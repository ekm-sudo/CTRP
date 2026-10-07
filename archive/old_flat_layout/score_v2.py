"""
Customs Taxpayer Risk Profiling Model, release 1: scoring and back-test.

Layers
  L1  peer segmentation      HDBSCAN on structural features; unclustered taxpayers go to the
                             nearest group and carry the "no close peers" flag
  L2  directional scorecard  each parameter scaled 0..1 between its concern level and worst
                             case; weight = L x I / sum(L x I); missing parameters rescale the rest
  L3  pattern check          Isolation Forest within each peer group, capped at 15 points,
                             discounted for taxpayers with no close peers
  L4  composite and band     subtotal + adjustment, rounded, banded
  (Business rules: none in release 1, because no rule flags are in the source view yet.)

Usage (PowerShell, from the project folder)
  python score_v2.py data\bt_2026-03-31.csv          # one snapshot
  python score_v2.py data\bt_*.csv                    # all back-test snapshots + summary
  python score_v2.py data\live_2026-09-30.csv         # live scores

Input  : CSVs downloaded from Hue after running the queries in sql\ (see make_sql.py).
         Each row is a taxpayer; the out_* columns hold what happened in the 6 months after.
Output : results\scores_<snapshot>.csv, results\diagnostics_<snapshot>.txt,
         results\backtest_<snapshot>.csv, and results\backtest_summary.csv across snapshots
Needs  : pandas, numpy, scikit-learn >= 1.3
"""
import argparse
import glob
import sys
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings('ignore', category=FutureWarning)

# =====================================================================================
# CONFIGURATION. Everything a risk officer may want to change sits here.
# zero_at : value at which a taxpayer begins to be of concern (scores 0)
# one_at  : value at which the parameter is as bad as it gets (scores 1)
# For direction 'lower', smaller values are riskier and zero_at > one_at.
# L, I    : likelihood and impact, 1 to 5. Parameters with L <= 2 are context only.
# All values below are PROVISIONAL. The L and I are the illustrative ratings used in the
# Design and Architecture worked example, so the document and the model agree until the
# ratings session replaces them. Scale points are to be set against the distributions
# printed in the diagnostics file.
# =====================================================================================
PARAMS = [
    # code      column                           direction  zero_at  one_at  L  I  label
    ('PAR_077', 'par077_severe_top_up_rate',     'higher',  0.02,    0.20,   4, 5, 'Top-ups of 30% or more of final tax'),
    ('PAR_048', 'par048_top_up_ratio',           'higher',  0.06,    0.33,   4, 4, 'Top-ups over original tax'),
    ('PAR_076', 'par076_shortfall_share',        'higher',  0.02,    0.20,   4, 4, 'Value shortfall against benchmark'),
    ('PAR_045', 'par045_amended_entry_rate',     'higher',  0.10,    0.50,   3, 4, 'Declarations amended'),
    ('PAR_105', 'par105_recency',                'higher',  0.00,    1.00,   3, 4, 'Recent top-ups (90 and 180 days)'),
    ('PAR_066', 'par066_negative_top_up_rate',   'higher',  0.02,    0.20,   3, 3, 'Declarations with negative top-ups'),
    ('PAR_023', 'par023_station_spread',         'higher',  0.30,    0.70,   3, 2, 'Clearance spread across stations'),
]
# PAR_048: 0.06 and 0.33 are the two officers' thresholds on original tax. Scoring starts at
# the lower and is full at the higher until the distribution settles which is right.

ADEQUATE_ENTRIES = 10            # below this: limited history, no pattern adjustment
PEER_FEATURES = ['log_value', 'log_entries', 'active_months', 'avg_items_per_entry',
                 'hs_headings_used', 'origins_used', 'cpcs_used', 'stations_used_24m',
                 'chapter_value_share']
MIN_CLUSTER_SIZES = [50, 100, 200]   # tried in turn; the one with the lowest noise share is used
# Extra features the pattern check (Layer 3) uses. They carry no points of their own:
# they only help decide how unusual a taxpayer is within their peer group.
PATTERN_FEATURES = ['volume_trend', 'im7_share', 'log_consignees', 'consignee_is_self_share',
                    'top_up_entry_rate', 'stations_used_90d']
