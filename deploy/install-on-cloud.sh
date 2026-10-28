#!/usr/bin/env bash
# Execute only on the provisioned Ubuntu cloud VM, after uploading this package.
# No secrets in cloud-init, command arguments, or installation output.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo 'Run as root on the cloud VM' >&2; exit 1; fi
if [[ ! -f /opt/cloudru-sales-mcp/requirements.lock ]]; then echo 'Upload package to /opt/cloudru-sales-mcp first' >&2; exit 1; fi
if ! id cloudru-sales >/dev/null 2>&1; then
  useradd --system --home /var/lib/cloudru-sales --shell /usr/sbin/nologin cloudru-sales
fi
install -d -m 0700 -o cloudru-sales -g cloudru-sales /var/lib/cloudru-sales /var/lib/cloudru-sales/imports
install -d -m 0750 -o root -g cloudru-sales /etc/cloudru-sales
python3 -m venv /opt/cloudru-sales-mcp/.venv
/opt/cloudru-sales-mcp/.venv/bin/pip install --requirement /opt/cloudru-sales-mcp/requirements.lock
install -m 0644 /opt/cloudru-sales-mcp/deploy/cloudru-sales-mcp.service /etc/systemd/system/cloudru-sales-mcp.service
systemctl daemon-reload
# Deliberately no start: wait for protected credentials, TLS and operator configuration.
echo 'Package installed. Configure credentials, Terraform binary, TLS and runtime.env before enabling service.'
