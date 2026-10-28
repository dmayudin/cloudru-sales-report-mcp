import hashlib
import json
import time
from pathlib import Path
import pytest
from cloudru_mcp.config import Settings, SafeError
from cloudru_mcp.infra import Deployment, Provisioner, template, summarize
from cloudru_mcp.remote import BearerVerifier
from cloudru_mcp.bi import BI


def config():
    return Deployment.model_validate_json(Path('deploy/deployment.example.json').read_text())


def test_template_network_and_minimal_scope():
    r=template(config())['resource']
    assert r['cloudru_evolution_compute_subnet']['workload']['dns_servers']=={'value':['10.77.0.10']}
    assert r['cloudru_evolution_clickhouse_cluster']['sales']['replicas']==0
    assert r['cloudru_evolution_bi_bi']['sales']['enable_external_host'] is False
    assert 'policy' not in r['cloudru_evolution_obs_bucket']['sales']
    assert all(v['lifecycle']['prevent_destroy'] for instances in r.values() for v in instances.values())


@pytest.mark.parametrize('actions',[['delete'],['update'],['delete','create']])
def test_refuses_destructive_plans(actions):
    with pytest.raises(SafeError,match='only creation'):
        summarize({'resource_changes':[{'address':'a','change':{'actions':actions}}]})


@pytest.mark.asyncio
async def test_bearer_is_expiring_and_resource_bound():
    v=BearerVerifier(hashlib.sha256(b'secret').hexdigest(),'https://mcp.example/mcp',int(time.time())+10)
    assert await v.verify_token('bad') is None
    assert (await v.verify_token('secret')).resource=='https://mcp.example/mcp'
    v.expires=0
    assert await v.verify_token('secret') is None


def test_infra_scope_mismatch(tmp_path,monkeypatch):
    path=tmp_path/'deployment.json';path.write_text(config().model_dump_json())
    monkeypatch.setenv('CLOUDRU_DEPLOYMENT_FILE',str(path))
    with pytest.raises(SafeError,match='project differs'):
        Provisioner(Settings(project_id='different')).config()


def test_apply_needs_external_approval(tmp_path,monkeypatch):
    c=config();path=tmp_path/'deployment.json';path.write_text(c.model_dump_json())
    monkeypatch.setenv('CLOUDRU_DEPLOYMENT_FILE',str(path))
    monkeypatch.setenv('CLOUDRU_STATE_DIR',str(tmp_path))
    p=Provisioner(Settings(project_id=str(c.project_id)))
    (tmp_path/'approved.tfplan').write_bytes(b'plan')
    h=hashlib.sha256(b'plan').hexdigest()
    (tmp_path/'plan-metadata.json').write_text(json.dumps({'sha256':h,'created':time.time(),
        'config_hash':hashlib.sha256(c.model_dump_json().encode()).hexdigest()}))
    with pytest.raises(SafeError,match='APPROVAL'): p._perform('apply',h)
    assert not (tmp_path/'apply-intent.json').exists()


def test_bi_requires_own_credential(monkeypatch):
    monkeypatch.setenv('CLOUDRU_BI_URL','https://bi.example.com')
    monkeypatch.delenv('CLOUDRU_BI_API_TOKEN',raising=False)
    with pytest.raises(SafeError,match='IAM is not assumed'): BI(Settings()).probe()


def test_bi_partial_publication_blocks_retry(tmp_path,monkeypatch):
    monkeypatch.setenv('CLOUDRU_STATE_DIR',str(tmp_path))
    b=BI(Settings(allow_writes=True));b.database_id=7
    monkeypatch.setattr(b,'probe',lambda:{'database_configured':True})
    (tmp_path/'bi-publication.json').write_text('{"status":"publishing"}')
    with pytest.raises(SafeError,match='previous publication incomplete'): b.publish()


@pytest.mark.asyncio
async def test_tool_contract_without_server_start():
    from cloudru_mcp.server import make_server,Services
    server=make_server(Services(Settings()))
    tools=await server.list_tools()
    assert {'cloudru_deployment_apply','sales_bi_verify','sales_stage_csv'} <= {t.name for t in tools}
    apply=next(t for t in tools if t.name=='cloudru_deployment_apply')
    assert apply.annotations.idempotentHint is False
    assert 'pattern' in apply.inputSchema['properties']['plan_sha256']
