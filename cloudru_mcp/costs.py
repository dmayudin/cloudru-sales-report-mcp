"""Transparent estimate from operator-verified tariffs; never invent prices."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from .config import SafeError

REQUIRED = {'clickhouse','bi','mcp_compute','mcp_disk','network','dns','storage','logs','tls_domain','source_connector','agent_usage'}


def estimate(document, days=30, now=None):
    if not 1 <= days <= 366: raise SafeError('INPUT: days must be 1..366')
    now=now or datetime.now(timezone.utc)
    try:
        checked=datetime.fromisoformat(document['verified_at'])
        if checked.tzinfo is None: raise ValueError()
        items=document['items']
        if len(items)>100: raise ValueError()
    except (KeyError,ValueError,TypeError):
        raise SafeError('COST_CONFIG: dated tariff document required') from None
    stale=checked > now or now-checked > timedelta(days=7)
    seen=set(); result=[]; total=Decimal(0); missing=[]
    for row in items:
        try:
            category=row['category']
            if category not in REQUIRED or category in seen: raise ValueError()
            seen.add(category)
            unit=row['unit']
            if unit not in ('hour','month','period'): raise ValueError()
            source=urlsplit(row['source_url'])
            if source.scheme!='https' or not source.hostname: raise ValueError()
            if row.get('rate_rub') is None or row.get('quantity') is None:
                missing.append(category); continue
            rate=Decimal(str(row['rate_rub']));quantity=Decimal(str(row['quantity']))
            if not rate.is_finite() or not quantity.is_finite() or min(rate,quantity)<0: raise ValueError()
            if row.get('vat_included') is not True: raise ValueError()
            factor=Decimal(days*24) if unit=='hour' else Decimal(days)/30 if unit=='month' else Decimal(1)
            amount=(rate*quantity*factor).quantize(Decimal('.01'))
            total+=amount
            result.append({'category':category,'amount_rub':str(amount),'source_url':row['source_url'],
                'assumption':str(row.get('assumption',''))[:500]})
        except (KeyError,TypeError,ValueError,InvalidOperation):
            raise SafeError('COST_CONFIG: invalid tariff row; use finite nonnegative VAT-inclusive prices and source URL') from None
    missing=sorted(set(missing)|(REQUIRED-seen))
    complete=not missing and not stale
    return {'currency':'RUB','days':days,'hours':days*24,'vat_included':True,
        'verified_at':checked.isoformat(),'stale':stale,'missing_categories':missing,
        'complete':complete,'total_rub':str(total) if complete else None,
        'known_subtotal_rub':str(total),'items':result,
        'billing_cutoff':False,'note':'Estimate for stated usage; paid resources continue billing until explicitly removed. Agent usage may be an allocated estimate.'}


def configured_estimate(days=30):
    path=Path(os.environ.get('CLOUDRU_TARIFF_FILE','/etc/cloudru-sales/tariffs.json'))
    try: document=json.loads(path.read_text())
    except (OSError,ValueError):
        return {'complete':False,'total_rub':None,'missing_categories':sorted(REQUIRED),
                'next':'Agent must verify current tariffs and usage assumptions; never quote a component as the total.'}
    return estimate(document,days)
