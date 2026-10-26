"""
Testing candidate parameters from the NTC and eHub parameter lists against Track A.

What: for every candidate that the data we already hold can supply, three questions on every back-test date:
        1. Alone: does ranking taxpayers by it put checks that found a top-up above checks that did not?
           (ROC AUC per check, the headline measure; 0.5 = no better than chance)
        2. Added to Track A: does the scorecard rank checks better with it as a ninth parameter?
           Added at weight 3 (the weight of each of the five smaller parameters, about 4% of the points)
           and at weight 9 (about 11%), on a 0 to 1 scale from the median to the 95th percentile.
        3. Challengers: NTC's own rules (the computable rows of the Business Risk scorecard, and the
           lane-targeting thresholds for each tier) scored the same way as Track A.
Why:  a parameter earns points in Track A only if it helps rank the checks that find top-ups; weights
      chosen by opinion cannot be defended to a reviewer. The same test was used for the current eight.

Data:  long run, 18 dates (Sep 2017 to Mar 2026): hit rate, average top-up, value of top-ups, IM7 share,
       number of declarations, first-time importer.
       Full extracts, 7 dates: unpaid declarations, preferential treatment, goods, origins, procedure codes.
       Version 2 extracts, 4 dates: exemption APCs, watch-list APCs, own-price drop, duty below peers,
       duty shortfall, new trader, price far from peers, same-day splitting.

    python main.py candidates        -> results/CTRP_candidate_parameters.xlsx
"""
import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from sklearn.metrics import roc_auc_score

from ctrp import addon as AD
from ctrp import core as M
from ctrp import longrun as LR
from ctrp import register as R
from ctrp.utils import DATA_DIR, RESULTS_DIR, load_extract, top_mask

ROOT = DATA_DIR.parent
WEIGHTS = (3, 9)            # L x I: 3 = a smaller parameter (about 4% of points), 9 = about 11%


# =========================================================================================
# Candidates: (column, source parameters, plain label, data set, how the column is built)
# =========================================================================================
CANDIDATES = [
    # long run, 18 dates
    ('cand_hit_rate', 'NTC scorecard "Hit rate"; lane targeting',
     'Hit rate: share of checks that found a top-up (24 months)', 'lr'),
    ('cand_avg_top_up', 'NTC scorecard "Average top-up"; lane targeting',
     'Average top-up per topped-up declaration, UGX (24 months)', 'lr'),
    ('cand_top_up_value', 'PAR_049', 'Value of top-ups, UGX (24 months)', 'lr'),
    ('im7_share', 'Lane targeting exceptions ("IM7 ratio")', 'Share of declarations into bond (IM7)', 'lr'),
    ('cand_entries', 'PAR_063', 'Number of import declarations (24 months)', 'lr'),
    ('cand_first_time', 'PAR_019, PAR_101', 'First-time importer: first declaration in the last 12 months', 'lr'),
    # full extracts
    ('ctx_unpaid_rate', 'PAR_072; NTC "Timely payment"', 'Share of declarations assessed but not paid', 'full'),
    ('ctx_preferential_use_rate', 'PAR_050, PAR_087', 'Share of declarations claiming preferential treatment',
     'full'),
    ('origins_used', 'PAR_062, NTC "Origin of goods"', 'Number of countries of origin', 'full'),
    ('hs_headings_used', 'NTC "Nature of imports"', 'Number of different HS headings', 'full'),
    ('cpcs_used', 'NTC "Nature of APCs"', 'Number of procedure codes (APCs)', 'full'),
    # version 2 extracts
    ('exemption_apc_value_share', 'PAR_052, PAR_053; NTC "APCs"', 'Share of value under exemption APCs', 'v2'),
    ('watchlist_apc_value_share', 'PAR_053 (AC-Trade watch list)', 'Share of value under watch-list APCs', 'v2'),
    ('own_price_drop_share', 'PAR_067', 'Price dropped against own history', 'v2'),
    ('low_duty_value_share', 'PAR_096 (stand-in)', 'Share of value taxed below HS peers (no exemption)', 'v2'),
    ('duty_gap_share', 'PAR_096 (stand-in)', 'Duty shortfall against HS peers', 'v2'),
    ('new_trader', 'PAR_019, PAR_101', 'New trader (first seen in the window)', 'v2'),
    ('price_deviation_median', 'PAR_090 (stand-in)', 'Prices far from other importers (either way)', 'v2'),
    ('same_day_split_excess', 'Splitting (officers)', 'Same-day splitting above the norm', 'v2'),
    # long-run add-on (sql/long_run_addon), 18 dates once Hue returns it
    ('cand_sensitive_share', 'PAR_026 to PAR_028; NTC "Nature of imports"',
     'Share of value in EAC sensitive items', 'addon'),
    ('cand_full_exempt_share', 'PAR_052; NTC "APCs: exempting all taxes"',
     'Share of value under an APC that removed all tax', 'addon'),
    ('cand_partial_exempt_share', 'PAR_052; NTC "APCs: exempting one tax head"',
     'Share of value under an APC that removed part of the tax', 'addon'),
    ('cand_relief_share', 'PAR_053', 'Tax forgone through exemptions, as a share of normal tax', 'addon'),
    ('cand_origin_goods_rate', 'PAR_062, PAR_083, PAR_089; NTC "Origin of goods"',
     'Past hit rate of the same origin and HS chapter (value-weighted)', 'addon'),
    ('cand_ntc_origin_share', 'NTC "Origin of goods" (their country list)',
     "Share of value from NTC's 10-point origins", 'addon'),
    ('cand_im4_top_up_ratio', 'PAR_048 at IM4; lane targeting "IM4 ratio"', 'Top-ups over original tax, IM4 only',
     'addon'),
    ('cand_im7_top_up_ratio', 'PAR_048 at IM7; lane targeting "IM7 ratio"', 'Top-ups over original tax, IM7 only',
     'addon'),
]
DATA_LABEL = {'lr': 'Long run', 'full': 'Full extracts', 'v2': 'Version 2 extracts', 'addon': 'Long run with the add-on'}
YES_NO = {'Y': 1.0, 'N': 0.0, 'y': 1.0, 'n': 0.0}