TOP_SHARES = [0.01, 0.05, 0.10]  # back-test: the top 1%, 5% and 10% of taxpayers by score
RESULTS = Path('results')
PATTERN_CAP = 15.0               # maximum points from the pattern check
PATTERN_START_PCT = 0.80         # only the most unusual 20% within a peer group earn points
NO_PEERS_DISCOUNT = 0.5          # multiplier on the adjustment for taxpayers with no close peers
LOW_AGREE = {'score_low': 0.25, 'pattern_high': 0.95, 'score_high': 0.90, 'pattern_low': 0.10}
BANDS = [(15, 'VERY LOW'), (35, 'LOW'), (50, 'MEDIUM'), (80, 'HIGH'), (101, 'VERY HIGH')]
SEED = 42


# =====================================================================================
def derive(df):
    """Columns the scorecard needs that are not straight from SQL."""
    d = df.copy()
    days = d['par105_days_since_last_top_up']
    d['par105_recency'] = np.select([days <= 90, days <= 180], [1.0, 0.5], default=0.0)
    d.loc[days.isna(), 'par105_recency'] = 0.0             # never topped up: no recency risk
    d['par023_station_spread'] = 1.0 - d['main_station_share']
    d['log_value'] = np.log1p(d['total_customs_value'].clip(lower=0))
    d['log_entries'] = np.log1p(d['entries_24m'])
    d['volume_trend'] = np.log((d['entries_last_90d'] + 1) / (d['entries_prev_90d'] + 1))
    d['log_consignees'] = np.log1p(d['distinct_consignees'])
    d['adequate'] = d['entries_24m'] >= ADEQUATE_ENTRIES
    return d


def scale(x, zero_at, one_at):
    """0 at the concern level, 1 at the worst case, linear between, held at the ends."""
    return ((x - zero_at) / (one_at - zero_at)).clip(0, 1)


def layer2_scorecard(d):
    scored = [p for p in PARAMS if p[5] > 2]
    li = {p[0]: p[5] * p[6] for p in scored}
    scaled = pd.DataFrame({p[0]: scale(d[p[1]].astype(float), p[3], p[4]) for p in scored}, index=d.index)
    avail = scaled.notna()
    li_avail = avail.mul(pd.Series(li)).sum(axis=1)               # sum of L x I over available params
    weights = avail.mul(pd.Series(li)).div(li_avail, axis=0) * 100 # rescaled so they still total 100
    points = (scaled.fillna(0) * weights).round(4)
    out = pd.DataFrame(index=d.index)
    for c in points.columns:
        out[f'pts_{c}'] = points[c]
    out['scorecard_subtotal'] = points.sum(axis=1)
    out['n_params_scored'] = avail.sum(axis=1)
    labels = {p[0]: p[7] for p in scored}

    def reasons(row):
        top = row[row >= 0.05].sort_values(ascending=False).head(3)
        return '; '.join(f'{labels[k]} ({k}) {v:.1f}' for k, v in top.items())
    out['top_reasons'] = points.apply(reasons, axis=1)
    return out


def layer1_peers(d, log):
    adequate = d[d['adequate']].copy()
    X = adequate[PEER_FEATURES].fillna(adequate[PEER_FEATURES].median())
    Xs = RobustScaler().fit_transform(X)
    best = None
    for mcs in MIN_CLUSTER_SIZES:
        lab = HDBSCAN(min_cluster_size=mcs, min_samples=10).fit_predict(Xs)
        noise = (lab == -1).mean()
        n = len(set(lab)) - (1 if -1 in lab else 0)
        log.append(f'  HDBSCAN min_cluster_size={mcs}: {n} groups, {noise:.1%} unclustered')
        if n >= 2 and (best is None or noise < best[1]):
            best = (mcs, noise, lab)
    if best is None:
        # Fallback so the pattern check still compares like with like: three size tiers.
        log.append('  No setting gave 2 or more groups: falling back to three size tiers by customs value.')
        lab = pd.qcut(adequate['log_value'].rank(method='first'), 3, labels=False).to_numpy()
        res = pd.DataFrame({'peer_group': lab, 'no_close_peers': 'N'}, index=adequate.index)
        return res
    else:
        log.append(f'  Using min_cluster_size={best[0]}')
        lab = best[2]
    no_peers = lab == -1
    if no_peers.any() and (lab >= 0).any():
        groups = sorted(set(lab[lab >= 0]))
        cents = np.vstack([Xs[lab == g].mean(axis=0) for g in groups])
        dist = ((Xs[no_peers][:, None, :] - cents[None, :, :]) ** 2).sum(axis=2)
        lab = lab.copy()
        lab[no_peers] = np.array(groups)[dist.argmin(axis=1)]
    res = pd.DataFrame({'peer_group': lab, 'no_close_peers': np.where(no_peers, 'Y', 'N')},
                       index=adequate.index)
    return res


