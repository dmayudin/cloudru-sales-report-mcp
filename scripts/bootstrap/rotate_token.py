#!/usr/bin/env python3
"""Run as root on the VM: issue a new MCP client token (old one stops working after service restart).
Usage: rotate_token.py [--token-days N]. Then re-register the client with the new /etc/cloudru-sales/client-token."""
import hashlib, os, re, secrets, sys, time
from pathlib import Path

days = int(sys.argv[sys.argv.index('--token-days') + 1]) if '--token-days' in sys.argv else 7
env = Path('/etc/cloudru-sales/secrets.env'); tok = Path('/etc/cloudru-sales/client-token')
token = secrets.token_urlsafe(48)
text = env.read_text()
text = re.sub(r'^CLOUDRU_MCP_TOKEN_SHA256=.*$', 'CLOUDRU_MCP_TOKEN_SHA256="' + hashlib.sha256(token.encode()).hexdigest() + '"', text, flags=re.M)
text = re.sub(r'^CLOUDRU_MCP_TOKEN_EXPIRES=.*$', 'CLOUDRU_MCP_TOKEN_EXPIRES="' + str(int(time.time()) + days * 86400) + '"', text, flags=re.M)
tmp = env.with_suffix('.tmp'); fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
with os.fdopen(fd, 'w') as f: f.write(text)
os.replace(tmp, env); os.system('chgrp cloudru-sales ' + str(env))
if tok.exists(): tok.unlink()
fd = os.open(tok, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f: f.write(token + '\n')
print(f'new client token written, valid {days} days; restart cloudru-sales-mcp and re-register the client')