# =========================================================================================
# Data
# =========================================================================================
def _lr_extra(panel, snap):
    """Per taxpayer, from the half-year counts: checks and hits in the 24 months, and the first declaration."""
    s = pd.Timestamp(snap)
    h24 = panel[panel['period_end'].isin(LR._periods(snap, 24))]
    g = h24.groupby('taxpayer_tin')[['checked', 'checked_hits', 'top_up_ugx', 'topped_up', 'entries']].sum()
    first = pd.to_datetime(panel[panel['period_end'] <= snap].groupby('taxpayer_tin')['first_dt'].min(),
                           format='%Y%m%d', errors='coerce')
    return pd.DataFrame({
        'cand_hit_rate': (g['checked_hits'] / g['checked']).where(g['checked'] > 0),
        'cand_avg_top_up': (g['top_up_ugx'] / g['topped_up']).where(g['topped_up'] > 0, 0.0),
        'cand_top_up_value': g['top_up_ugx'],
        'cand_entries': g['entries'].astype(float),
        'cand_first_time': ((s - first.reindex(g.index)).dt.days <= 365).astype(float),
        'hist_checked': g['checked'], 'hist_hits': g['checked_hits'],
    })


def datasets():
    """{'lr': {date: frame}, 'full': {...}, 'v2': {...}}, every frame with the candidate columns."""
    panel = LR.load()
    lr = {}
    for f in sorted((DATA_DIR / 'long_run').glob('lr_20*.csv')):
        snap = f.stem.replace('lr_', '')
        d = load_extract(f)
        x = _lr_extra(panel, snap)
        lr[snap] = d.join(x, on='taxpayer_tin')
    full = {f.stem.replace('bt_', ''): load_extract(f) for f in sorted(DATA_DIR.glob('bt_*.csv'))}
    v2 = {}
    for f in sorted((ROOT / 'data_v2').glob('bt_*.csv')):
        snap = f.stem.replace('bt_', '')
        v2[snap] = _with_yearly_counts(load_extract(f), snap)
    out = {'lr': lr, 'full': full, 'v2': v2, 'addon': {}}
    ap = AD.load()
    if ap is not None:                                # the add-on, once Hue has returned it
        for snap, d in lr.items():
            out['addon'][snap] = d.join(AD.features(ap, snap), on='taxpayer_tin')
    for frames in out.values():                       # Y/N flags (new_trader) as 1/0
        for d in frames.values():
            for col, *_ in CANDIDATES:
                if col in d and _is_text(d[col]):
                    d[col] = d[col].map(YES_NO).astype(float)
    return out


def _is_text(column):
    return column.dtype == object or str(column.dtype).startswith('str')


