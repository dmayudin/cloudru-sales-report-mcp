#!/usr/bin/env python3
"""One explicitly approved write call to a Cloud.ru API (e.g. DELETE a stuck cluster after user consent).
Usage: api_write.py [--marker FILE] METHOD URL [json-body]. Prints status and body excerpt only."""
import json, sys
from pathlib import Path
import httpx
from api import token, ROOT


def main():
    args = sys.argv[1:]; marker = ROOT / 'bootstrap-connection.json'
    if args[:1] == ['--marker']: marker = Path(args[1]); args = args[2:]
    method, url = args[0], args[1]
    body = json.loads(args[2]) if len(args) > 2 else None
    r = httpx.request(method, url, headers={'Authorization': 'Bearer ' + token(marker)}, json=body, timeout=60)
    print(r.status_code, r.headers.get('grpc-message', ''), r.text[:2000])


if __name__ == '__main__': main()
