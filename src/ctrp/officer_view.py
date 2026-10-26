"""
Officer view, version 0: one HTML file that shows the model's results the way an officer would receive them.

What: reads the live scores workbook (and the post-clearance audit downloads, if present) and writes ONE self-contained
      HTML file: a taxpayer list with filters, a taxpayer risk profile (score, bands, reasons, behaviour, entries since
      July with their peer comparisons), and the post-clearance audit list. It opens in any browser, needs no install,
      no server and no internet, and the data never leaves the computer.
Why:  to test how an officer reads a result before anything is built into ACE or a dashboard.

    python main.py view            -> results/CTRP_officer_view_<snapshot>.html

Contains TINs and names: internal use only. Keep it on URA machines; do not upload it anywhere.
"""
import json
from datetime import datetime

import numpy as np
import pandas as pd

from ctrp import extract as E
from ctrp.utils import RESULTS_DIR

TP_COLS = {  # field in the page -> column in the Scores sheet
    'rank': 'Rank', 'tin': 'TIN', 'score': 'History Risk Score', 'hband': 'History Risk Band',
    'oband': 'Overall Risk Band', 'by': 'Overall band set by', 'r1': 'Reason 1', 'r2': 'Reason 2', 'r3': 'Reason 3',
    'notes': 'Notes', 'pct': 'Behaviour risk percentile (against similar importers)', 'flag': 'Risky Behaviour Flag',
    'b1': 'Behaviour reason 1', 'b2': 'Behaviour reason 2', 'decl': 'Declarations (24 months)',
    'value': 'Customs value UGX (24 months)', 'peer': 'Peer group',
    'small': 'Limited history (under 10 declarations)'}
EN_COLS = ['rank', 'strength', 'signals', 'tax_at_stake', 'entry_key', 'entry_num', 'station', 'entry_year',
           'instance_id', 'assessed_on', 'taxpayer_tin', 'lane', 'topped_up', 'tax_raised', 'items', 'customs_value',
           'apcs', 'lowest_price_vs_peers', 'lowest_price_hs_code', 'lowest_price_per_kg', 'peer_price_per_kg',
           'lowest_duty_vs_peers', 'duty_gap', 'value_gap']
MAX_ENTRIES = 20_000
IT_COLS = ['entry_key', 'item', 'hs_code', 'origin', 'apc', 'customs_value', 'net_weight', 'quantity', 'price_kg',
           'peer_kg', 'price_vs_peers', 'price_unit', 'peer_unit', 'peer_basis', 'peer_importers', 'duty_rate',
           'peer_duty_rate', 'price_signal', 'duty_signal', 'tax_at_stake']


def _records(df, cols):
    """Columns + rows (smaller than a list of dicts); NaN becomes null."""
    df = df[[c for c in cols if c in df]].copy()
    def clean(v):
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
            return None
        if hasattr(v, 'item'):                       # numpy numbers
            v = v.item()
        if isinstance(v, float):
            return None if np.isnan(v) else round(v, 4)
        return v
    return {'cols': list(df.columns), 'rows': [[clean(v) for v in r] for r in df.astype(object).values.tolist()]}