def _with_yearly_counts(d, snap):
    """Add the long run's yearly counts (y1_, y2_, y3_) for this date, for recency weighting as in production."""
    lrf = DATA_DIR / 'long_run' / f'lr_{snap}.csv'
    if not lrf.exists():
        return d
    ycols = [c for c in pd.read_csv(lrf, nrows=0).columns if c[:3] in ('y1_', 'y2_', 'y3_')]
    ycols += ['days_since_last_top_up_36m']
    y = pd.read_csv(lrf, dtype={'taxpayer_tin': str}, usecols=['taxpayer_tin'] + ycols)
    return d.drop(columns=[c for c in ycols if c in d]).merge(y, on='taxpayer_tin', how='left')


# =========================================================================================
# Scoring and measuring
# =========================================================================================
def track_a(raw, extra=None):
    """Track A points (unrounded) for every row, optionally with extra parameters appended."""
    saved = [dict(p) for p in M.PARAMS]
    try:
        if extra:
            M.PARAMS.extend(extra)
        d = M.derive(raw)
        points, _, _ = M.layer2_scorecard(d)
        return points.sum(axis=1).to_numpy()
    finally:
        M.PARAMS[:] = saved


def auc_per_check(raw, score):
    """ROC AUC with each check after the snapshot as one case (found a top-up or not). Blank scores rank last."""
    h, c = raw['out_checked_hits'].to_numpy(float), raw['out_checked'].to_numpy(float)
    score = np.nan_to_num(np.asarray(score, float), nan=-1e18)
    m = c > 0
    y = np.r_[np.ones(m.sum()), np.zeros(m.sum())]
    w = np.r_[h[m], c[m] - h[m]]
    sc = np.r_[score[m], score[m]]
    k = w > 0
    return roc_auc_score(y[k], sc[k], sample_weight=w[k])


def precision_top5(raw, score):
    """Share of checks on the top 5% of taxpayers that found a top-up."""
    h, c = raw['out_checked_hits'].to_numpy(float), raw['out_checked'].to_numpy(float)
    top = top_mask(np.nan_to_num(np.asarray(score, float), nan=-1e18), 0.05)
    return h[top].sum() / max(c[top].sum(), 1)


def scale_points(frames, col):
    """0 at the median, 1 at the 95th percentile, among regular taxpayers (10+ declarations), all dates
    pooled. If the median is 0 (most taxpayers never do it), 0 is the minimum risk level. Uses only the
    spread of the column, never the outcome."""
    v = pd.concat([f.loc[f['entries_24m'] >= 10, col] for f in frames.values()]).astype(float).dropna()
    lo, hi = v.quantile(0.5), v.quantile(0.95)
    if hi <= lo:
        nz = v[v > 0]
        lo, hi = 0.0, (nz.quantile(0.95) if len(nz) else 1.0)
    return float(lo), float(hi)


def test_candidates(data):
    """Each candidate alone and added to Track A (weights 3 and 9), on every date it has data for."""
    rows, per_date = [], []
    for col, src, label, which in CANDIDATES:
        frames = {k: f for k, f in data[which].items() if col in f and f[col].notna().any()}
        if not frames:
            continue
        lo, hi = scale_points(frames, col)
        res = {'alone': [], 'base': [], 'w3': [], 'w9': [], 'p_base': [], 'p_w9': [], 'p_w3': []}
        for snap, raw in frames.items():
            raw = raw.reset_index(drop=True)
            base = track_a(raw)
            alone = raw[col].astype(float).to_numpy()
            r = {'Candidate': label, 'Snapshot': snap, 'Alone': auc_per_check(raw, alone),
                 'Track A': auc_per_check(raw, base)}
            for w in WEIGHTS:
                p = dict(code='CAND', col=col, zero_at=lo, one_at=hi, L=3, I=w // 3, fmt='num', label=label,
                         reason='')
                sc = track_a(raw, [p])
                r[f'Track A + candidate (weight {w})'] = auc_per_check(raw, sc)
                res[f'p_w{w}'].append(precision_top5(raw, sc))
            res['p_base'].append(precision_top5(raw, base))
            res['alone'].append(r['Alone'])
            res['base'].append(r['Track A'])
            res['w3'].append(r['Track A + candidate (weight 3)'])
            res['w9'].append(r['Track A + candidate (weight 9)'])
            per_date.append(r)
        base, w3, w9 = map(np.array, (res['base'], res['w3'], res['w9']))
        best = 9 if w9.mean() >= w3.mean() else 3
        gain = (w9 if best == 9 else w3) - base
        rows.append({'Candidate': label, 'From': src, 'Data': DATA_LABEL[which],
                     'Dates': len(frames), 'AUC alone (average)': np.mean(res['alone']),
                     'Track A AUC (same dates)': base.mean(),
                     'Track A + candidate, weight 3': w3.mean(), 'Track A + candidate, weight 9': w9.mean(),
                     'Best gain in AUC': gain.mean(), 'Dates better (best weight)': int((gain > 0.0005).sum()),
                     'Dates worse (best weight)': int((gain < -0.0005).sum()),
                     'Precision top 5%: Track A': np.mean(res['p_base']),
                     'Precision top 5%: with candidate (best weight)': np.mean(res[f'p_w{best}']),
                     'Scale (minimum risk level to maximum)': f'{lo:,.3g} to {hi:,.3g}',
                     'Column': col})
    return pd.DataFrame(rows), pd.DataFrame(per_date)


