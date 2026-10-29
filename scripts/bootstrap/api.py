#!/usr/bin/env python3
"""Read-only Cloud.ru API probe with the bootstrap key: prints HTTP status and a body excerpt, never secrets.
Usage: api.py [--marker FILE] URL [URL...]   (GET only; use api_write.py for the few approved write calls)"""
import json, sys
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]


def token(marker):
    c = json.loads(Path(json.loads(marker.read_text())['credentials_file']).read_text())
    r = httpx.post('https://iam.api.cloud.ru/api/v2/auth/token', json={'keyId': c['key_id'], 'secret': c['key_secret']}, timeout=30)
    r.raise_for_status(); return r.json()['access_token']


def main():
    args = sys.argv[1:]; marker = ROOT / 'bootstrap-connection.json'
    if args[:1] == ['--marker']: marker = Path(args[1]); args = args[2:]
    t = token(marker)
    for url in args:
        try:
            r = httpx.get(url, headers={'Authorization': 'Bearer ' + t}, timeout=30)
            print(f'{r.status_code} {url}\n   {r.text[:1500]}\n')
        except Exception as e:
            print(f'ERR {url}: {type(e).__name__}')


if __name__ == '__main__': main()
