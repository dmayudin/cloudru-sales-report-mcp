"""Fetch a full snapshot from one operator-scoped private S3 key, without local user files."""
import json
import os
from pathlib import Path
from .config import SafeError
from .sales import MAX_BYTES, parse, snapshot_id, summary


def source_config():
    path=Path(os.environ.get('CLOUDRU_SOURCE_FILE','/etc/cloudru-sales/source.json'))
    try: cfg=json.loads(path.read_text())
    except (OSError,ValueError): raise SafeError('SOURCE_CONFIG: configure private S3 source on server') from None
    if set(cfg)-{'kind','key'} or cfg.get('kind')!='s3_object':
        raise SafeError('SOURCE_CONFIG: only s3_object is supported for scheduled fetching')
    key=cfg.get('key','')
    if not isinstance(key,str) or not key.startswith('source/') or len(key)>512 or '..' in key.split('/'):
        raise SafeError('SOURCE_CONFIG: source key must be scoped to source/ in configured bucket')
    return cfg


def fetch(svc):
    svc.s.require_write()
    cfg=source_config()
    response=svc.store._call('get_object',Key=cfg['key'])
    body=response['Body']
    try:
        if response.get('ContentLength',MAX_BYTES+1)>MAX_BYTES:
            raise SafeError('LIMIT: source snapshot exceeds size limit')
        data=body.read(MAX_BYTES+1)
    finally: body.close()
    rows=parse(data)
    sid=snapshot_id(data)
    # No modifications until validation passed. Content-addressed import retains history.
    svc.store.put(data)
    result=svc.ch.import_rows(sid,rows)
    if hasattr(svc,'after_import'): result=svc.after_import(sid,result)
    return {'snapshot_id':sid,'source':'configured_private_s3_object','totals':summary(rows),'import':result}
