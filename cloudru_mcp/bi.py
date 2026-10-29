"""Apache Superset REST adapter. Managed BI compatibility must be probed live."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from decimal import Decimal
import httpx
from .config import SafeError


class BI:
    def __init__(self,settings,client=None):
        self.s=settings
        # Managed BI external/internal hosts present certificates issued by the private Cloud.ru CA chain
        # (Cloud.ru Certificate Manager CA ← Cloud.ru External Root CA): verify against the operator-provided CA file.
        ca=os.environ.get('CLOUDRU_BI_CA_FILE') or os.environ.get('CLOUDRU_CH_CA_FILE') or True
        self.client=client or httpx.Client(timeout=30,follow_redirects=False,trust_env=False,verify=ca)
        self.base=os.environ.get('CLOUDRU_BI_URL','').rstrip('/')
        self.token=os.environ.get('CLOUDRU_BI_API_TOKEN','')
        self.uri=os.environ.get('CLOUDRU_BI_SQLALCHEMY_URI','')
        self.database_id=int(os.environ.get('CLOUDRU_BI_DATABASE_ID','0'))
        self.root=Path(os.environ.get('CLOUDRU_STATE_DIR','/var/lib/cloudru-sales'))

    def request(self,method,path,body=None):
        u=urlsplit(self.base)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:
            raise SafeError('CONFIG: configure trusted HTTPS Managed BI origin server-side')
        if not self.token: raise SafeError('AUTH: Managed BI requires a supported API credential; Cloud.ru IAM is not assumed to be a Superset JWT')
        headers={'Authorization':'Bearer '+self.token}
        try:
            if method!='GET':
                csrf=self.client.get(self.base+'/api/v1/security/csrf_token/',headers=headers)
                if csrf.status_code!=200: raise SafeError('BI_AUTH: CSRF/token exchange unsupported; no browser fallback')
                headers['X-CSRFToken']=csrf.json()['result']
            r=self.client.request(method,self.base+path,headers=headers,json=body)
            if r.status_code not in (200,201):
                raise SafeError(f'BI_API: HTTP {r.status_code}; validate API permission and Managed BI compatibility')
            if len(r.content)>2_000_000: raise SafeError('LIMIT: BI response too large')
            return r.json()
        except (httpx.HTTPError,ValueError,KeyError):
            raise SafeError('BI_UNKNOWN: request outcome unknown; inspect recorded IDs before retry') from None

    def probe(self):
        self.request('GET','/api/v1/security/csrf_token/')
        saved=self.root/'bi-connection.json'
        if self.database_id<=0 and saved.exists():
            self.database_id=json.loads(saved.read_text()).get('database_id',0)
        if self.database_id<=0:
            return {'api_authenticated':True,'database_configured':False,'next':'configure ClickHouse connection via supported Managed BI API'}
        self.request('GET',f'/api/v1/database/{self.database_id}')
        return {'api_authenticated':True,'database_configured':True,'dashboard_verified':False}

    def connect(self):
        self.s.require_write()
        if self.probe()['database_configured']:
            return {'database_id':self.database_id,'existing':True}
        uri=self.uri
        if not uri.startswith('clickhousedb://') or 'secure=true' not in uri.lower():
            raise SafeError('CONFIG: provide TLS clickhousedb URI for the dedicated BI reader on server')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.root/'bi-connection.json'
        try: fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError: raise SafeError('BI_UNKNOWN: reconcile existing connection intent before retry') from None
        with os.fdopen(fd,'w') as f: json.dump({'status':'creating'},f)
        result=self.request('POST','/api/v1/database/',{'database_name':'sales_report_mcp',
            'sqlalchemy_uri':uri,'expose_in_sqllab':False,'allow_dml':False,'allow_ctas':False,
            'allow_cvas':False,'allow_file_upload':False})
        self.database_id=result['id']
        with open(path,'w') as f: json.dump({'database_id':self.database_id,'status':'created'},f)
        return {'database_id':self.database_id}

    def verify(self, sid, totals):
        path=self.root/'bi-publication.json'
        if not path.exists(): raise SafeError('NOT_READY: publish BI first')
        state=json.loads(path.read_text())
        if state.get('status')!='published': raise SafeError('NOT_READY: BI publication incomplete')
        metrics=[{'expressionType':'SQL','sqlExpression':sql,'label':label,'optionName':label}
            for label,sql in [('revenue','SUM(net_revenue)'),('contribution','SUM(net_revenue-net_cogs-fees)'),
                              ('rows','COUNT(*)'),('snapshot','MIN(snapshot_id)')]]
        result=self.request('POST','/api/v1/chart/data',{'datasource':{'id':state['dataset_id'],'type':'table'},
            'queries':[{'columns':[],'metrics':metrics,'row_limit':1}], 'force':True,
            'result_format':'json','result_type':'full'})
        try:
            row=result['result'][0]['data'][0]
            matched=(row['snapshot']==sid and int(row['rows'])==int(totals['rows']) and
                Decimal(str(row['revenue']))==Decimal(totals['net_revenue']) and
                Decimal(str(row['contribution']))==Decimal(totals['contribution']))
        except (KeyError,IndexError,ValueError,TypeError):
            raise SafeError('BI_CONTRACT: unexpected chart query result') from None
        if not matched: raise SafeError('RECONCILIATION: BI does not match committed snapshot')
        return {'snapshot_id':sid,'stage':'BI_DATA_VERIFIED','url':state['url'],'totals':totals}

    def publish(self):
        self.s.require_write()
        self.probe()
        if self.database_id<=0: raise SafeError('CONFIG: server-side BI database connection ID required')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.root/'bi-publication.json'
        # Exclusive intent file prevents duplicate dashboards and blind POST retries.
        try: fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            state=json.loads(path.read_text())
            if state.get('status')=='published': return state
            raise SafeError('BI_UNKNOWN: previous publication incomplete; reconcile IDs in protected manifest') from None
        state={'status':'publishing'}
        with os.fdopen(fd,'w') as f: json.dump(state,f)
        def record(key,value):
            state[key]=value
            temp=path.with_suffix('.tmp')
            with open(temp,'w') as f: json.dump(state,f)
            os.chmod(temp,0o600);os.replace(temp,path)
        dataset=self.request('POST','/api/v1/dataset/',{'database':self.database_id,
            'schema':self.s.database,'table_name':'mcp_sales_current_v1'})['id']
        record('dataset_id',dataset)
        dashboard=self.request('POST','/api/v1/dashboard/',{'dashboard_title':'Sales revenue and contribution',
            'published':False})['id']
        record('dashboard_id',dashboard)
        metrics=[{'expressionType':'SQL','sqlExpression':sql,'label':label,'optionName':label}
            for label,sql in [('revenue','SUM(net_revenue)'),('contribution','SUM(net_revenue-net_cogs-fees)')]]
        chart=self.request('POST','/api/v1/chart/',{'slice_name':'Revenue and contribution by channel',
            'viz_type':'table','datasource_id':dataset,'datasource_type':'table','dashboards':[dashboard],
            'params':json.dumps({'viz_type':'table','datasource':f'{dataset}__table','query_mode':'aggregate',
                'groupby':['channel'],'metrics':metrics,'row_limit':100,'time_range':'No filter'})})['id']
        record('chart_id',chart)
        position={'DASHBOARD_VERSION_KEY':'v2','ROOT_ID':{'id':'ROOT_ID','type':'ROOT','children':['GRID_ID']},
            'GRID_ID':{'id':'GRID_ID','type':'GRID','children':['ROW-1'],'parents':['ROOT_ID']},
            'ROW-1':{'id':'ROW-1','type':'ROW','children':['CHART-1'],'parents':['ROOT_ID','GRID_ID'],'meta':{'background':'BACKGROUND_TRANSPARENT'}},
            'CHART-1':{'id':'CHART-1','type':'CHART','children':[],'parents':['ROOT_ID','GRID_ID','ROW-1'],
                'meta':{'chartId':chart,'width':12,'height':50,'sliceName':'Revenue and contribution by channel'}}}
        self.request('PUT',f'/api/v1/dashboard/{dashboard}',{'published':True,'position_json':json.dumps(position)})
        record('url',self.base+f'/superset/dashboard/{dashboard}/')
        record('status','published')
        record('data_verified',False)
        return state
