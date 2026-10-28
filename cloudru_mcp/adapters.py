"""Bounded service adapters. Control-plane paths are tracked in docs/research.md."""
from datetime import datetime, timezone
import json
import logging
import ssl
import time
from typing import Literal
import httpx
from .config import Settings, SafeError, identifier, uuid
from .sales import MAX_BYTES, snapshot_id, validate_snapshot_id, summary

log = logging.getLogger(__name__)
MAX_RESPONSE = 2_000_000


class CloudAPI:
    def __init__(self, settings: Settings, client=None):
        self.s = settings
        self.client = client or httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
        self.token = None
        self.expires = 0.0

    def _request(self, method, url, **kwargs):
        try:
            with self.client.stream(method, url, **kwargs) as r:
                code = r.status_code
                if code >= 300:
                    return code, None
                body = bytearray()
                for part in r.iter_bytes():
                    body.extend(part)
                    if len(body) > MAX_RESPONSE:
                        raise SafeError("LIMIT: upstream response too large; narrow resource scope")
                return code, json.loads(body)
        except (httpx.HTTPError, ValueError):
            raise SafeError("UPSTREAM: network failure or invalid JSON; no change was requested") from None

    def _auth(self):
        if not self.s.key_id or not self.s.key_secret:
            raise SafeError("AUTH: configure CLOUDRU_KEY_ID and CLOUDRU_KEY_SECRET outside the chat")
        code, data = self._request("POST", "https://iam.api.cloud.ru/api/v2/auth/token",
                                   json={"keyId": self.s.key_id, "secret": self.s.key_secret})
        if code != 200 or not isinstance(data, dict):
            raise SafeError(f"AUTH: IAM returned HTTP {code}")
        self.token = data.get('access_token') or data.get('token')
        if not isinstance(self.token, str) or not self.token:
            raise SafeError("AUTH: IAM response has no access token")
        self.expires = time.monotonic() + 240

    def get(self, service, path, params=None):
        host = {"dp": "dataplatform.api.cloud.ru", "ch": "clickhouse.api.cloud.ru"}[service]
        if not self.token or time.monotonic() >= self.expires:
            self._auth()
        for attempt in range(2):
            code, data = self._request("GET", f"https://{host}{path}", params=params,
                                      headers={"Authorization": f"Bearer {self.token}"})
            log.info("service=%s method=GET status=%s", service, code)
            if code == 401 and attempt == 0:
                self._auth()
                continue
            if code != 200:
                raise SafeError(f"UPSTREAM: {service} HTTP {code}; check permissions/resource and retry read only")
            return data

    def inspect(self, kind: Literal['data_platform', 'managed_bi', 'clickhouse'], resource_id):
        if not self.s.project_id:
            raise SafeError("CONFIG: set CLOUDRU_PROJECT_ID before inspecting cloud resources")
        resource_id = uuid(resource_id)
        allow, service, collection = {
            'data_platform': (self.s.allowed_dp_clusters, 'dp', 'clusters'),
            'managed_bi': (self.s.allowed_bis, 'dp', 'bis'),
            'clickhouse': (self.s.allowed_ch_clusters, 'ch', 'clusters'),
        }[kind]
        if resource_id not in allow:
            raise SafeError("ACCESS: resource is not in the operator-configured allowlist")
        data = self.get(service, f"/v1/{collection}/{resource_id}")
        if not isinstance(data, dict):
            raise SafeError("CONTRACT: unexpected resource response; verify current Cloud.ru OpenAPI")
        for wrapper in ('cluster', 'bi'):
            if isinstance(data.get(wrapper), dict):
                data = data[wrapper]
                break
        owner = data.get('projectId', data.get('project_id'))
        if owner and str(owner) != self.s.project_id:
            raise SafeError("ACCESS: returned resource belongs to another project")
        # Explicit allowlist permits lookup even when the provider omits project_id.
        safe = {k: data[k] for k in ('id','name','status','state','createdAt','created_at')
                if isinstance(data.get(k), (str, int, bool))}
        if not safe:
            raise SafeError("CONTRACT: no recognized fields; inspect provider schema before continuing")
        return {"kind": kind, "resource_id": resource_id, "resource": safe,
                "contract_evidence": "historical_workspace_http_200; live verification required"}


