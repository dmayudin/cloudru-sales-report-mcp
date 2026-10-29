"""Self-contained HTML sales dashboard rendered on the MCP host and served over HTTPS by Caddy.

Managed BI (Superset) accepts only interactive Cloud.ru OAuth sign-in, so a headless agent cannot
publish there. This page is the automatic alternative: no browser, no external scripts or CDNs,
every label from CSV is HTML-escaped, and the file is replaced atomically.
"""
import html
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from .config import SafeError

GROUPS = (('channel', 'По каналам продаж'), ('category', 'По категориям'))


def _d(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


def rub(value) -> str:
    v = _d(value).quantize(Decimal('1'))
    s = f'{abs(v):,}'.replace(',', ' ')
    return ('−' if v < 0 else '') + s + ' ₽'


def pct(value) -> str:
    return '—' if value is None else str(value).replace('.', ',') + ' %'


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def collect(ch, sid):
    """Read every block from ClickHouse through the reconciled report path (same numbers as sales_report)."""
    data = {'snapshot_id': sid}
    for key in ('channel', 'category', 'day', 'sku'):
        data[key] = ch.report(sid, key, 20 if key != 'day' else 100)
    data['totals'] = data['channel']['totals']
    return data


def _scale(rows, keys):
    vals = [_d(r[k]) for r in rows for k in keys] or [Decimal(0)]
    lo, hi = min(Decimal(0), min(vals)), max(Decimal(0), max(vals))
    span = (hi - lo) or Decimal(1)
    return lo, span


def _hbar(value, lo, span, series):
    v = _d(value)
    zero = (-lo) / span * 100
    width = abs(v) / span * 100
    left = zero - width if v < 0 else zero
    neg = ' neg' if v < 0 else ''
    return (f'<span class="bar s{series}{neg}" style="left:{left:.2f}%;width:{max(width, Decimal("0.4")):.2f}%"></span>')


def grouped_bars(report, title):
    rows = report['groups']
    lo, span = _scale(rows, ('revenue', 'contribution'))
    out = [f'<section class="card"><h2>{esc(title)}</h2>',
           '<div class="legend"><span><i class="sw s1"></i>Выручка</span><span><i class="sw s2"></i>Маржинальный доход</span></div>',
           '<div class="hbars">']
    for r in rows:
        tip = (f'{esc(r["label"])}: выручка {rub(r["revenue"])}, маржинальный доход {rub(r["contribution"])}, '
               f'маржа {pct(r["margin_pct"])}, строк {esc(r["rows"])}')
        out.append(f'<div class="hrow" data-tip="{tip}" tabindex="0"><div class="hlabel">{esc(r["label"])}</div>'
                   f'<div class="htrack">{_hbar(r["revenue"], lo, span, 1)}</div>'
                   f'<div class="hval">{rub(r["revenue"])}</div>'
                   f'<div class="hlabel sub">маржа {pct(r["margin_pct"])}</div>'
                   f'<div class="htrack">{_hbar(r["contribution"], lo, span, 2)}</div>'
                   f'<div class="hval">{rub(r["contribution"])}</div></div>')
    out.append('</div>')
    out.append(_table(rows, 'Таблица'))
    if report.get('truncated'):
        out.append('<p class="note">Показаны первые 20 групп по выручке; итоги посчитаны по всем строкам.</p>')
    out.append('</section>')
    return ''.join(out)


def day_columns(report):
    rows = sorted(report['groups'], key=lambda r: r['label'])
    lo, span = _scale(rows, ('revenue',))
    zero = (-lo) / span * 100
    cols = []
    for r in rows:
        v = _d(r['revenue'])
        h = abs(v) / span * 100
        bottom = zero - h if v < 0 else zero
        tip = f'{esc(r["label"])}: выручка {rub(v)}, маржинальный доход {rub(r["contribution"])}'
        cols.append(f'<div class="col" data-tip="{tip}" tabindex="0"><div class="ctrack">'
                    f'<span class="cbar s1{" neg" if v < 0 else ""}" style="bottom:{bottom:.2f}%;height:{max(h, Decimal("0.4")):.2f}%"></span>'
                    f'</div><div class="clabel">{esc(r["label"][5:] if len(str(r["label"])) == 10 else r["label"])}</div></div>')
    return ('<section class="card"><h2>Выручка по дням</h2>'
            f'<div class="cols" style="--zero:{zero:.2f}%">{"".join(cols)}</div>'
            + _table(rows, 'Таблица') + '</section>')


def _table(rows, summary):
    body = ''.join(f'<tr><th scope="row">{esc(r["label"])}</th><td>{rub(r["revenue"])}</td><td>{rub(r["cogs"])}</td>'
                   f'<td>{rub(r["fees"])}</td><td>{rub(r["contribution"])}</td><td>{pct(r["margin_pct"])}</td>'
                   f'<td>{esc(r["rows"])}</td></tr>' for r in rows)
    return (f'<details><summary>{esc(summary)}</summary><div class="tw"><table><thead><tr><th></th><th>Выручка</th>'
            '<th>Себестоимость</th><th>Комиссии</th><th>Марж. доход</th><th>Маржа</th><th>Строк</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>')


CSS = '''
:root{color-scheme:light;--bg:#f4f4f2;--surface:#fcfcfb;--line:#e4e3df;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--s1:#2a78d6;--s2:#eb6834;--track:#efeeea}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111110;--surface:#1a1a19;
--line:#2c2c2a;--text:#f0efec;--text2:#c3c2b7;--muted:#9a998f;--s1:#3987e5;--s2:#d95926;--track:#242422}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111110;--surface:#1a1a19;--line:#2c2c2a;--text:#f0efec;--text2:#c3c2b7;
--muted:#9a998f;--s1:#3987e5;--s2:#d95926;--track:#242422}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 48px}header h1{font-size:24px;margin:0 0 4px}header p{margin:0;color:var(--text2)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi b{display:block;font-size:24px;font-variant-numeric:tabular-nums;margin-top:2px}.kpi span{color:var(--text2);font-size:13px}
.kpi.hero b{font-size:30px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px;min-width:0}
.card h2{font-size:16px;margin:0 0 8px}.legend{display:flex;gap:16px;color:var(--text2);font-size:13px;margin-bottom:10px}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}.sw.s1{background:var(--s1)}.sw.s2{background:var(--s2)}
.hrow{display:grid;grid-template-columns:minmax(80px,30%) 1fr auto;column-gap:10px;row-gap:2px;align-items:center;padding:6px 4px;border-radius:6px}
.hrow+.hrow{border-top:1px solid var(--line)}.hrow:hover,.hrow:focus{background:var(--track);outline:none}
.hlabel{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hlabel.sub{font-weight:400;color:var(--muted);font-size:13px;white-space:normal}
.htrack{position:relative;height:12px}.bar{position:absolute;top:0;height:12px;border-radius:0 4px 4px 0}.bar.neg{border-radius:4px 0 0 4px}
.bar.s1,.cbar.s1{background:var(--s1)}.bar.s2{background:var(--s2)}
.hval{font-variant-numeric:tabular-nums;color:var(--text2);font-size:13px;text-align:right;min-width:84px}
.cols{display:flex;align-items:stretch;gap:6px;height:200px;padding-top:8px}.col{flex:1;display:flex;flex-direction:column;min-width:0;border-radius:6px}
.col:hover,.col:focus{background:var(--track);outline:none}.ctrack{position:relative;flex:1;border-bottom:1px solid var(--line)}
.cbar{position:absolute;left:50%;width:min(60%,56px);transform:translateX(-50%);border-radius:4px 4px 0 0}.cbar.neg{border-radius:0 0 4px 4px}
.clabel{text-align:center;color:var(--muted);font-size:12px;padding-top:4px;white-space:nowrap;overflow:hidden}
details{margin-top:10px}summary{cursor:pointer;color:var(--text2);font-size:13px}.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums;margin-top:6px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th[scope=row],thead th:first-child{text-align:left}
thead th{color:var(--text2);font-weight:600}.note,footer{color:var(--muted);font-size:13px}
#tip{position:fixed;pointer-events:none;background:var(--text);color:var(--surface);padding:6px 9px;border-radius:6px;font-size:13px;max-width:280px;display:none;z-index:9}
'''

JS = '''(function(){var t=document.getElementById('tip');function show(e){var el=e.target.closest('[data-tip]');if(!el){t.style.display='none';return}
t.textContent=el.getAttribute('data-tip');t.style.display='block';var r=el.getBoundingClientRect(),x=(e.clientX||r.left+r.width/2)+12,y=(e.clientY||r.top)+12;
t.style.left=Math.min(x,innerWidth-t.offsetWidth-8)+'px';t.style.top=Math.min(y,innerHeight-t.offsetHeight-8)+'px'}
document.addEventListener('mousemove',show);document.addEventListener('focusin',show);document.addEventListener('mouseleave',function(){t.style.display='none'})})();'''


def render(data, generated_at=None):
    t = data['totals']
    when = (generated_at or datetime.now(timezone.utc)).strftime('%d.%m.%Y %H:%M UTC')
    kpis = [('hero', 'Выручка', rub(t['net_revenue'])), ('hero', 'Маржинальный доход', rub(t['contribution'])),
            ('hero', 'Маржа', pct(t['margin_pct'])), ('', 'Себестоимость', rub(t['net_cogs'])),
            ('', 'Комиссии', rub(t['fees'])), ('', 'Строк в выгрузке', esc(t['rows']))]
    kpi_html = ''.join(f'<div class="kpi {c}"><span>{esc(n)}</span><b>{v}</b></div>' for c, n, v in kpis)
    groups = ''.join(grouped_bars(data[k], title) for k, title in GROUPS)
    sku = data['sku']
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>Отчёт по продажам</title><style>{CSS}</style></head><body><main>'
            '<header><h1>Отчёт по продажам</h1>'
            f'<p>Обновлено {esc(when)} · снимок {esc(data["snapshot_id"][:12])} · суммы в рублях, '
            'маржинальный доход = выручка − себестоимость − комиссии</p></header>'
            f'<div class="kpis">{kpi_html}</div><div class="grid">{groups}</div>{day_columns(data["day"])}'
            f'<section class="card"><h2>По товарам</h2>{_table(sku["groups"], "Показать таблицу").replace("<details>", "<details open>")}</section>'
            '<footer>Данные: Managed ClickHouse, представление sales_report.mcp_sales_current_v1. '
            'Страницу собрал сервер MCP автоматически.</footer></main><div id="tip" role="tooltip"></div>'
            f'<script>{JS}</script></body></html>')


def publish(ch, sid, root=None, url=None):
    root = Path(root or os.environ.get('CLOUDRU_DASHBOARD_DIR', ''))
    url = url or os.environ.get('CLOUDRU_DASHBOARD_URL', '')
    if not str(root) or str(root) == '.' or not root.is_dir():
        raise SafeError('CONFIG: set CLOUDRU_DASHBOARD_DIR to an existing directory served by the HTTPS proxy')
    page = render(collect(ch, sid)).encode('utf-8')
    tmp = root / '.index.html.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    os.fchmod(fd, 0o640)  # the service runs with UMask=0077; the proxy reads through the directory group
    with os.fdopen(fd, 'wb') as f:
        f.write(page)
    os.replace(tmp, root / 'index.html')
    return {'dashboard_url': url or None, 'snapshot_id': sid, 'bytes': len(page),
            'access': 'HTTPS, basic auth and the client IP allowlist; password lives only on the server'}
