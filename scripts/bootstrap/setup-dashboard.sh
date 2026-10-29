#!/bin/bash
# usage: sudo bash setup-dashboard.sh <host>   (on the runtime VM, after vm-setup.sh)
# Serves the automatic sales dashboard at https://<host>/report/ behind HTTP basic auth.
# The password is generated here and stays in /etc/cloudru-sales/report-password (root, 0600);
# the agent copies it to the user's clipboard, never into chat.
set -euo pipefail
HOST="$1"; DIR=/srv/cloudru-sales-report; PW=/etc/cloudru-sales/report-password; USERS=/etc/caddy/report-users
install -d -o cloudru-sales -g caddy -m 2750 "$DIR"
if [ ! -s "$PW" ]; then umask 077; openssl rand -base64 18 | tr -d '/+=\n' > "$PW"; fi
chmod 600 "$PW"; chown root:root "$PW"
HASH=$(caddy hash-password --plaintext "$(cat "$PW")")
umask 027; printf 'sales %s\n' "$HASH" > "$USERS"; chown root:caddy "$USERS"; chmod 640 "$USERS"
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
    request_body {
        max_size 6MB
    }
    redir /report /report/
    handle_path /report/* {
        basicauth {
            import $USERS
        }
        header {
            Cache-Control "no-store"
            X-Robots-Tag "noindex"
            Referrer-Policy "no-referrer"
            Content-Security-Policy "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        }
        root * $DIR
        file_server
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
CADDY
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
mkdir -p /etc/systemd/system/cloudru-sales-mcp.service.d
for u in cloudru-sales-mcp cloudru-sales-refresh; do mkdir -p /etc/systemd/system/$u.service.d; printf "[Service]\nReadWritePaths=%s\n" "$DIR" > /etc/systemd/system/$u.service.d/dashboard.conf; done
ENV=/etc/cloudru-sales/runtime.env
grep -q '^CLOUDRU_DASHBOARD_DIR=' "$ENV" || echo "CLOUDRU_DASHBOARD_DIR=$DIR" >> "$ENV"
grep -q '^CLOUDRU_DASHBOARD_URL=' "$ENV" || echo "CLOUDRU_DASHBOARD_URL=https://$HOST/report/" >> "$ENV"
systemctl daemon-reload; systemctl reload caddy; systemctl restart cloudru-sales-mcp
echo "dashboard ready: https://$HOST/report/ (user: sales)"