def collect():
    path = RESULTS_DIR / f'CTRP_scores_{E.LIVE_SNAPSHOT}.xlsx'
    if not path.exists():
        raise SystemExit(f'{path.name} not found in results/. Run python main.py v3 --rebuild (or score) first.')
    s = pd.read_excel(path, sheet_name='Scores', dtype={'TIN': str})
    s = s.rename(columns={v: k for k, v in TP_COLS.items()})
    readme = pd.read_excel(path, sheet_name='Read me')
    model = readme.loc[readme.iloc[:, 0] == 'Model'].iloc[0, 1] if (readme.iloc[:, 0] == 'Model').any() else ''
    data = {'snapshot': E.LIVE_SNAPSHOT, 'model': str(model), 'made': datetime.now().strftime('%d-%m-%Y %H:%M'),
            'taxpayers': _records(s, list(TP_COLS)), 'entries': None, 'items': None, 'names': {}, 'addresses': {}, 'entries_total': 0}
    try:
        from ctrp import pca
        e = pca.load_entries()
    except SystemExit:
        e = None
    if e is not None:
        # the page shows the strongest entries only: a browser slows down past a few tens of thousands of rows
        f = e[e['strength'].isin(['Strong', 'Some'])].head(MAX_ENTRIES).copy()
        data['entries_total'] = int(e['strength'].isin(['Strong', 'Some']).sum())
        f['assessed_on'] = f['assessed_on'].astype(str)
        data['entries'] = _records(f, EN_COLS)
        first = e[e['taxpayer_nm'] != ''].drop_duplicates('taxpayer_tin').set_index('taxpayer_tin')
        data['names'] = first['taxpayer_nm'].to_dict()
        data['addresses'] = first['taxpayer_address'].to_dict() if 'taxpayer_address' in first else {}
        items = pca.load_items()
        if items is not None:
            data['items'] = _records(items[items['entry_key'].isin(f['entry_key'])], IT_COLS)
    return data


