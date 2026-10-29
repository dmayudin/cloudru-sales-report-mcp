#!/usr/bin/env python3
"""Run Terraform/OpenTofu with the bootstrap Cloud.ru key loaded from the protected marker file.
Never prints secrets. Usage: tfrun.py [--marker FILE] <workdir> <terraform args...>

The marker is written by scripts/connect_cloud.py (default: <package>/bootstrap-connection.json).
Optional <workdir>/secret.env.json holds generated TF_VAR_* passwords (mode 0600)."""
import json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RC = ROOT / 'cloudru_mcp' / 'terraform.rc'


def main():
    args = sys.argv[1:]
    marker = ROOT / 'bootstrap-connection.json'
    if args[:1] == ['--marker']:
        marker = Path(args[1]); args = args[2:]
    if len(args) < 2:
        print(__doc__); return 2
    workdir, tf_args = Path(args[0]), args[1:]
    creds = json.loads(Path(json.loads(marker.read_text())['credentials_file']).read_text())
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'SSL_CERT_FILE') if k in os.environ}
    if os.environ.get('TF_LOG'): env['TF_LOG'] = os.environ['TF_LOG']
    env.update(AUTH_KEY_ID=creds['key_id'], AUTH_SECRET=creds['key_secret'], TF_IN_AUTOMATION='1',
               TF_CLI_CONFIG_FILE=str(RC))
    extra = workdir / 'secret.env.json'
    if extra.exists(): env.update(json.loads(extra.read_text()))
    binary = os.environ.get('CLOUDRU_TERRAFORM_BIN', 'terraform')
    return subprocess.run([binary, *tf_args], cwd=workdir, env=env).returncode


if __name__ == '__main__': raise SystemExit(main())