# =========================================================================================
# Challengers: NTC's own rules
# =========================================================================================
def _top_up_ratio(raw):
    """Top-ups over original tax in the 24 months, 0 where there was no original tax."""
    return (raw['total_top_up'] / raw['total_original_tax'].where(raw['total_original_tax'] > 0)).fillna(0)


def ntc_scorecard(raw):
    """The rows of NTC's Business Risk scorecard that the data supports, with NTC's points and weights:
    hit rate (>10% = 10, >5% = 5) x 5; top-up over original tax (>5% = 5) x 5; average top-up (>UGX 15m = 5) x 5."""
    hr = raw['cand_hit_rate'].fillna(0)
    ratio = _top_up_ratio(raw)
    return (5 * np.select([hr > 0.10, hr > 0.05], [10, 5], 0) + 5 * np.where(ratio > 0.05, 5, 0)
            + 5 * np.where(raw['cand_avg_top_up'] > 15e6, 5, 0)).astype(float)


LANE = {  # tier: (red: ratio, hit, avg top-up), (yellow: ratio, hit, avg)
    'Tier 1': ((0.04, 0.03, 12e6), (0.03, 0.01, 12e6)),
    'Tier 2': ((0.05, 0.05, 15e6), (0.04, 0.01, 15e6)),
    'Tier 3': ((0.06, 0.07, np.inf), (-np.inf, -np.inf, np.inf)),   # Tier 3: yellow by default
}


def lane_rule(raw, tier):
    """NTC lane targeting for companies: RED (2) if any red threshold is passed, else YELLOW (1) if any
    yellow threshold is passed, else BLUE (0). The tier is not in the view, so each tier's thresholds
    are applied to everyone in turn."""
    (rr, rh, ra), (yr, yh, ya) = LANE[tier]
    hr = raw['cand_hit_rate'].fillna(0)
    ratio = _top_up_ratio(raw)
    avg = raw['cand_avg_top_up'].fillna(0)
    red = (ratio > rr) | (hr > rh) | (avg > ra)
    yel = (ratio > yr) | (hr > yh) | (avg >= ya)
    return np.where(red, 2.0, np.where(yel, 1.0, 0.0))


def test_challengers(data):
    """NTC's scorecard and lane-targeting rules against Track A, on the long-run dates."""
    rows = []
    for snap, raw in data['lr'].items():
        raw = raw.reset_index(drop=True)
        base = track_a(raw)
        r = {'Snapshot': snap, 'Track A': auc_per_check(raw, base),
             'NTC Business Risk scorecard (computable rows)': auc_per_check(raw, ntc_scorecard(raw))}
        for t in LANE:
            r[f'Lane targeting, {t} thresholds'] = auc_per_check(raw, lane_rule(raw, t))
        r['Precision top 5%: Track A'] = precision_top5(raw, base)
        r['Precision top 5%: NTC scorecard'] = precision_top5(raw, ntc_scorecard(raw))
        sc = ntc_scorecard(raw)
        r['Share of taxpayers with any NTC points'] = float((sc > 0).mean())
        if snap in data['addon']:                     # with the add-on: nature of imports, APCs, origin
            a = data['addon'][snap].reset_index(drop=True)
            # NTC's sheet gives weight 3 to nature of imports and none to APCs and origin; 1 is assumed
            ext = (sc + 3 * a['ntc_nature_points'].fillna(0) + a['ntc_apc_points'].fillna(0)
                   + a['ntc_origin_points'].fillna(0))
            r['NTC scorecard with nature of imports, APCs and origin'] = auc_per_check(raw, ext)
        rows.append(r)
    return pd.DataFrame(rows)


