"""One scheduled full-snapshot refresh using the same core as MCP tools."""
import argparse
import json
import sys
from .config import Settings, SafeError
from .server import Services


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--filename', help='CSV basename on the cloud executor')
    source.add_argument('--source', action='store_true', help='Fetch configured private S3 source')
    args = parser.parse_args()
    try:
        svc = Services(Settings.from_env())
        if args.source:
            from .sources import fetch
            print(json.dumps(fetch(svc),ensure_ascii=False))
            return 0
        preview = svc.preview(args.filename)
        sid = preview['snapshot_id']
        svc.upload(args.filename, sid)
        result = svc.ingest(sid)
        print(json.dumps(result, ensure_ascii=False))
    except SafeError as e:
        print(json.dumps({'status':'failed', 'reason':str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception:
        print('{"status":"failed","reason":"Unexpected failure; details suppressed"}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