def write(out=None):
    data = collect()
    out = out or RESULTS_DIR / f'CTRP_officer_view_{E.LIVE_SNAPSHOT}.html'
    payload = json.dumps(data, separators=(',', ':'), default=str, allow_nan=False).replace('</', '<\\/')
    out.write_text(PAGE.replace('__DATA__', payload), encoding='utf-8')
    n_e = len(data['entries']['rows']) if data['entries'] else 0
    print(f"written {out} ({len(data['taxpayers']['rows']):,} taxpayers, {n_e:,} entries with a signal)")
    return out


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CTRP Officer View (v0)</title>
<style>
:root{--navy:#1C3F7C;--ndark:#132D5A;--nmid:#2A5099;--nlight:#E8EEF8;--yellow:#F5C800;--red:#C0392B;--red-lt:#FEF2F2;
--green:#15803D;--green-lt:#ECFDF3;--amber:#B45309;--amber-lt:#FFFBEB;--muted:#6B7280;--border:#CBD5E1;--bg:#F8FAFC}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:var(--bg);color:#1a1a2e;font-size:13px}
.nav{background:var(--navy);border-bottom:3px solid var(--yellow);padding:8px 16px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:5}
.nav-title{color:#fff;font-size:14px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.nav-sub{color:var(--yellow);font-size:11px;margin-top:2px}
.nav-right{text-align:right;color:rgba(255,255,255,.75);font-size:11px;line-height:1.6}.nav-right b{color:#fff}
.tabs{display:flex;gap:4px;padding:8px 16px 0}
.tab{padding:7px 14px;border:1px solid var(--border);border-bottom:none;background:#fff;cursor:pointer;font-weight:700;color:var(--muted);border-radius:3px 3px 0 0}
.tab.on{color:var(--navy);border-top:3px solid var(--yellow)}
.wrap{display:grid;grid-template-columns:580px 1fr;gap:12px;padding:0 16px 16px}
.panel{background:#fff;border:1px solid var(--border);border-radius:3px;padding:10px}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.filters input[type=text]{flex:1;min-width:160px;padding:6px;border:1px solid var(--border);border-radius:3px}
.filters select,.filters label{font-size:12px;padding:5px;border:1px solid var(--border);border-radius:3px;background:#fff}
.count{font-size:11px;color:var(--muted);margin-bottom:4px}
table{width:100%;border-collapse:collapse}
th{background:var(--navy);color:#fff;font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;padding:5px 6px;text-align:left;position:sticky;top:0}
td{font-size:12px;padding:4px 6px;border-bottom:1px solid var(--border);vertical-align:top}
tr:nth-child(even) td{background:#F8FAFC}
.list{max-height:calc(100vh - 210px);overflow:auto}
.list tr{cursor:pointer}.list tr:hover td{background:var(--nlight)}
.sel td{background:#FFF7CC!important}
.mono{font-family:monospace;color:var(--nmid)}
.band{display:inline-block;white-space:nowrap;padding:1px 6px;border-radius:2px;font-weight:700;font-size:11px}
.b-VERYHIGH{background:var(--red);color:#fff}.b-HIGH{background:var(--red-lt);color:var(--red)}
.b-MEDIUM{background:var(--amber-lt);color:var(--amber)}.b-LOW{background:var(--green-lt);color:var(--green)}
.b-VERYLOW{background:#F1F5F9;color:var(--muted)}
.hero{display:grid;grid-template-columns:80px 1fr 220px;gap:12px;align-items:center;border:1px solid var(--nmid);border-left:5px solid var(--navy);background:var(--nlight);border-radius:3px;padding:10px 12px;margin-bottom:10px}
.ring{width:70px;height:70px;border-radius:50%;border:6px solid var(--muted);display:flex;flex-direction:column;align-items:center;justify-content:center;background:#fff}
.ring-n{font-size:22px;font-weight:700;line-height:1}.ring-s{font-size:8px;color:var(--muted);text-transform:uppercase}
.id-name{font-size:16px;font-weight:700;color:var(--navy)}.id-meta{font-size:11.5px;color:var(--muted);margin-top:3px;line-height:1.6}
.chips{display:flex;gap:5px;margin-top:7px;flex-wrap:wrap;align-items:center}.lbl{font-size:11px;color:var(--muted);margin-left:6px}
.id-addr{font-size:12px;color:#334155;margin-top:2px}.id-meta b{color:var(--navy)}
.session{text-align:right;font-size:11px;color:var(--muted);line-height:1.8}.session b{color:var(--navy)}
.sec{margin-bottom:10px}
.s-head{background:var(--navy);padding:5px 9px;display:flex;justify-content:space-between;border-radius:3px 3px 0 0}
.s-tag{font-size:9.5px;color:var(--yellow);letter-spacing:.1em;text-transform:uppercase;font-weight:700;margin-right:7px}
.s-title{font-size:12.5px;font-weight:700;color:#fff}
.s-badge{font-size:10.5px;color:var(--yellow);border:1px solid rgba(245,200,0,.5);border-radius:2px;padding:1px 6px}
.s-body{border:1px solid var(--border);border-top:none;border-radius:0 0 3px 3px;padding:8px 10px;background:#fff}
.ov-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.ov-box{background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:7px 9px}
.ov-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
.ov-val{font-size:17px;font-weight:700;color:var(--navy)}.ov-sub{font-size:10.5px;color:var(--muted);margin-top:2px}
.reason{padding:5px 8px;border-left:3px solid var(--navy);background:var(--nlight);margin-bottom:5px;border-radius:0 3px 3px 0}
.note{padding:5px 8px;border-left:3px solid var(--amber);background:var(--amber-lt);color:var(--amber);margin-bottom:5px;border-radius:0 3px 3px 0}
.bar{height:8px;background:var(--border);border-radius:4px;overflow:hidden;margin:4px 0}.bar>div{height:100%;background:var(--red)}
.t-red{color:var(--red);font-weight:700}.t-amber{color:var(--amber);font-weight:700}.t-green{color:var(--green);font-weight:700}
.empty{color:var(--muted);font-style:italic;padding:6px}
.items td{font-size:11px;background:#FFFDF2!important}
.footer{margin:0 16px 16px;border-top:2px solid var(--yellow);padding-top:5px;display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
.footer b{color:var(--navy);letter-spacing:.06em}
.hide{display:none}
.full{grid-template-columns:1fr}
</style></head><body>
<div class="nav"><div><div class="nav-title">CTRP · Customs Taxpayer Risk Profiling</div>
<div class="nav-sub">Officer view · version 0 for testing · internal use only</div></div>
<div class="nav-right"><div>Snapshot <b id="snap"></b></div><div id="model"></div><div>Made <b id="made"></b></div></div></div>
<div class="tabs"><div class="tab on" data-t="tp">Taxpayers</div><div class="tab" data-t="pca">Post-clearance audit list</div></div>

<div id="v-tp" class="wrap">
 <div class="panel">
  <div class="filters">
   <input type="text" id="q" placeholder="Search TIN or name">
   <select id="fb"><option value="">All bands</option><option>VERY HIGH</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option><option>VERY LOW</option></select>
   <label><input type="checkbox" id="ff" checked> Risky Behaviour Flag</label>
   <label><input type="checkbox" id="fe"> Entries since July</label>
  </div>
  <div class="count" id="cnt"></div>
  <div class="list"><table><thead><tr><th>Rank</th><th>TIN</th><th>Taxpayer</th><th>Overall band</th><th>Score</th><th>Risky Behaviour Flag</th></tr></thead><tbody id="tl"></tbody></table></div>
 </div>
 <div id="prof"><div class="panel empty">Pick a taxpayer on the left.</div></div>
</div>

<div id="v-pca" class="wrap full hide">
 <div class="panel">
  <div class="filters">
   <input type="text" id="pq" placeholder="Search TIN, entry number or HS code">
   <select id="ps"><option value="">All strengths</option><option>Strong</option><option>Some</option><option>Weak</option></select>
   <select id="pl"><option value="">All lanes</option><option>Red</option><option>Yellow</option><option>Green</option><option>Blue</option><option>No flag</option></select>
   <label><input type="checkbox" id="pn"> Not topped up</label>
  </div>
  <div class="count" id="pcnt"></div>
  <div class="list" style="max-height:calc(100vh - 200px)"><table><thead><tr><th>Rank</th><th>Strength</th><th>Entry</th><th>Date</th><th>TIN</th><th>Taxpayer</th><th>Lane</th><th>Topped up</th><th>What we saw</th><th>Price % of peers</th><th>Tax at stake (UGX)</th></tr></thead><tbody id="pl-body"></tbody></table></div>
 </div>
</div>
<div class="footer"><b>UGANDA REVENUE AUTHORITY</b><span>CTRP · Officer view v0 · scores are provisional until the Risk Officers confirm the settings</span><span>Data Science Section · ITID</span></div>

<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const T = rows(D.taxpayers), EN = D.entries ? rows(D.entries) : [], IT = D.items ? rows(D.items) : [];
function rows(t){ return t.rows.map(r => Object.fromEntries(t.cols.map((c,i)=>[c,r[i]]))); }
const byTin = {}; EN.forEach(e => (byTin[e.taxpayer_tin] = byTin[e.taxpayer_tin] || []).push(e));
const byEntry = {}; IT.forEach(i => (byEntry[i.entry_key] = byEntry[i.entry_key] || []).push(i));
const esc = s => (s===null||s===undefined)?'':String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ugx = v => v===null||v===undefined ? '' : Math.round(v).toLocaleString('en-US');
const pct = v => v===null||v===undefined ? '' : Math.round(v*100) + '%';
const band = b => b ? `<span class="band b-${String(b).replace(/ /g,'')}">${esc(b)}</span>` : '';
const ringColour = b => ({'VERY HIGH':'#C0392B','HIGH':'#C0392B','MEDIUM':'#B45309','LOW':'#15803D'}[b] || '#6B7280');
document.getElementById('snap').textContent = D.snapshot;
document.getElementById('model').textContent = D.model;
document.getElementById('made').textContent = D.made;

// ---------- taxpayer list ----------
let selected = null;
function drawList(){
  const q = document.getElementById('q').value.trim().toLowerCase(), fb = document.getElementById('fb').value;
  const ff = document.getElementById('ff').checked, fe = document.getElementById('fe').checked;
  const hit = T.filter(t => (!q || t.tin.includes(q) || (D.names[t.tin]||'').toLowerCase().includes(q))
    && (!fb || t.oband === fb) && (!ff || t.flag === 'Y') && (!fe || byTin[t.tin]));
  document.getElementById('cnt').textContent = `${hit.length.toLocaleString()} taxpayers` + (hit.length > 300 ? ' (first 300 shown)' : '');
  document.getElementById('tl').innerHTML = hit.slice(0,300).map(t =>
    `<tr data-tin="${t.tin}" class="${t.tin===selected?'sel':''}"><td>${t.rank}</td><td class="mono">${t.tin}</td><td>${esc(D.names[t.tin]||'')}</td><td>${band(t.oband)}</td><td>${t.score}</td><td>${t.flag==='Y'?'<span class="t-red">Yes</span>':'No'}</td></tr>`).join('');
}
document.getElementById('tl').addEventListener('click', ev => { const tr = ev.target.closest('tr'); if (tr) { selected = tr.dataset.tin; drawList(); drawProfile(selected); } });
['q','fb','ff','fe'].forEach(id => document.getElementById(id).addEventListener('input', drawList));

// ---------- taxpayer profile ----------
function drawProfile(tin){
  const t = T.find(x => x.tin === tin), ent = (byTin[tin] || []);
  const stake = ent.reduce((a,e)=>a+(e.tax_at_stake||0),0), strong = ent.filter(e=>e.strength==='Strong').length;
  const reasons = [t.r1,t.r2,t.r3].filter(Boolean).map(r => `<div class="reason">${esc(clean(r))}</div>`).join('') || '<div class="empty">No history reasons: no scorecard points.</div>';
  const notes = t.notes ? String(t.notes).split(/\n/).filter(Boolean).map(n => `<div class="note">${esc(n)}</div>`).join('') : '';
  const beh = [t.b1,t.b2].filter(Boolean).map(r => `<div class="reason">${esc(clean(r))}</div>`).join('');
  const entRows = ent.map(e => `<tr data-k="${esc(e.entry_key)}" style="cursor:pointer"><td class="mono">${esc(e.entry_num)} ${esc(e.station)} ${esc(e.entry_year)}</td><td>${esc(e.assessed_on)}</td><td>${esc(e.lane)}</td><td>${e.topped_up==='Y'?'<span class="t-green">Y</span>':'N'}</td><td>${strengthTag(e.strength)}</td><td>${esc(e.signals)}</td><td>${pricePct(e)}</td><td>${ugx(e.tax_at_stake)}</td></tr><tr class="hide items" id="it-${esc(e.entry_key)}"><td colspan="8">${itemTable(e.entry_key)}</td></tr>`).join('');
  document.getElementById('prof').innerHTML = `
  <div class="hero"><div class="ring" style="border-color:${ringColour(t.hband)}"><span class="ring-n" style="color:${ringColour(t.hband)}">${t.score}</span><span class="ring-s">Score</span></div>
   <div><div class="id-name">${esc(D.names[tin] || 'Name not in the entries since July')}</div>
    ${D.addresses && D.addresses[tin] ? `<div class="id-addr">${esc(D.addresses[tin])}</div>` : ''}
    <div class="id-meta"><b>TIN</b> ${tin} &nbsp;·&nbsp; <b>Rank</b> ${t.rank} of ${T.length.toLocaleString()} &nbsp;·&nbsp; <b>Peer group</b> ${esc(t.peer || 'none (fewer than 10 declarations)')}</div>
    <div class="chips"><span class="lbl">Overall</span>${band(t.oband)} <span class="lbl">History</span>${band(t.hband)} <span class="lbl">Risky Behaviour Flag</span>${t.flag==='Y'?'<span class="band b-HIGH">Yes</span>':'<span class="band b-VERYLOW">No</span>'} ${t.small==='Y'?'<span class="band b-VERYLOW">Limited history</span>':''}</div></div>
   <div class="session"><div><b>Overall band set by</b></div><div>${esc(t.by||'')}</div><div>Snapshot <b>${D.snapshot}</b></div></div></div>
  <div class="sec"><div class="s-head"><span><span class="s-tag">Overview</span><span class="s-title">Taxpayer profile</span></span></div><div class="s-body"><div class="ov-grid">
   <div class="ov-box"><div class="ov-label">Declarations</div><div class="ov-val">${(t.decl||0).toLocaleString()}</div><div class="ov-sub">last 24 months</div></div>
   <div class="ov-box"><div class="ov-label">Customs value</div><div class="ov-val">${ugx(t.value)}</div><div class="ov-sub">UGX, last 24 months</div></div>
   <div class="ov-box"><div class="ov-label">Entries with a signal</div><div class="ov-val">${ent.length}</div><div class="ov-sub">since 1 July 2026 · ${strong} strong</div></div>
   <div class="ov-box"><div class="ov-label">Tax at stake</div><div class="ov-val" style="color:var(--amber)">${ugx(stake)}</div><div class="ov-sub">UGX, estimate to check</div></div>
  </div></div></div>
  <div class="sec"><div class="s-head"><span><span class="s-tag">History</span><span class="s-title">Why this score: compliance history</span></span><span class="s-badge">History band ${esc(t.hband)}</span></div><div class="s-body">${reasons}${notes}</div></div>
  <div class="sec"><div class="s-head"><span><span class="s-tag">Behaviour</span><span class="s-title">Trading behaviour against similar importers</span></span><span class="s-badge">Risky Behaviour Flag: ${t.flag==='Y'?'Yes':'No'}</span></div><div class="s-body">
   ${t.pct!==null && t.pct!==undefined ? `<div>Behaviour risk percentile: <b>${pct(t.pct)}</b> (higher than ${pct(t.pct)} of similar importers)</div><div class="bar"><div style="width:${Math.round((t.pct||0)*100)}%"></div></div>` : '<div class="empty">Not in the behaviour view (has a top-up history).</div>'}
   ${beh}</div></div>
  <div class="sec"><div class="s-head"><span><span class="s-tag">Entries</span><span class="s-title">Entries since 1 July 2026 with a signal</span></span><span class="s-badge">click an entry for its items and peer prices</span></div><div class="s-body">
   ${ent.length ? `<table id="ent"><thead><tr><th>Entry</th><th>Date</th><th>Lane</th><th>Topped up</th><th>Strength</th><th>What we saw</th><th>Price % of peers</th><th>Tax at stake (UGX)</th></tr></thead><tbody>${entRows}</tbody></table>` : `<div class="empty">${EN.length ? 'No entry since July with a signal.' : 'The post-clearance audit downloads are not in data/pca/ yet.'}</div>`}
  </div></div>`;
  const tb = document.getElementById('ent');
  if (tb) tb.addEventListener('click', ev => { const tr = ev.target.closest('tr[data-k]'); if (tr) document.getElementById('it-' + tr.dataset.k).classList.toggle('hide'); });
}
function clean(r){ return String(r).replace(/^PAR_\w+:\s*/, '').replace(/\bPAR_\w+:\s*/g, '').replace('same main goods and size', 'same main HS section and size'); }
function pricePct(e){ return (e.lowest_price_vs_peers !== null && e.lowest_price_vs_peers < 0.8) ? pct(e.lowest_price_vs_peers) : ''; }
function strengthTag(s){ return s==='Strong'?'<span class="t-red">Strong</span>':s==='Some'?'<span class="t-amber">Some</span>':esc(s); }
function itemTable(k){
  const its = byEntry[k] || [];
  if (!its.length) return '<div class="empty">No item-level price or duty signal (the signal is on the entry: split, amendment, APC, preference or new importer).</div>';
  return `<table><thead><tr><th>Item</th><th>HS code</th><th>Origin</th><th>APC</th><th>Value (UGX)</th><th>kg</th><th>Price/kg</th><th>Peer/kg</th><th>% of peers</th><th>Price/unit</th><th>Peer/unit</th><th>Duty</th><th>Peer duty</th><th>Signal</th><th>Peers</th></tr></thead><tbody>` +
    its.map(i => `<tr><td>${esc(i.item)}</td><td class="mono">${esc(i.hs_code)}</td><td>${esc(i.origin)}</td><td>${esc(i.apc)}</td><td>${ugx(i.customs_value)}</td><td>${ugx(i.net_weight)}</td><td>${ugx(i.price_kg)}</td><td>${ugx(i.peer_kg)}</td><td class="t-red">${pct(i.price_vs_peers)}</td><td>${ugx(i.price_unit)}</td><td>${ugx(i.peer_unit)}</td><td>${pct(i.duty_rate)}</td><td>${pct(i.peer_duty_rate)}</td><td>${esc([i.price_signal,i.duty_signal].filter(Boolean).join('; '))}</td><td>${esc(i.peer_basis||'')} (${esc(i.peer_importers||'')})</td></tr>`).join('') + '</tbody></table>';
}

// ---------- post-clearance audit list ----------
function drawPca(){
  const q = document.getElementById('pq').value.trim().toLowerCase(), s = document.getElementById('ps').value;
  const l = document.getElementById('pl').value, n = document.getElementById('pn').checked;
  const hit = EN.filter(e => (!q || (e.taxpayer_tin||'').includes(q) || String(e.entry_num||'').toLowerCase().includes(q) || String(e.lowest_price_hs_code||'').includes(q))
    && (!s || e.strength === s) && (!l || e.lane === l) && (!n || e.topped_up !== 'Y'));
  const stake = hit.reduce((a,e)=>a+(e.tax_at_stake||0),0);
  document.getElementById('pcnt').textContent = EN.length ? `${hit.length.toLocaleString()} entries · tax at stake UGX ${ugx(stake)} (estimate)` + (D.entries_total > EN.length ? ` · the ${EN.length.toLocaleString()} strongest of ${D.entries_total.toLocaleString()} (all are in the workbook)` : '') + (hit.length > 500 ? ' · first 500 shown' : '') : 'The post-clearance audit downloads are not in data/pca/ yet.';
  document.getElementById('pl-body').innerHTML = hit.slice(0,500).map(e => `<tr data-tin="${e.taxpayer_tin}" style="cursor:pointer"><td>${e.rank}</td><td>${strengthTag(e.strength)}</td><td class="mono">${esc(e.entry_num)} ${esc(e.station)} ${esc(e.entry_year)}</td><td>${esc(e.assessed_on)}</td><td class="mono">${esc(e.taxpayer_tin)}</td><td>${esc(D.names[e.taxpayer_tin]||'')}</td><td>${esc(e.lane)}</td><td>${e.topped_up==='Y'?'Y':'N'}</td><td>${esc(e.signals)}</td><td>${pricePct(e)}</td><td>${ugx(e.tax_at_stake)}</td></tr>`).join('');
}
document.getElementById('pl-body').addEventListener('click', ev => { const tr = ev.target.closest('tr'); if (!tr) return;
  showTab('tp'); selected = tr.dataset.tin; document.getElementById('q').value = selected; drawList(); drawProfile(selected); });
['pq','ps','pl','pn'].forEach(id => document.getElementById(id).addEventListener('input', drawPca));

function showTab(t){
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x.dataset.t === t));
  document.getElementById('v-tp').classList.toggle('hide', t !== 'tp');
  document.getElementById('v-pca').classList.toggle('hide', t !== 'pca');
}
document.querySelectorAll('.tab').forEach(x => x.addEventListener('click', () => showTab(x.dataset.t)));
drawList(); drawPca();
</script></body></html>
"""