class ObjectStore:
    def __init__(self, settings, client=None):
        self.s = settings
        self._client = client

    @property
    def client(self):
        if not self.s.bucket:
            raise SafeError("CONFIG: set CLOUDRU_S3_BUCKET to an existing private bucket")
        if self._client is None:
            if not self.s.s3_access_key or not self.s.s3_secret_key:
                raise SafeError("AUTH: configure dedicated S3 keys; access key format tenant_id:key_id")
            import boto3
            from botocore.config import Config
            self._client = boto3.client('s3', endpoint_url='https://s3.cloud.ru', region_name='ru-central-1',
                aws_access_key_id=self.s.s3_access_key, aws_secret_access_key=self.s.s3_secret_key,
                config=Config(connect_timeout=10, read_timeout=30, retries={'total_max_attempts': 1},
                              s3={'addressing_style': 'path'}))
        return self._client

    def _call(self, method, **kwargs):
        try:
            return getattr(self.client, method)(Bucket=self.s.bucket, **kwargs)
        except SafeError:
            raise
        except Exception:
            # botocore exceptions may contain object names and provider bodies.
            raise SafeError("S3: operation failed; check credentials, bucket permissions and connectivity") from None

    def list(self, cursor=None, limit=20):
        args = {"Prefix": "incoming/", "MaxKeys": limit}
        if cursor:
            args['ContinuationToken'] = cursor
        result = self._call('list_objects_v2', **args)
        return {"objects": [{"key": o['Key'], "bytes": o['Size']} for o in result.get('Contents', [])],
                "next_cursor": result.get('NextContinuationToken')}

    def put(self, data):
        self.s.require_write()
        key = f"incoming/{snapshot_id(data)}.csv"
        # Content-addressed writes always write the exact same bytes under this key.
        self._call('put_object', Key=key, Body=data, ContentType='text/csv; charset=utf-8',
                   Metadata={'sha256': snapshot_id(data)})
        return key

    def read(self, sid):
        validate_snapshot_id(sid)
        result = self._call('get_object', Key=f'incoming/{sid}.csv')
        body = result['Body']
        try:
            if result.get('ContentLength', MAX_BYTES + 1) > MAX_BYTES:
                raise SafeError("LIMIT: S3 object exceeds 5 MB")
            data = body.read(MAX_BYTES + 1)
        finally:
            body.close()
        if len(data) > MAX_BYTES or snapshot_id(data) != sid:
            raise SafeError("INTEGRITY: S3 content does not match snapshot_id")
        return data