def layer3_pattern(d, peers, card):
    cols = [p[1] for p in PARAMS] + PEER_FEATURES + PATTERN_FEATURES
    adj = pd.Series(0.0, index=d.index)
    pct = pd.Series(np.nan, index=d.index)
    for g, idx in peers.groupby('peer_group').groups.items():
        sub = d.loc[idx, cols].astype(float)
        sub = sub.fillna(sub.median()).fillna(0)
        if len(sub) < 30:
            continue                                                # too small to judge; no adjustment
        iso = IsolationForest(n_estimators=200, random_state=SEED).fit(sub)
        anomaly = -iso.score_samples(sub)                           # higher = more unusual
        pct.loc[idx] = pd.Series(anomaly, index=idx).rank(pct=True)
    a = ((pct - PATTERN_START_PCT) / (1 - PATTERN_START_PCT)).clip(0, 1) * PATTERN_CAP
    a = a.fillna(0)
    nop = peers['no_close_peers'].reindex(d.index).eq('Y')
    a[nop] = a[nop] * NO_PEERS_DISCOUNT
    adj[:] = a
    # low agreement: scorecard and pattern check point in opposite directions
    s_pct = card['scorecard_subtotal'].rank(pct=True)
    low = ((s_pct < LOW_AGREE['score_low']) & (pct > LOW_AGREE['pattern_high'])) | \
          ((s_pct > LOW_AGREE['score_high']) & (pct < LOW_AGREE['pattern_low']))
    return adj.round(2), pct, np.where(low, 'Y', 'N')


def band(score):
    for upper, name in BANDS:
        if score <= upper:
            return name
    return BANDS[-1][1]


def diagnostics(d, card, log):
    log.append('\nPARAMETER DISTRIBUTIONS (set zero_at and one_at against these)')
    qs = [0.5, 0.75, 0.9, 0.95, 0.99]
    rows = []
    for code, col, _, z, o, *_ in PARAMS:
        x = d[col].astype(float)
        rows.append([code, x.notna().mean()] + list(x.quantile(qs).values) + [(x > z).mean(), (x >= o).mean()])
    t = pd.DataFrame(rows, columns=['param', 'available'] + [f'p{int(q*100)}' for q in qs]
                     + ['share_above_zero_at', 'share_at_one_at'])
    log.append(t.round(4).to_string(index=False))
    log.append('\nCORRELATION BETWEEN SCORED PARAMETERS (Spearman; above 0.7 means they measure the same thing)')
    log.append(d[[p[1] for p in PARAMS]].astype(float).corr(method='spearman').round(2).to_string())


def backtest(m, log):
    """What happened in the 6 months after the snapshot, by band and by rank."""
    def summarise(frame, key):
        g = frame.groupby(key, observed=True).agg(
            taxpayers=('taxpayer_tin', 'count'), entries=('out_entries', 'sum'),
            checked=('out_checked', 'sum'), hits=('out_checked_hits', 'sum'),
            top_up=('out_top_up', 'sum'), original_tax=('out_original_tax', 'sum'))
        g['hit_rate'] = g['hits'] / g['checked'].replace(0, np.nan)
        g['top_up_rate'] = g['top_up'] / g['original_tax'].replace(0, np.nan)
        return g

    order = [b for _, b in BANDS]
    bt = summarise(m, 'band').reindex(order)
    base = summarise(m.assign(all='ALL'), 'all').iloc[0]
    log.append('\nBACK-TEST BY BAND (what happened in the 6 months after the snapshot)')
    log.append(bt.round(4).to_string())
    log.append(f"Everyone: hit rate {base['hit_rate']:.4f}, top-up rate {base['top_up_rate']:.4f}")

    # The bands are not calibrated yet, so also compare like with like by rank: the top
    # x% of taxpayers by model score against the top x% by past top-up ratio alone.
    rows = []
    model_rank = (m['scorecard_subtotal'] + m['pattern_adjustment']).rank(ascending=False, method='first')
    base_rank = m['par048_top_up_ratio'].fillna(0).rank(ascending=False, method='first')
    for share in TOP_SHARES:
        k = max(1, int(round(share * len(m))))
        for name, rank in [('model', model_rank), ('baseline_par048', base_rank)]:
            g = summarise(m[rank <= k].assign(all='x'), 'all').iloc[0]
            rows.append({'top_share': share, 'ranked_by': name, 'taxpayers': k,
                         'hit_rate': g['hit_rate'], 'top_up_rate': g['top_up_rate'],
                         'hit_lift': g['hit_rate'] / base['hit_rate'] if base['hit_rate'] else np.nan})
    rk = pd.DataFrame(rows)
    log.append('\nBACK-TEST BY RANK (lift = hit rate divided by everyone\'s hit rate)')
    log.append(rk.round(4).to_string(index=False))
    log.append('The model earns its place only if its rows beat the baseline rows at the same share.')
    return bt.reset_index(), rk, base


