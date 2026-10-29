#!/usr/bin/env python3
"""Agent-neutral file installation. Does not start a server or edit MCP credentials."""
import argparse
import json
from pathlib import Path
import shutil

NAME='cloudru-sales-report-mcp'
VERSION='0.3.2'
RUNTIME=('cloudru_mcp','deploy','requirements.lock','pyproject.toml','README.md','INSTALL.md',
         'examples/sales-demo.csv','docs','prompts','scripts','skills','LICENSE','SECURITY.md')


def copy(source,target):
    if source.is_symlink(): raise ValueError('Symlinks are not accepted')
    if source.is_dir():
        target.mkdir()
        for item in source.iterdir():
            if item.name in ('__pycache__','.DS_Store'): continue
            copy(item,target/item.name)
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)


def install(package,skill_dir,runtime_dir,replace=False):
    package,skill_dir,runtime_dir=map(lambda p:Path(p).resolve(),(package,skill_dir,runtime_dir))
    if skill_dir.exists() or runtime_dir.exists():
        if not replace: raise ValueError('Destination exists; rerun with --replace to update (runtime dir must hold no state or secrets)')
        for d in (skill_dir,runtime_dir):
            if d.exists() and any(n in {'terraform.tfstate','secrets.env','approval.json','bootstrap-connection.json'} for n in (x.name for x in d.rglob('*'))):
                raise ValueError(f'{d} contains state or secrets; move them out before --replace')
        for d in (skill_dir,runtime_dir):
            if d.exists(): shutil.rmtree(d)
    if skill_dir in runtime_dir.parents or runtime_dir in skill_dir.parents or skill_dir==runtime_dir:
        raise ValueError('Skill and runtime directories must be separate')
    if package==runtime_dir or package in runtime_dir.parents or package in skill_dir.parents:
        raise ValueError('Install outside the source package')
    for name in RUNTIME:
        if not (package/name).exists(): raise ValueError('Incomplete release package')
    (skill_dir.parent).mkdir(parents=True,exist_ok=True)
    runtime_dir.mkdir(parents=True)
    try:
        for name in RUNTIME: copy(package/name,runtime_dir/name)
        copy(package/'skills'/NAME,skill_dir)
        (skill_dir/'installation.json').write_text(json.dumps({'runtime_root':str(runtime_dir),'package_version':VERSION},indent=2)+'\n')
    except Exception:
        shutil.rmtree(runtime_dir)
        if skill_dir.exists(): shutil.rmtree(skill_dir)
        raise
    return {'skill':str(skill_dir),'runtime':str(runtime_dir),'server_started':False,'cloud_connected':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skill-dir',required=True,type=Path,help='Exact agent skill directory, including skill name')
    p.add_argument('--runtime-dir',required=True,type=Path,help='Agent-managed package directory; not a running local service')
    p.add_argument('--replace',action='store_true',help='Replace an existing installation of this skill (no state/secrets inside)')
    a=p.parse_args()
    try: print(json.dumps(install(Path(__file__).resolve().parents[1],a.skill_dir,a.runtime_dir,a.replace)))
    except (ValueError,OSError) as e: p.error(str(e))


if __name__=='__main__': main()
