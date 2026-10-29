"""Scenario-only provisioning through the official Cloud.ru API provider.
No caller-supplied HCL, command, endpoint or arbitrary resource types.
"""
import fcntl
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from uuid import uuid4, UUID
from pydantic import BaseModel, ConfigDict, Field
from .config import SafeError


# Service account product roles required by the scenario (verified 2026-10-28 on a real project).
SERVICE_ACCOUNT_ROLES = ('eiv.admin', 's3e.editor', 'dbaas.clickhouse.admin', 'dataplatform.admin',
                         'logaas.writer', 'vpc.admin', 'cdns.admin')


class Deployment(BaseModel):
    """Server-side deployment configuration. Cloud.ru returns RFC 4122 UUIDs of several versions
    (ClickHouse specifications are UUIDv7), so any UUID is accepted."""
    model_config = ConfigDict(extra='forbid')
    project_id: UUID
    # None → the template creates a project-level service account, grants SERVICE_ACCOUNT_ROLES and issues
    # an access key for it, so the user never visits the IAM console. The bootstrap key (personal access key)
    # must be able to manage IAM in the project.
    service_account_id: UUID | None = None
    service_account_key_ttl: str = Field(default='0', pattern=r'^(0|\d+[smh])$')  # 0 = no expiry (Cloud.ru IAM)
    zone_id: UUID
    bi_flavor_id: UUID
    ch_specification_id: UUID
    log_group_id: UUID
    tenant_id: UUID
    name: str = Field(pattern=r'^[a-z][a-z0-9-]{2,30}$')
    bucket: str = Field(pattern=r'^[a-z][a-z0-9-]{2,60}$')
    ch_version: str = Field(pattern=r'^\d{2}\.\d{1,2}$')
    storage_gib: int = Field(default=40, ge=40, le=100)
    network_cidr: str = '10.77.0.0/16'
    bi_external: bool = False
    runtime_image_id: UUID
    runtime_flavor_id: UUID
    runtime_disk_type_id: UUID
    admin_cidr: str
    client_cidr: str
    ssh_public_key: str = Field(pattern=r'^ssh-ed25519 [A-Za-z0-9+/=]+(?: .*)?$')


