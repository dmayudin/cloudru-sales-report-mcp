#!/usr/bin/env python3
"""Build an allowlisted, credential-free distribution archive."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
INCLUDE=('cloudru_mcp','deploy','skills','scripts','requirements.lock','pyproject.toml','README.md','INSTALL.md','examples/sales-demo.csv','docs','prompts','tests','LICENSE','SECURITY.md','AGENTS.md')


def build(output=None):
    output=output or ROOT/'dist'/'cloudru-sales-report-mcp-0.4.0.zip'
    output.parent.mkdir(parents=True,exist_ok=True)
    entries={}
    for name in INCLUDE:
        p=ROOT/name
        paths=p.rglob('*') if p.is_dir() else [p]
        for f in paths:
            if f.is_symlink(): raise ValueError('Release cannot contain symlinks')
            if not f.is_file() or '__pycache__' in f.parts or f.name=='.DS_Store': continue
            rel=f.relative_to(ROOT)
            if rel.parts[0]=='cloudru_mcp' and f.suffix!='.py' and f.name!='terraform.rc': continue
            if rel.parts[0]=='scripts' and f.suffix not in ('.py','.sh','.template'): continue
            if rel.parts[0]=='deploy' and not (f.name.endswith(('.example','.example.json','.service','.timer')) or f.name in ('install-on-cloud.sh','terraform.rc')): continue
            if rel.parts[0]=='skills' and f.suffix not in ('.md','.png'): continue
            entries[str(f.relative_to(ROOT))]=f.read_bytes()
    manifest={name:hashlib.sha256(data).hexdigest() for name,data in sorted(entries.items())}
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for name,data in sorted(entries.items()): z.writestr('cloudru-sales-report-mcp/'+name,data)
        z.writestr('cloudru-sales-report-mcp/MANIFEST.json',json.dumps(manifest,indent=2))
    output.with_suffix('.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n')
    return output


if __name__=='__main__': print(build())
