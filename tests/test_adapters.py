import io
import json
from pathlib import Path
import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber
import httpx
import pytest
from cloudru_mcp.config import Settings, SafeError
from cloudru_mcp.adapters import CloudAPI, ObjectStore, ClickHouse
from cloudru_mcp.sales import snapshot_id, parse

PID = '00000000-0000-4000-8000-000000000001'
RID = '00000000-0000-4000-8000-000000000002'
OTHER = '00000000-0000-4000-8000-000000000003'


def test_iam_refresh_and_bi_scope_and_redaction():
    calls, auth_calls = [], []
    def handler(req):
        calls.append(req)
        if req.url.host == 'iam.api.cloud.ru':
            assert req.url.path == '/api/v2/auth/token'
            assert json.loads(req.content) == {'keyId': 'id', 'secret': 'sensitive-secret'}
            auth_calls.append(req)
            return httpx.Response(200, json={'access_token': f'token-{len(auth_calls)}'})
        assert req.url.path == f'/v1/bis/{RID}'
        if len(auth_calls) == 1:
            return httpx.Response(401, json={'secret': 'do-not-return'})
        assert req.headers['Authorization'] == 'Bearer token-2'
        return httpx.Response(200, json={'id': RID, 'projectId': PID, 'status': 'READY', 'password': 'never-return'})
    s = Settings(project_id=PID, allowed_bis=(RID,), key_id='id', key_secret='sensitive-secret')
    api = CloudAPI(s, httpx.Client(transport=httpx.MockTransport(handler)))
    result = api.inspect('managed_bi', RID)
    assert result['resource']['status'] == 'READY'
    assert 'password' not in json.dumps(result)
    assert len(auth_calls) == 2
    with pytest.raises(SafeError, match='allowlist'):
        api.inspect('managed_bi', OTHER)
    assert len(calls) == 4


def test_wrong_project_rejected():
    s = Settings(project_id=PID, allowed_dp_clusters=(RID,), key_id='id', key_secret='key')
    api = CloudAPI(s, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200,
        json={'access_token':'abc'} if r.method == 'POST' else {'id': RID, 'project_id': OTHER}))))
    with pytest.raises(SafeError, match='another project'):
        api.inspect('data_platform', RID)


def test_upstream_errors_never_include_body():
    s = Settings(key_id='id', key_secret='key')
    api = CloudAPI(s, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text='super-secret'))))
    with pytest.raises(SafeError) as e:
        api.get('dp', '/v1/clusters')
    assert 'super-secret' not in str(e.value)


def test_cloud_redirect_not_followed():
    s = Settings(key_id='id', key_secret='key')
    client = httpx.Client(follow_redirects=False, transport=httpx.MockTransport(
        lambda r: httpx.Response(302, headers={'Location':'https://evil.example'})))
    with pytest.raises(SafeError, match='HTTP 302'):
        CloudAPI(s, client).get('dp', '/v1/clusters')


def s3():
    return boto3.client('s3', endpoint_url='https://s3.cloud.ru', region_name='ru-central-1',
        aws_access_key_id='test:key', aws_secret_access_key='test-secret')


def test_s3_pagination():
    client = s3()
    with Stubber(client) as stub:
        stub.add_response('list_objects_v2', {'Contents':[{'Key':'incoming/a.csv','Size':20}],
            'NextContinuationToken':'next','IsTruncated':True}, {'Bucket':'pilot','Prefix':'incoming/','MaxKeys':1})
        stub.add_response('list_objects_v2', {'Contents':[], 'IsTruncated':False},
            {'Bucket':'pilot','Prefix':'incoming/','MaxKeys':1,'ContinuationToken':'next'})
        store = ObjectStore(Settings(bucket='pilot'), client)
        assert store.list(limit=1)['next_cursor'] == 'next'
        assert store.list('next', 1)['next_cursor'] is None
        stub.assert_no_pending_responses()


def test_s3_hash_and_bounded_read():
    client = s3()
    data = b'hello'
    sid = snapshot_id(data)
    with Stubber(client) as stub:
        for content in (data, b'wrong'):
            stub.add_response('get_object', {'Body':StreamingBody(io.BytesIO(content), len(content)),
                'ContentLength':len(content)}, {'Bucket':'pilot','Key':f'incoming/{sid}.csv'})
        store = ObjectStore(Settings(bucket='pilot'), client)
        assert store.read(sid) == data
        with pytest.raises(SafeError, match='INTEGRITY'):
            store.read(sid)


def test_ch_error_and_timeout_not_retried():
    calls = []
    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout('password=leak', request=req)
    s = Settings(clickhouse_url='https://ch.example', clickhouse_user='u', clickhouse_password='p', allow_writes=True)
    ch = ClickHouse(s, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(SafeError) as e:
        ch.prepare()
    assert 'leak' not in str(e.value)
    assert len(calls) == 1


def test_reconciliation_blocks_manifest():
    s = Settings(allow_writes=True)
    ch = ClickHouse(s)
    writes = []
    ch.committed = lambda sid: []
    ch._execute = lambda q, data=b'': writes.append(q)
    ch.totals = lambda sid: {'rows':0, 'qty':'0','net_revenue':'0','net_cogs':'0','fees':'0'}
    rows = parse((Path(__file__).parents[1] / 'examples/sales-demo.csv').read_bytes())
    with pytest.raises(SafeError, match='RECONCILIATION'):
        ch.import_rows('a'*64, rows)
    assert len(writes) == 1
    assert 'mcp_snapshots' not in writes[0]
