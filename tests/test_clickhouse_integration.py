"""Opt-in local ClickHouse tests. Never connect to Cloud.ru from this module."""
import os
from pathlib import Path
import uuid
from decimal import Decimal
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from cloudru_mcp.config import Settings
from cloudru_mcp.adapters import ClickHouse
from cloudru_mcp.server import Services, make_server
from cloudru_mcp.sales import parse, snapshot_id

pytestmark = pytest.mark.skipif(os.environ.get('LOCAL_CH_TEST') != '1', reason='isolated local ClickHouse not requested')
ROOT = Path(__file__).parents[1]


class MemoryStore:
    """Only S3 is replaced. Protocol, CSV and SQL execute normally."""
    def __init__(self):
        self.data = {}
    def put(self, data):
        sid = snapshot_id(data)
        self.data[sid] = data
        return f'incoming/{sid}.csv'
    def read(self, sid):
        return self.data[sid]


@pytest.fixture
def ch():
    settings = Settings(database='mcp_test_' + uuid.uuid4().hex[:12],
        clickhouse_url='http://127.0.0.1:18123', allow_loopback_http=True,
        clickhouse_user='mcp_test', clickhouse_password='local-disposable-test',
        import_dir=ROOT/'examples', allow_writes=True)
    adapter = ClickHouse(settings)
    adapter._execute(f'CREATE DATABASE {adapter.db}')
    yield adapter
    adapter._execute(f'DROP DATABASE {adapter.db}')
    adapter.client.close()


@pytest.mark.asyncio
async def test_mcp_to_real_clickhouse_complete_workflow(ch):
    server = make_server(Services(ch.s, store=MemoryStore(), ch=ch))
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool('sales_prepare_schema', {})
        assert not result.isError
        result = await session.call_tool('sales_preview_csv', {'filename':'sales-demo.csv'})
        sid = result.structuredContent['snapshot_id']
        result = await session.call_tool('sales_upload_csv', {'filename':'sales-demo.csv','expected_snapshot_id':sid})
        assert not result.isError
        first = await session.call_tool('sales_import_snapshot', {'snapshot_id':sid})
        assert not first.isError, first
        assert first.structuredContent['status'] == 'imported'
        second = await session.call_tool('sales_import_snapshot', {'snapshot_id':sid})
        assert not second.isError
        assert second.structuredContent['status'] == 'already_imported'
        result = await session.call_tool('sales_report', {'snapshot_id':sid, 'group_by':'channel', 'limit':1})
        assert not result.isError, result
        report = result.structuredContent
        assert Decimal(report['totals']['contribution']) == 320
        assert report['totals']['margin_pct'] == '24.62'
        assert report['truncated'] is True
        assert int(report['totals']['rows']) == 3
        assert len(report['groups']) == 1
    rows = ch._json(f'SELECT count() AS n, sum(contribution) AS profit FROM {ch.db}.mcp_sales_current_v1')
    assert int(rows[0]['n']) == 3
    assert Decimal(str(rows[0]['profit'])) == 320


def test_partial_retry_final_and_current_view(ch):
    import json
    ch.prepare()
    data = (ROOT/'examples/sales-demo.csv').read_bytes()
    sid = snapshot_id(data)
    rows = parse(data)
    # Simulate a connection loss after partial insert, before manifest commit.
    payload = (json.dumps({'snapshot_id':sid, **rows[0]})+'\n').encode()
    ch._execute(f'INSERT INTO {ch.db}.mcp_sales_v1 FORMAT JSONEachRow', payload)
    assert not ch.committed(sid)
    assert int(ch._json(f'SELECT count() AS n FROM {ch.db}.mcp_sales_current_v1')[0]['n']) == 0
    ch.import_rows(sid, rows)
    assert int(ch.totals(sid)['rows']) == 3
    # Force duplicates, then verify logical idempotency before merges complete.
    ch._execute(f'INSERT INTO {ch.db}.mcp_sales_v1 FORMAT JSONEachRow', payload)
    assert int(ch.totals(sid)['rows']) == 3
    # A new full snapshot replaces the BI selection; retry old does not roll it back.
    data2 = data.replace(b'1000', b'1200')
    sid2 = snapshot_id(data2)
    ch.import_rows(sid2, parse(data2))
    ch.import_rows(sid, rows)
    current = ch._json(f'SELECT DISTINCT snapshot_id FROM {ch.db}.mcp_sales_current_v1')
    assert current == [{'snapshot_id':sid2}]
