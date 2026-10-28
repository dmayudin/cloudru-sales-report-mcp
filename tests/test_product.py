from datetime import datetime,timezone,timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import pytest
from cloudru_mcp.costs import estimate,REQUIRED
from cloudru_mcp.config import SafeError,Settings
from cloudru_mcp.sources import fetch
NOW=datetime(2026,10,28,tzinfo=timezone.utc)


def rates():
    return {'verified_at':NOW.isoformat(),'items':[{'category':c,'rate_rub':'1','quantity':'1',
        'unit':'hour','vat_included':True,'source_url':'https://cloud.ru/documents/tariffs/index.html'} for c in REQUIRED]}


def test_complete_monthly_estimate():
    r=estimate(rates(),now=NOW)
    assert r['complete'] and r['total_rub']==str(len(REQUIRED)*720)+'.00'
    assert r['hours']==720 and not r['billing_cutoff']


def test_unknown_component_prevents_total():
    d=rates();d['items'][0]['rate_rub']=None
    r=estimate(d,now=NOW)
    assert r['total_rub'] is None and not r['complete'] and len(r['missing_categories'])==1


def test_old_tariffs_not_quoted_as_current():
    assert estimate(rates(),now=NOW+timedelta(days=8))['total_rub'] is None


@pytest.mark.parametrize('value',['NaN','Infinity','-1'])
def test_bad_rates_rejected(value):
    d=rates();d['items'][0]['rate_rub']=value
    with pytest.raises(SafeError): estimate(d,now=NOW)


def source(tmp_path,monkeypatch,data):
    p=tmp_path/'source.json';p.write_text('{"kind":"s3_object","key":"source/sales.csv"}')
    monkeypatch.setenv('CLOUDRU_SOURCE_FILE',str(p));events=[]
    def get(method,**kw):
        assert method=='get_object' and kw['Key']=='source/sales.csv'
        return {'Body':BytesIO(data),'ContentLength':len(data)}
    store=SimpleNamespace(_call=get,put=lambda b:events.append('put'))
    svc=SimpleNamespace(s=Settings(allow_writes=True),store=store,ch=SimpleNamespace(import_rows=lambda *a:events.append('import')))
    return svc,events,p


def test_source_invalid_csv_does_not_publish(tmp_path,monkeypatch):
    svc,events,_=source(tmp_path,monkeypatch,b'bad')
    with pytest.raises(SafeError): fetch(svc)
    assert not events


def test_source_valid_snapshot_and_scope(tmp_path,monkeypatch):
    svc,events,p=source(tmp_path,monkeypatch,Path('examples/sales-demo.csv').read_bytes())
    result=fetch(svc)
    assert events==['put','import'] and result['totals']['contribution']=='320.00'
    p.write_text('{"kind":"s3_object","key":"other-customer/sales.csv"}')
    with pytest.raises(SafeError,match='source key'): fetch(svc)


def test_install_portable_and_no_overwrite(tmp_path):
    spec=importlib.util.spec_from_file_location('installer',Path('scripts/install_skill.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    s=tmp_path/'agent-skills'/'report';r=tmp_path/'packages'/'report'
    result=m.install(Path('.'),s,r)
    assert result['server_started'] is False
    assert json.loads((s/'installation.json').read_text())['runtime_root']==str(r)
    assert (s/'references/onboarding.md').exists()
    assert (r/'cloudru_mcp/server.py').exists() and not (r/'.venv').exists()
    with pytest.raises(ValueError,match='Destination exists'): m.install(Path('.'),s,r)
    assert (s/'SKILL.md').exists()