def template(c: Deployment):
    n = ipaddress.ip_network(c.network_cidr)
    if n.version != 4 or n.prefixlen != 16 or not n.is_private:
        raise SafeError('CONFIG: a private IPv4 /16 is required')
    a, b = list(n.subnets(new_prefix=24))[:2]
    dns = str(a.network_address + 10)
    ref = lambda t: '${' + t + '.sales.id}'
    project = str(c.project_id)
    r = {}
    def add(kind, values):
        r['cloudru_evolution_' + kind] = {'sales': values}
    add('vpc_vpc', dict(name=c.name, project_id=project))
    # Cloud.ru rejects a bare network address (422): pass the CIDR, the gateway and the routed flag.
    # The DNS server lives in this subnet; Data Platform requires its subnet to contain a matching DNS server,
    # so ClickHouse, Data Platform and Managed BI are placed here as well.
    add('compute_subnet', dict(name=c.name+'-dns', project_id=project, zone={'id':str(c.zone_id)},
        vpc_id=ref('cloudru_evolution_vpc_vpc'), subnet_address=str(a), default_gateway=str(a.network_address+1),
        routed_network=True, dns_servers={'value':[dns]}))
    add('dns_dns_server', dict(name=c.name, availability_zone_id=str(c.zone_id),
        vpc_id=ref('cloudru_evolution_vpc_vpc'), subnet_id=ref('cloudru_evolution_compute_subnet'), ip_address=dns))
    r['cloudru_evolution_compute_subnet']['workload'] = dict(name=c.name+'-data', project_id=project,
        zone={'id':str(c.zone_id)}, vpc_id=ref('cloudru_evolution_vpc_vpc'),
        subnet_address=str(b), default_gateway=str(b.network_address+1), routed_network=True, dns_servers={'value':[dns]},
        depends_on=['cloudru_evolution_dns_dns_server.sales'])
    subnet=ref('cloudru_evolution_compute_subnet')                 # data services
    vm_subnet='${cloudru_evolution_compute_subnet.workload.id}'    # MCP runtime VM
    if c.service_account_id is None:
        add('iam_service_account', dict(name=c.name, target={'project_id':project}))  # description is read-only
        sa=ref('cloudru_evolution_iam_service_account')
        r['cloudru_evolution_iam_permission']={role.replace('.','_'):dict(resource_id=project, subject_id=sa,
            role_identifier={'role_name':role}) for role in SERVICE_ACCOUNT_ROLES}
        add('iam_access_key', dict(service_account_id=sa, ttl=c.service_account_key_ttl,
            depends_on=['cloudru_evolution_iam_permission.'+role.replace('.','_') for role in SERVICE_ACCOUNT_ROLES]))
    else:
        sa=str(c.service_account_id)
    add('cluster_cluster', dict(name=c.name, project_id=project, service_account_id=sa,
        network_configuration={'vpc_id':ref('cloudru_evolution_vpc_vpc'),'subnet_id':subnet,'zone_ids':[str(c.zone_id)]},
        depends_on=['cloudru_evolution_dns_dns_server.sales']))
    add('bi_bi', dict(name=c.name, project_id=project, cluster_id=ref('cloudru_evolution_cluster_cluster'),
        flavor_id=str(c.bi_flavor_id), subnet_id=subnet, zone_id=str(c.zone_id),
        log_group_id=str(c.log_group_id), load_examples=False, enable_external_host=c.bi_external))
    add('clickhouse_cluster', dict(name=c.name, project_id=project, version=c.ch_version,
        # Provider attribute `replicas` is sent as replicas_per_shard (1..3) = hosts per shard, despite its description.
        specification_id=str(c.ch_specification_id), shards=1, replicas=1, storage_gib=c.storage_gib,
        subnet_ids=[subnet], logging={'enabled':True,'log_group_id':str(c.log_group_id)}))
    add('clickhouse_database', dict(name='sales_report', cluster_id=ref('cloudru_evolution_clickhouse_cluster')))
    add('clickhouse_user', dict(name='sales_importer', password='${var.importer_password}',
        cluster_id=ref('cloudru_evolution_clickhouse_cluster'), granted_roles={'value':['cloud_admin']}))
    r['cloudru_evolution_clickhouse_user']['reader'] = dict(name='sales_reader',password='${var.reader_password}',
        cluster_id=ref('cloudru_evolution_clickhouse_cluster'),granted_roles={'value':['cloud_reader']})
    add('obs_bucket', dict(bucket=c.bucket,versioning=True))
    for cidr in (c.admin_cidr,c.client_cidr):
        allowed=ipaddress.ip_network(cidr)
        if allowed.version!=4 or allowed.prefixlen<24:
            raise SafeError('CONFIG: runtime access must be restricted to explicit IPv4 /24 or narrower CIDRs')
    add('compute_security_group',dict(name=c.name+'-mcp',project_id=project,zone={'id':str(c.zone_id)}))
    r['cloudru_evolution_compute_security_group_rule']={}
    for key,direction,protocol,port,cidr in [
        ('ssh','INGRESS','TCP','22:22',c.admin_cidr),('https','INGRESS','TCP','443:443',c.client_cidr),
        # Let's Encrypt HTTP-01 validation needs 80/tcp from anywhere; Caddy only answers ACME there and redirects the rest.
        ('acme','INGRESS','TCP','80:80','0.0.0.0/0'),
        ('egress','EGRESS','ANY','any','0.0.0.0/0')]:
        r['cloudru_evolution_compute_security_group_rule'][key]=dict(
            security_group_id=ref('cloudru_evolution_compute_security_group'),
            direction='TRAFFIC_DIRECTION_'+direction,ether_type='ETHER_TYPE_IPV4',
            ip_protocol='IP_PROTOCOL_'+protocol,port_range=port,remote_ip_prefix=cidr)
    add('compute_interface',dict(name=c.name+'-mcp',project_id=project,zone={'id':str(c.zone_id)},
        subnet={'id':vm_subnet},security_groups=[{'id':ref('cloudru_evolution_compute_security_group')}],
        interface_security_enabled=True,type='INTERFACE_TYPE_REGULAR'))
    add('compute_external_ip',dict(name=c.name+'-mcp',project_id=project,zone={'id':str(c.zone_id)},
        network_interface={'id':ref('cloudru_evolution_compute_interface')}))
    add('compute_disk',dict(name=c.name+'-mcp',project_id=project,zone={'id':str(c.zone_id)},
        size=20,disk_type={'id':str(c.runtime_disk_type_id)},image={'id':str(c.runtime_image_id)},bootable=True))
    # Cloud.ru accepts either cloud_init or image_metadata, not both; image_metadata gave no SSH login on Ubuntu 24.04.
    userdata='#cloud-config\n'+json.dumps({'hostname':c.name+'-mcp','users':[{'name':'deploy','groups':['sudo'],'shell':'/bin/bash',
        'sudo':'ALL=(ALL) NOPASSWD:ALL','lock_passwd':True,'ssh_authorized_keys':[c.ssh_public_key]}],
        'ssh_pwauth':False,'disable_root':True})
    add('compute_vm',dict(name=c.name+'-mcp',project_id=project,zone={'id':str(c.zone_id)},
        flavor={'id':str(c.runtime_flavor_id)},disks=[{'id':ref('cloudru_evolution_compute_disk')}],
        network_interfaces=[{'id':ref('cloudru_evolution_compute_interface')}],
        cloud_init_userdata=base64.b64encode(userdata.encode()).decode(),
        depends_on=['cloudru_evolution_compute_security_group_rule.ssh',
                    'cloudru_evolution_compute_security_group_rule.https','cloudru_evolution_compute_external_ip.sales']))
    # Never silently replace/delete scenario resources.
    for instances in r.values():
        for v in instances.values():
            v['lifecycle']={'prevent_destroy':True}
    return {'terraform':{'required_version':'>= 1.6, < 2.0','required_providers':{
        'cloudru':{'source':'cloudru/cloud','version':'2.1.5'}}},
        'provider':{'cloudru':{'project_id':project,'region':'ru-central-1','object_storage_tenant_id':str(c.tenant_id)}},
        'variable':{k:{'type':'string','sensitive':True} for k in ('importer_password','reader_password')},
        'resource':r, 'output':{
            'data_platform_id':{'value':ref('cloudru_evolution_cluster_cluster')},
            'bi_id':{'value':ref('cloudru_evolution_bi_bi')},
            'clickhouse_id':{'value':ref('cloudru_evolution_clickhouse_cluster')},
            'clickhouse_hosts':{'value':'${cloudru_evolution_clickhouse_cluster.sales.hosts}'},
            'bi_internal_host':{'value':'${cloudru_evolution_bi_bi.sales.internal_host}'},
            'runtime_vm_id':{'value':ref('cloudru_evolution_compute_vm')},
            'runtime_public_ip':{'value':'${cloudru_evolution_compute_external_ip.sales.ip_address}'},
            'subnet_id':{'value':subnet}, 'vpc_id':{'value':ref('cloudru_evolution_vpc_vpc')},
            'bucket':{'value':c.bucket}, 'service_account_id':{'value':sa},
            **({'service_account_key_id':{'value':'${cloudru_evolution_iam_access_key.sales.key_id}','sensitive':True},
                'service_account_key_secret':{'value':'${cloudru_evolution_iam_access_key.sales.secret}','sensitive':True}}
               if c.service_account_id is None else {})}}


