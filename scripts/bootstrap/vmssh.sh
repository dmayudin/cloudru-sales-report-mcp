#!/usr/bin/env bash
# SSH/SCP wrapper for the runtime VM with a pinned host key.
# Env: VM_IP (required), VM_KEY (private key path), VM_KNOWN_HOSTS (file with the verified host key), VM_USER (default deploy)
# Usage: vmssh.sh ssh <cmd...> | vmssh.sh scp <files...>   (scp copies into /tmp on the VM)
set -euo pipefail
: "${VM_IP:?set VM_IP}"; : "${VM_KEY:?set VM_KEY}"; : "${VM_KNOWN_HOSTS:?set VM_KNOWN_HOSTS}"
U="${VM_USER:-deploy}"
OPTS=(-i "$VM_KEY" -o UserKnownHostsFile="$VM_KNOWN_HOSTS" -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o BatchMode=yes)
mode="$1"; shift
if [ "$mode" = scp ]; then exec scp "${OPTS[@]}" "$@" "$U@$VM_IP:/tmp/"; else exec ssh "${OPTS[@]}" "$U@$VM_IP" "$@"; fi