READ_ME = [
    'Candidate parameters from the NTC and Business Analysis lists, tested against Track A. Prepared by Data '
    'Science (ITID). No TINs.',
    '',
    'The test (the same one the current eight parameters passed)',
    'Every red or yellow check in the 6 months after a back-test date is one case: it found a top-up or it did not. '
    'A good parameter ranks the checks that found a top-up above the ones that did not.',
    'ROC AUC per check measures this: 0.5 = no better than chance, 1 = perfect. Track A scores about 0.82.',
    'Alone: the candidate on its own. Below 0.5 means the opposite of what the list assumes (higher value, FEWER '
    'top-ups).',
    'Added to Track A: the candidate as a ninth parameter, at weight 3 (like each smaller parameter, about 4% of the '
    'points) and at weight 9 (about 11%), scaled from the median to the 95th percentile. Better or worse on a date = '
    'AUC changed by more than 0.0005.',
    'Precision in the top 5%: the share of checks on the top 5% of taxpayers that found a top-up. A parameter that '
    'raises AUC but lowers this helps at the bottom of the list, not where officers look.',
    '',
    'Data: long run, 18 dates (Sep 2017 to Mar 2026); full extracts, 7 dates; version 2 extracts, 4 dates. Track A '
    'is scored on the same dates each time, so every comparison is like with like.',
    '',
    'Sheets',
    'Candidates: one row per candidate, averages over its dates.',
    'By date: every candidate on every date.',
    'NTC rules: NTC\'s Business Risk scorecard (the rows the data supports, with NTC\'s points and weights) and the '
    'lane-targeting thresholds, as challengers to Track A.',
    'Parameter register: every parameter in the lists shared, with its status and where its data is.',
    'Data request: what to ask for, in priority order, and why.',
    'The add-on query (sql/long_run_addon) fetches sensitive goods, depth of exemption, the origin and goods record '
    'and top-ups by regime; its candidates appear here once its results are saved in data/long_run_addon/.',
]
# Text columns of the register sheets: fixed width 60, wrapped
LONG_TEXT_SHEETS = ('Parameter register', 'Data request')
LONG_TEXT_COLUMNS = ('Where it stands', 'Why this priority', 'Parameters it unlocks', 'Data needed and where it is',
                     'Parameter', 'Where it is', 'What')
HEADER_FILL = PatternFill('solid', start_color='102A83')


def _format_sheet(ws):
    """White-on-blue header, widths from the content, wrapped register text, percent or 4-decimal numbers."""
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = HEADER_FILL
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for col in ws.columns:
        hdr = str(col[0].value or '')
        long = ws.title in LONG_TEXT_SHEETS and hdr in LONG_TEXT_COLUMNS
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
        width = 60 if long else min(max(10, width + 2), 60 if ws.title != 'Read me' else 170)
        ws.column_dimensions[col[0].column_letter].width = width
        for c in col[1:]:
            if long:
                c.alignment = Alignment(wrap_text=True, vertical='top')
            if isinstance(c.value, float):
                c.number_format = '0.0%' if 'Precision' in hdr or 'Share' in hdr else '0.0000'
    if ws.title not in ('Read me',):
        ws.freeze_panes = 'B2'


def write(summary, per_date, ch, out):
    """The workbook: the tests, NTC's rules, the parameter register and the data request."""
    reg = pd.DataFrame(R.REGISTER, columns=R.COLUMNS)
    req = pd.DataFrame(R.DATA_REQUEST, columns=R.DATA_REQUEST_COLUMNS)
    avg = (ch.mean(numeric_only=True).rename('Average over the dates').reset_index()
           .rename(columns={'index': 'Measure'}))
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        pd.DataFrame({'Read me': READ_ME}).to_excel(w, sheet_name='Read me', index=False)
        summary.sort_values('Best gain in AUC', ascending=False).to_excel(w, sheet_name='Candidates', index=False)
        per_date.to_excel(w, sheet_name='By date', index=False)
        avg.to_excel(w, sheet_name='NTC rules', index=False)
        ch.to_excel(w, sheet_name='NTC rules', index=False, startrow=len(avg) + 3)
        reg.to_excel(w, sheet_name='Parameter register', index=False)
        req.to_excel(w, sheet_name='Data request', index=False)
        for ws in w.book.worksheets:
            _format_sheet(ws)
    return out


def run(out=None):
    """Load every data set, run both tests and write the workbook."""
    data = datasets()
    summary, per_date = test_candidates(data)
    ch = test_challengers(data)
    out = write(summary, per_date, ch, out or RESULTS_DIR / 'CTRP_candidate_parameters.xlsx')
    return summary, per_date, ch, out