class ClickHouse:
    def __init__(self, settings, client=None):
        self.s = settings
        self.client = client
        self.db = identifier(settings.database)

    def _execute(self, query, data=b'', params=None):
        endpoint = self.s.ch_endpoint()
        if self.client is None:
            verify = ssl.create_default_context(cafile=self.s.clickhouse_ca or None)
            self.client = httpx.Client(timeout=60, follow_redirects=False, trust_env=False, verify=verify)
        if not self.s.clickhouse_user or not self.s.clickhouse_password:
            raise SafeError("AUTH: configure dedicated ClickHouse credentials")
        args = {'query': query, 'wait_end_of_query': '1', 'max_execution_time': '30', **(params or {})}
        try:
            with self.client.stream('POST', endpoint, params=args, content=data,
                    headers={'X-ClickHouse-User': self.s.clickhouse_user,
                             'X-ClickHouse-Key': self.s.clickhouse_password}) as r:
                if r.status_code != 200 or r.headers.get('X-ClickHouse-Exception-Code'):
                    raise SafeError(f"CLICKHOUSE: HTTP {r.status_code}; check grants/schema; verify outcome before retrying writes")
                content = bytearray()
                for chunk in r.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE:
                        raise SafeError("LIMIT: ClickHouse response too large")
                return bytes(content)
        except httpx.HTTPError:
            raise SafeError("CLICKHOUSE: network failure; write outcome may be unknown; retry only the same snapshot") from None

    def _json(self, query, params=None):
        try:
            result = json.loads(self._execute(query + ' FORMAT JSON', params=params))
            return result['data']
        except (ValueError, KeyError, TypeError):
            raise SafeError("CONTRACT: ClickHouse did not return the expected JSON data") from None

    def prepare(self):
        self.s.require_write()
        # Database must already exist. No cluster, user, grant or database provisioning.
        self._execute(f'''CREATE TABLE IF NOT EXISTS {self.db}.mcp_sales_v1 (
            snapshot_id FixedString(64), line_id String, date Date, sku String,
            product String, category String, channel String, qty Decimal(18,2),
            net_revenue Decimal(18,2), net_cogs Decimal(18,2), fees Decimal(18,2), currency FixedString(3)
        ) ENGINE = ReplacingMergeTree ORDER BY (snapshot_id, line_id)''')
        self._execute(f'''CREATE TABLE IF NOT EXISTS {self.db}.mcp_snapshots_v1 (
            snapshot_id FixedString(64), row_count UInt32, imported_at DateTime64(3, 'UTC')
        ) ENGINE = ReplacingMergeTree ORDER BY snapshot_id''')
        self._execute(f'''CREATE VIEW IF NOT EXISTS {self.db}.mcp_sales_current_v1 AS
            SELECT *, net_revenue-net_cogs-fees AS contribution
            FROM {self.db}.mcp_sales_v1 FINAL WHERE snapshot_id = (
                SELECT snapshot_id FROM {self.db}.mcp_snapshots_v1 FINAL
                ORDER BY imported_at DESC, snapshot_id DESC LIMIT 1)''')
        return {"database": self.db, "tables": ['mcp_sales_v1', 'mcp_snapshots_v1'],
                "bi_view": 'mcp_sales_current_v1', "status": 'schema_ready'}

    def committed(self, sid):
        return self._json(f'SELECT row_count FROM {self.db}.mcp_snapshots_v1 FINAL WHERE snapshot_id={{sid:String}}',
                          {'param_sid': validate_snapshot_id(sid)})

    def totals(self, sid):
        return self._json(f'''SELECT count() AS rows, toString(sum(qty)) AS qty,
            toString(sum(net_revenue)) AS net_revenue, toString(sum(net_cogs)) AS net_cogs,
            toString(sum(fees)) AS fees FROM {self.db}.mcp_sales_v1 FINAL
            WHERE snapshot_id={{sid:String}}''', {'param_sid': validate_snapshot_id(sid)})[0]

    def import_rows(self, sid, rows):
        from decimal import Decimal
        self.s.require_write()
        validate_snapshot_id(sid)
        expected = summary(rows)
        existed = bool(self.committed(sid))
        if not existed:
            payload = ''.join(json.dumps({'snapshot_id': sid, **row}, ensure_ascii=False) + '\n' for row in rows).encode()
            self._execute(f'INSERT INTO {self.db}.mcp_sales_v1 FORMAT JSONEachRow', payload)
        actual = self.totals(sid)
        if int(actual['rows']) != expected['rows'] or any(Decimal(actual[k]) != Decimal(expected[k]) for k in ('qty','net_revenue','net_cogs','fees')):
            raise SafeError("RECONCILIATION: imported totals differ; snapshot was not published; previous view remains active")
        if not existed:
            payload = json.dumps({'snapshot_id': sid, 'row_count': len(rows),
                'imported_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}).encode() + b'\n'
            self._execute(f'INSERT INTO {self.db}.mcp_snapshots_v1 FORMAT JSONEachRow', payload)
        return {"snapshot_id": sid, "status": 'already_imported' if existed else 'imported', "totals": expected}

    def report(self, sid, group_by, limit=20):
        from decimal import Decimal
        validate_snapshot_id(sid)
        if group_by not in ('day','sku','channel','category'):
            raise SafeError("INPUT: unsupported grouping")
        if not 1 <= limit <= 100:
            raise SafeError("INPUT: report limit must be 1..100")
        manifest = self.committed(sid)
        if not manifest:
            raise SafeError("NOT_READY: snapshot has not passed import reconciliation")
        totals = self.totals(sid)
        if int(totals['rows']) != int(manifest[0]['row_count']):
            raise SafeError("INTEGRITY: committed snapshot row count changed")
        dimension = 'date' if group_by == 'day' else group_by
        result = self._json(f'''SELECT toString({dimension}) AS label, count() AS rows,
            toString(sum(net_revenue)) AS revenue, toString(sum(net_cogs)) AS cogs,
            toString(sum(fees)) AS fees FROM {self.db}.mcp_sales_v1 FINAL
            WHERE snapshot_id={{sid:String}} GROUP BY {dimension}
            ORDER BY sum(net_revenue) DESC, label LIMIT {limit + 1}''', {'param_sid': sid})
        for row in result:
            rev = Decimal(row['revenue'])
            profit = rev - Decimal(row['cogs']) - Decimal(row['fees'])
            row['contribution'] = str(profit)
            row['margin_pct'] = str((profit / rev * 100).quantize(Decimal('.01'))) if rev else None
        revenue = Decimal(totals['net_revenue'])
        profit = revenue - Decimal(totals['net_cogs']) - Decimal(totals['fees'])
        return {"snapshot_id": sid, "group_by": group_by, "currency": "RUB", "totals": {
            **totals, "contribution": str(profit), "margin_pct": str((profit / revenue * 100).quantize(Decimal('.01'))) if revenue else None},
            "groups": result[:limit], "truncated": len(result) > limit,
            "bi_view": f'{self.db}.mcp_sales_current_v1'}
