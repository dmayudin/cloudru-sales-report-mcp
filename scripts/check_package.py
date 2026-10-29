#!/usr/bin/env python3
"""Check the release allowlist, portable documentation and accidental secrets."""
import re
from pathlib import Path
from urllib.parse import unquote
from build_release import INCLUDE

ROOT = Path(__file__).resolve().parents[1]


def main():
    errors = []
    files = []
    for name in INCLUDE:
        path = ROOT / name
        if not path.exists():
            errors.append(f"Missing package entry: {name}")
        files.extend(path.rglob('*') if path.is_dir() else [path])
    for path in files:
        if '__pycache__' in path.parts or not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if path.is_symlink():
            errors.append(f"Symlink: {rel}")
            continue
        if path.name in {'credentials.json', '.env', 'secrets.env', 'client-token',
                         'bootstrap-connection.json', 'installation.json'} or '.tfstate' in path.name:
            errors.append(f"Private runtime file: {rel}")
        if path.suffix in {'.png', '.jpg', '.jpeg', '.gif', '.zip'}:
            continue  # binary assets (screenshots): no text checks
        text = path.read_text(encoding='utf-8')
        if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)', text):
            errors.append(f"Possible secret: {rel}")
        if path.suffix == '.md':
            if re.search(r'/Users/[^/\s]+/', text):
                errors.append(f"Personal absolute path: {rel}")
            for link in re.findall(r'\]\(([^\s)]+)\)', text):
                if '://' in link or link.startswith(('#', 'mailto:')):
                    continue
                target = unquote(link.split('#', 1)[0])
                if target and not (path.parent / target).exists():
                    errors.append(f"Broken link in {rel}: {target}")
    if errors:
        raise SystemExit('\n'.join(errors))
    print('Package checks passed: links, portability, required files and secret patterns.')


if __name__ == '__main__':
    main()
