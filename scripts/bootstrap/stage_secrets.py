#!/usr/bin/env python3
"""Local helper: assemble the one-time /root/bootstrap-secrets.json for the VM (mode 0600). Prints nothing secret.
Usage: stage_secrets.py <deploy-workdir> <output-file> [--marker FILE] [--from-state]
  --from-state: take the runtime key from the Terraform output of the created service account
                (service_account_key_id/secret) instead of the bootstrap personal key."""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
args = sys.argv[1:]; marker = ROOT / 'bootstrap-connection.json'
if '--marker' in args:
    i = args.index('--marker'); marker = Path(args[i + 1]); del args[i:i + 2]
from_state = '--from-state' in args
args = [a for a in args if a != '--from-state']
work, out = Path(args[0]), Path(args[1])
dep = json.loads((work / 'deployment.json').read_text())
tf = json.loads((work / 'secret.env.json').read_text())
if from_state:
    o = json.loads(subprocess.run([sys.executable, str(Path(__file__).with_name('tfrun.py')), '--marker', str(marker), str(work),
                                   'output', '-json'], capture_output=True, text=True, check=True).stdout)
    key_id, key_secret = o['service_account_key_id']['value'], o['service_account_key_secret']['value']
else:
    user = json.loads(Path(json.loads(marker.read_text())['credentials_file']).read_text())
    key_id, key_secret = user['key_id'], user['key_secret']
if out.exists(): out.unlink()
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    json.dump({'key_id': key_id, 'key_secret': key_secret, 'tenant_id': dep['tenant_id'],
               'importer_password': tf['TF_VAR_importer_password'], 'reader_password': tf['TF_VAR_reader_password']}, f)
print('staged', out, 'mode 600', '(service account key)' if from_state else '(bootstrap personal key)')