def score_file(path):
    raw = pd.read_csv(path)
    raw.columns = [c.split('.')[-1].lower() for c in raw.columns]   # Hue may prefix columns
    if raw['taxpayer_tin'].duplicated().any():
        sys.exit(f'{path}: more than one row for some TINs; fix before scoring.')
    snap = str(raw['snapshot_date'].iloc[0])[:10]
    d = derive(raw)
    log = [f'Snapshot {snap}: {len(d):,} taxpayers, {d["adequate"].sum():,} with {ADEQUATE_ENTRIES}+ entries']

    card = layer2_scorecard(d)
    log.append('\nLAYER 1: peer segmentation')
    peers = layer1_peers(d, log)
    adj, pat_pct, low = layer3_pattern(d, peers, card)

    keep = ['taxpayer_tin', 'snapshot_date', 'limited_history', 'entries_24m', 'total_customs_value',
            'dominant_hs_chapter'] + [p[1] for p in PARAMS] + [c for c in d.columns if c.startswith('ctx_')]
    out = d[keep].join(card).join(peers)
    out['peer_group'] = out['peer_group'].fillna(-1).astype(int)    # -1: limited history, not segmented
    out['no_close_peers'] = out['no_close_peers'].fillna('N')
    out['pattern_adjustment'] = adj
    out['pattern_percentile'] = pat_pct.round(4)
    out['low_agreement'] = low
    out['score'] = (out['scorecard_subtotal'] + out['pattern_adjustment']).round().clip(0, 100).astype(int)
    out['band'] = out['score'].apply(band)

    log.append('\nBAND DISTRIBUTION')
    log.append(out['band'].value_counts().reindex([b for _, b in BANDS]).fillna(0).astype(int).to_string())
    log.append('\nSCORE PERCENTILES')
    log.append(out['score'].quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]).to_string())
    diagnostics(d, card, log)

    RESULTS.mkdir(exist_ok=True)
    out.to_csv(RESULTS / f'scores_{snap}.csv', index=False)
    summary = None
    if 'out_entries' in d.columns and d['out_entries'].sum() > 0:
        m = out.join(d[[c for c in d.columns if c.startswith('out_')]])
        bt, rk, base = backtest(m, log)
        bt.assign(snapshot=snap).to_csv(RESULTS / f'backtest_{snap}.csv', index=False)
        summary = rk.assign(snapshot=snap, everyone_hit_rate=base['hit_rate'],
                            everyone_top_up_rate=base['top_up_rate'])
    (RESULTS / f'diagnostics_{snap}.txt').write_text('\n'.join(log))
    print('\n'.join(log))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+', help='one or more CSVs; wildcards allowed')
    a = ap.parse_args()
    files = sorted({f for pat in a.files for f in (glob.glob(pat) or [pat])})
    summaries = [s for s in (score_file(f) for f in files) if s is not None]
    if len(summaries) > 1:
        allrk = pd.concat(summaries, ignore_index=True)
        allrk.to_csv(RESULTS / 'backtest_summary.csv', index=False)
        piv = allrk.pivot_table(index=['top_share', 'ranked_by'], columns='snapshot', values='hit_lift')
        print('\n' + '=' * 88 + '\nHIT-RATE LIFT ACROSS SNAPSHOTS (1.0 = no better than everyone)')
        print(piv.round(2).to_string())
        print('\nThe model is consistent if its lift beats the baseline in every snapshot, not just on average.')


if __name__ == '__main__':
    main()
