#!/usr/bin/env bash
# Runs as root on the fresh Ubuntu 24.04 runtime VM. Idempotent. No secrets in arguments or output.
# Usage: vm-setup.sh <public-mcp-hostname>   (package tarball expected at /tmp/cloudru-sales-mcp.tgz)
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
HOST="$1"
# The VM subnet's private DNS (Evolution DNS) is not reachable from the VM; use public resolvers for apt/ACME/API.
if ! grep -qs '^DNS=' /etc/systemd/resolved.conf.d/public-dns.conf 2>/dev/null; then
  mkdir -p /etc/systemd/resolved.conf.d
  printf '[Resolve]\nDNS=8.8.8.8 1.1.1.1\nFallbackDNS=8.8.4.4\n' > /etc/systemd/resolved.conf.d/public-dns.conf
  systemctl restart systemd-resolved
fi
apt-get update -qq
apt-get install -y -qq python3 python3-venv ca-certificates curl unzip >/dev/null
# Terraform CLI: HashiCorp downloads (apt repo and releases.hashicorp.com) return 404 from Russian networks.
# OpenTofu from the official GitHub release, SHA256-verified, is CLI-compatible with the provider.
if ! command -v tofu >/dev/null; then
  TOFU=1.8.8; cd /tmp
  curl -fsSLO "https://github.com/opentofu/opentofu/releases/download/v${TOFU}/tofu_${TOFU}_linux_amd64.zip"
  curl -fsSLO "https://github.com/opentofu/opentofu/releases/download/v${TOFU}/tofu_${TOFU}_SHA256SUMS"
  grep "tofu_${TOFU}_linux_amd64.zip" "tofu_${TOFU}_SHA256SUMS" | sha256sum -c -
  unzip -o -q "tofu_${TOFU}_linux_amd64.zip" tofu -d /usr/local/bin; chmod 755 /usr/local/bin/tofu
  ln -sf /usr/local/bin/tofu /usr/local/bin/terraform
  rm -f "tofu_${TOFU}_linux_amd64.zip" "tofu_${TOFU}_SHA256SUMS"
fi
# Caddy from the Ubuntu repository: automatic Let's Encrypt via HTTP-01 (needs 80/tcp open, see template rule "acme").
if ! command -v caddy >/dev/null; then apt-get install -y -qq caddy >/dev/null; fi
mkdir -p /opt/cloudru-sales-mcp && tar -xzf /tmp/cloudru-sales-mcp.tgz -C /opt/cloudru-sales-mcp
bash /opt/cloudru-sales-mcp/deploy/install-on-cloud.sh
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
    request_body {
        max_size 6MB
    }
    reverse_proxy 127.0.0.1:8000
}
CADDY
systemctl enable --now caddy >/dev/null
systemctl reload caddy || true
tofu version | head -1; caddy version; /opt/cloudru-sales-mcp/.venv/bin/python --version
echo "VM setup done"
