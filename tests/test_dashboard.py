import pytest
from cloudru_mcp.config import SafeError
from cloudru_mcp import dashboard

TOTALS = {'rows': 3, 'qty': '2.8', 'net_revenue': '1300', 'net_cogs': '780', 'fees': '200',
          'contribution': '320', 'margin_pct': '24.62'}


class FakeCH:
    def __init__(self):
        self.calls = []

    def report(self, sid, group_by, limit=20):
        self.calls.append((group_by, limit))
        groups = {
            'channel': [{'label': 'Магазин', 'rows': 2, 'revenue': '800', 'cogs': '480', 'fees': '150', 'contribution': '170', 'margin_pct': '21.25'},
                        {'label': '<script>alert(1)</script>', 'rows': 1, 'revenue': '500', 'cogs': '300', 'fees': '50', 'contribution': '150', 'margin_pct': '30.00'}],
            'category': [{'label': 'Посуда', 'rows': 1, 'revenue': '-200', 'cogs': '-120', 'fees': '0', 'contribution': '-80', 'margin_pct': '40.00'}],
            'day': [{'label': '2026-10-02', 'rows': 2, 'revenue': '300', 'cogs': '180', 'fees': '50', 'contribution': '70', 'margin_pct': '23.33'},
                    {'label': '2026-10-01', 'rows': 1, 'revenue': '1000', 'cogs': '600', 'fees': '150', 'contribution': '250', 'margin_pct': '25.00'}],
            'sku': [{'label': 'SKU-001', 'rows': 2, 'revenue': '800', 'cogs': '480', 'fees': '150', 'contribution': '170', 'margin_pct': None}],
        }[group_by]
        return {'snapshot_id': sid, 'group_by': group_by, 'totals': TOTALS, 'groups': groups, 'truncated': False}


SID = 'a' * 64


def test_render_escapes_labels_and_shows_totals():
    page = dashboard.render(dashboard.collect(FakeCH(), SID))
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page
    assert '1 300 ₽' in page and '24,62 %' in page and '−80 ₽' in page
    assert 'http://' not in page and 'https://' not in page  # no external resources
    assert page.index('10-01') < page.index('10-02')  # days in chronological order


def test_publish_writes_atomically(tmp_path):
    out = dashboard.publish(FakeCH(), SID, root=tmp_path, url='https://host/report/')
    assert out['dashboard_url'] == 'https://host/report/'
    assert (tmp_path / 'index.html').read_text(encoding='utf-8').startswith('<!doctype html>')
    assert not (tmp_path / '.index.html.tmp').exists()


def test_publish_requires_configured_dir(monkeypatch):
    monkeypatch.delenv('CLOUDRU_DASHBOARD_DIR', raising=False)
    with pytest.raises(SafeError, match='CONFIG'):
        dashboard.publish(FakeCH(), SID)


def test_money_format():
    assert dashboard.rub('1234567.4') == '1 234 567 ₽'
    assert dashboard.pct(None) == '—'


def test_import_hook_publishes_and_never_fails_import(tmp_path, monkeypatch):
    from cloudru_mcp.config import Settings
    from cloudru_mcp.server import Services
    svc = Services(Settings(), ch=FakeCH())
    monkeypatch.setenv('CLOUDRU_DASHBOARD_DIR', str(tmp_path))
    out = svc.after_import(SID, {'status': 'imported'})
    assert out['status'] == 'imported' and out['dashboard']['bytes'] > 0
    monkeypatch.setenv('CLOUDRU_DASHBOARD_DIR', str(tmp_path / 'missing'))
    out = svc.after_import(SID, {'status': 'imported'})
    assert out['status'] == 'imported' and out['dashboard']['published'] is False
