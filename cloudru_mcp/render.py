"""Render the fixed bootstrap template. No API calls, credentials or local application launch."""
import argparse
import json
import os
from pathlib import Path
from .infra import Deployment, template


def main():
    p=argparse.ArgumentParser()
    p.add_argument('config',type=Path)
    p.add_argument('output',type=Path)
    args=p.parse_args()
    c=Deployment.model_validate_json(args.config.read_text())
    rendered=json.dumps(template(c),indent=2)
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: f.write(rendered+'\n')
    print('Template rendered. No cloud requests made.')


if __name__=='__main__': main()
