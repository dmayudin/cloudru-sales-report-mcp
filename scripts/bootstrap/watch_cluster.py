#!/usr/bin/env python3
"""Poll a Managed ClickHouse cluster until hosts appear or the status leaves DEPLOYING; detects the known
"stuck in DEPLOYING" platform failure (creation operation frozen, hosts empty) and prints a verdict.
Usage: watch_cluster.py [--marker FILE] <cluster_id> [--minutes 45] [--interval 60]"""
import json, sys, time
from pathlib import Path
import httpx
from api import token, ROOT

args = sys.argv[1:]; marker = ROOT / 'bootstrap-connection.json'
if '--marker' in args: i = args.index('--marker'); marker = Path(args[i + 1]); del args[i:i + 2]
minutes = int(args[args.index('--minutes') + 1]) if '--minutes' in args else 45
interval = int(args[args.index('--interval') + 1]) if '--interval' in args else 60
cid = args[0]; t = token(marker); deadline = time.time() + minutes * 60; last = None
while True:
    r = httpx.get(f'https://clickhouse.api.cloud.ru/v1/clusters/{cid}', headers={'Authorization': 'Bearer ' + t}, timeout=30)
    if r.status_code == 401: t = token(marker); continue
    d = r.json(); st = (d.get('status'), d.get('health'), len(d.get('hosts', [])))
    if st != last: print(time.strftime('%H:%M:%S'), *st, json.dumps(d.get('hosts', []))[:300], flush=True); last = st
    if st[0] != 'DEPLOYING' or st[2] > 0:
        print('READY' if st[2] > 0 else 'STATE_CHANGED'); break
    if time.time() > deadline:
        ops = httpx.get(f'https://clickhouse.api.cloud.ru/v1/clusters/{cid}/operations', headers={'Authorization': 'Bearer ' + t}, timeout=30).json()
        op = next((o for o in ops.get('operations', []) if 'Создание' in o.get('description', '') or not o.get('done')), {})
        print('STUCK: still DEPLOYING with no hosts after', minutes, 'minutes; creation operation updated_at =', op.get('updated_at'),
              '\nKnown platform failure (backing Kubernetes cluster not provisioned). The cluster cannot be deleted by the API '
              'while DEPLOYING; file the support ticket from references/troubleshooting.md and do not create more clusters.')
        break
    time.sleep(interval)
