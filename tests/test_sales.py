from decimal import Decimal
from pathlib import Path
import pytest
from cloudru_mcp.config import Settings, SafeError
from cloudru_mcp.sales import parse, summary, read_local, snapshot_id, FIELDS
from cloudru_mcp.server import Services

EXAMPLE = Path(__file__).parents[1] / 'examples/sales-demo.csv'


def test_business_case_and_returns():
    rows = parse(EXAMPLE.read_bytes())
    result = summary(rows[:1])
    assert Decimal(result['contribution']) == 250
    assert result['margin_pct'] == '25.00'
    result = summary(rows)
    assert result['rows'] == 3
    assert Decimal(result['net_revenue']) == 1300
    assert Decimal(result['contribution']) == 320
    assert result['margin_pct'] == '24.62'


@pytest.mark.parametrize('old,new', [(b'1000', b'NaN'), (b'1000', b'1.123'),
    (b'2026-10-01', b'2026-02-30'), (b'RUB', b'USD'), (b'sale-002', b'sale-001')])
def test_bad_data_is_rejected(old, new):
    with pytest.raises(SafeError):
        parse(EXAMPLE.read_bytes().replace(old, new))


def test_empty_and_extra_columns_rejected():
    for data in (','.join(FIELDS).encode(), EXAMPLE.read_bytes().replace(b',RUB', b',RUB,extra')):
        with pytest.raises(SafeError):
            parse(data)


def test_zero_revenue():
    rows = parse(EXAMPLE.read_bytes())[:1]
    rows[0]['net_revenue'] = '0'
    assert summary(rows)['margin_pct'] is None


def test_no_path_escape(tmp_path):
    (tmp_path / 'link.csv').symlink_to(EXAMPLE)
    for name in ('../sales-demo.csv', str(EXAMPLE), 'link.csv'):
        with pytest.raises(SafeError):
            read_local(tmp_path, name)


def test_write_gate_and_changed_file():
    settings = Settings(import_dir=EXAMPLE.parent)
    service = Services(settings)
    sid = snapshot_id(EXAMPLE.read_bytes())
    with pytest.raises(SafeError, match='READ_ONLY'):
        service.upload(EXAMPLE.name, sid)
    settings.allow_writes = True
    with pytest.raises(SafeError, match='CHANGED'):
        service.upload(EXAMPLE.name, '0' * 64)


@pytest.mark.parametrize('url', ['http://10.0.0.1:8123', 'https://host/?query=DROP',
                                 'https://user:password@host', 'file:///etc/passwd'])
def test_clickhouse_endpoint_scope(url):
    with pytest.raises(SafeError):
        Settings(clickhouse_url=url).ch_endpoint()


def test_loopback_requires_opt_in():
    s = Settings(clickhouse_url='http://127.0.0.1:8123')
    with pytest.raises(SafeError):
        s.ch_endpoint()
    s.allow_loopback_http = True
    assert s.ch_endpoint() == s.clickhouse_url