def summarize(plan):
    changes=[]
    for r in plan.get('resource_changes',[]):
        if r.get('mode') == 'data':
            continue
        actions=r['change']['actions']
        if actions not in (['no-op'], ['create']):
            raise SafeError('PLAN: only creation/no-op allowed; update, delete or replacement requires operator review')
        changes.append({'address':r['address'],'actions':actions})
    return changes


class Provisioner:
    def __init__(self, settings):
        self.s=settings
        self.root=Path(os.environ.get('CLOUDRU_STATE_DIR','/var/lib/cloudru-sales')).resolve()
        self.config_path=Path(os.environ.get('CLOUDRU_DEPLOYMENT_FILE','/etc/cloudru-sales/deployment.json'))
        self.bin=os.environ.get('CLOUDRU_TERRAFORM_BIN','/usr/local/bin/terraform')

    def config(self):
        try:
            c=Deployment.model_validate_json(self.config_path.read_text())
        except Exception:
            raise SafeError('CONFIG: operator must supply valid deployment.json; no secrets belong in it') from None
        if str(c.project_id) != self.s.project_id:
            raise SafeError('ACCESS: deployment project differs from server scope')
        return c

    def _env(self):
        if not self.s.key_id or not self.s.key_secret:
            raise SafeError('AUTH: Cloud.ru credentials must be configured on the server')
        # Do not inherit TF_CLI_ARGS, TF_LOG, provider overrides, or shell state.
        e={k:os.environ[k] for k in ('PATH','HOME','SSL_CERT_FILE') if k in os.environ}
        e.update(AUTH_KEY_ID=self.s.key_id,AUTH_SECRET=self.s.key_secret,TF_IN_AUTOMATION='1',
            TF_VAR_importer_password=self.s.clickhouse_password,
            TF_VAR_reader_password=os.environ.get('CLOUDRU_BI_CH_PASSWORD',''))
        e['TF_CLI_CONFIG_FILE']=str(Path(__file__).parent/'terraform.rc')
        return e

    def _run(self, args, timeout=3600, cwd=None):
        try:
            p=subprocess.run([self.bin,*args],cwd=cwd or self.root,env=self._env(),capture_output=True,timeout=timeout)
        except (OSError,subprocess.TimeoutExpired):
            raise SafeError('UNKNOWN: provider interrupted; inspect cloud/state before another apply') from None
        if p.returncode:
            fd=os.open(self.root/'provider-error.log',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'wb') as f: f.write(p.stderr[-100000:])
            # Terraform diagnostics and state can contain plaintext passwords.
            raise SafeError('PROVIDER: command failed; inspect protected provider diagnostics on server; do not retry apply blindly')
        return p.stdout

    def _write(self, path, value):
        tmp=path.with_suffix('.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f: json.dump(value,f)
        os.replace(tmp,path)

    def start(self, action, expected_hash=None):
        if action == 'apply': self.s.require_write()
        if action != 'catalog': self.config()
        self._env()
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chmod(self.root,0o700)
        lock=open(self.root/'operation.lock','a')
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise SafeError('BUSY: a provisioning operation is running') from None
        job=str(uuid4())
        self._write(self.root/(job+'.json'),{'job_id':job,'status':'running','action':action})
        def work():
            try:
                result=self._perform(action,expected_hash)
                state={'job_id':job,'status':'succeeded','result':result}
            except SafeError as e: state={'job_id':job,'status':'needs_attention','error':str(e)}
            except Exception: state={'job_id':job,'status':'needs_attention','error':'INTERNAL: inspect protected server state'}
            self._write(self.root/(job+'.json'),state)
            lock.close()
        threading.Thread(target=work,daemon=True).start()
        return {'job_id':job,'status':'running','next_tool':'cloudru_deployment_status'}

    def _perform(self, action, expected_hash):
        if action == 'catalog':
            if not self.s.project_id: raise SafeError('CONFIG: project ID required')
            root=self.root/'catalog'
            root.mkdir(mode=0o700,exist_ok=True)
            types={'zones':'compute_zone_collection','bi_flavors':'bi_flavor_collection',
                   'ch_versions':'clickhouse_version_collection'}
            attrs={'zones':'zones','bi_flavors':'flavors','ch_versions':'versions'}
            data={'cloudru_evolution_'+v:{'list':({} if k=='ch_versions' else {'project_id':self.s.project_id})} for k,v in types.items()}
            doc={'terraform':{'required_providers':{'cloudru':{'source':'cloudru/cloud','version':'2.1.5'}}},
                 'provider':{'cloudru':{'project_id':self.s.project_id,'region':'ru-central-1'}},'data':data,
                 'output':{k:{'value':'${data.cloudru_evolution_'+v+'.list.'+attrs[k]+'}'} for k,v in types.items()}}
            self._write(root/'main.tf.json',doc)
            self._run(['init','-input=false','-no-color'],300,root)
            self._run(['plan','-input=false','-no-color','-out=catalog.tfplan'],600,root)
            plan=json.loads(self._run(['show','-json','catalog.tfplan'],60,root))
            return {'catalog':{k:v.get('value') for k,v in plan['planned_values']['outputs'].items()},
                    'cost_verified':False,'pagination':'Provider-managed collection; do not infer absence from incomplete results'}
        c=self.config()
        if action == 'plan':
            if not self._env()['TF_VAR_importer_password'] or not self._env()['TF_VAR_reader_password']:
                raise SafeError('CONFIG: importer and BI reader passwords required on server')
            pending=self.root/'apply-intent.json'
            if pending.exists():
                raise SafeError('UNKNOWN: previous apply may have changed resources; operator reconciliation required')
            self._write(self.root/'main.tf.json',template(c))
            self._run(['init','-input=false','-no-color'],300)
            self._run(['validate','-json'],60)
            self._run(['plan','-input=false','-no-color','-out=approved.tfplan'],600)
            plan=json.loads(self._run(['show','-json','approved.tfplan'],60))
            changes=summarize(plan)
            h=hashlib.sha256((self.root/'approved.tfplan').read_bytes()).hexdigest()
            self._write(self.root/'plan-metadata.json',{'sha256':h,'created':time.time(),
                'config_hash':hashlib.sha256(c.model_dump_json().encode()).hexdigest(),'changes':changes})
            return {'plan_sha256':h,'changes':changes,'cost_verified':False,
                'next':'Review tariffs, budget, access and plan; then apply the same hash'}
        meta=json.loads((self.root/'plan-metadata.json').read_text())
        actual=hashlib.sha256((self.root/'approved.tfplan').read_bytes()).hexdigest()
        if expected_hash != actual or actual != meta['sha256'] or time.time()-meta['created']>3600:
            raise SafeError('STALE: plan hash mismatch or plan older than one hour')
        if hashlib.sha256(c.model_dump_json().encode()).hexdigest()!=meta['config_hash']:
            raise SafeError('STALE: deployment configuration changed')
        # Approval is an operator-side file; an agent cannot grant itself spending permission via tool arguments.
        try: approval=json.loads((self.root/'approval.json').read_text())
        except Exception: raise SafeError('APPROVAL: operator must authorize this plan in protected approval.json') from None
        if approval.get('plan_sha256')!=actual or approval.get('expires_at',0)<=time.time() or approval.get('budget_rub',0)<=0:
            raise SafeError('APPROVAL: missing, expired or mismatched spending authorization')
        if (self.root/'apply-intent.json').exists():
            raise SafeError('UNKNOWN: earlier apply requires operator reconciliation')
        self._write(self.root/'apply-intent.json',{'sha256':actual,'started':time.time()})
        self._run(['apply','-input=false','-no-color','approved.tfplan'])
        outputs=json.loads(self._run(['output','-json'],60))
        result={k:v['value'] for k,v in outputs.items() if not v.get('sensitive') and k in template(c)['output']}
        self._write(self.root/'manifest.json',result)
        (self.root/'apply-intent.json').unlink()
        (self.root/'approval.json').unlink()
        return {'resources':result,'stage':'INFRA_APPLIED','data_and_bi_verified':False}

    def status(self, job_id):
        from .config import uuid
        p=self.root/(uuid(job_id)+'.json')
        if not p.exists(): raise SafeError('NOT_FOUND: unknown job')
        state=json.loads(p.read_text())
        if state['status']=='running':
            with open(self.root/'operation.lock','a') as lock:
                try:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    state['status']='unknown_after_restart'
                    state['next']='Reconcile cloud and Terraform state; do not repeat apply'
                except BlockingIOError: pass
        return state
