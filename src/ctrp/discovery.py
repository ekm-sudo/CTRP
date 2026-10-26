"""
Track B: discovery. Finds risk the current process has not yet caught.

What: scores every taxpayer on BEHAVIOUR only (prices, amendments, how and what they trade), with
      no top-up history and no lane history in the inputs. Then measures how well each score
      ranks the taxpayers who had NO top-up in their history but were caught in the 6 months
      after the snapshot ("discovery lift").
Why:  Track A (the scorecard) ranks taxpayers already known to customs: every taxpayer in its
      top 5% had a top-up before (DECISIONS 59). Taxpayers with no top-up history gave 9% of later
      hits, and Track A barely ranks them (lift 1.34). Track B is built to find them.

    from ctrp import discovery as B
    table, detail = B.evaluate(extracts)          # extracts = {snapshot: raw DataFrame}
    or:  python main.py discovery

Rules that keep Track B honest
  1. No input that records what customs did: top-ups, tax reduced after assessment, red or
     yellow lanes. Otherwise Track B would copy the current selection, not discover.
  2. Learned versions train only on EARLIER snapshots whose outcomes had closed (as Track A's
     challengers do), and only on taxpayers with no top-up history, the group Track B is for.
  3. Every input has a stated risk direction, so a learned model can never reward the opposite.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from ctrp import core as M

SHARES = (0.05, 0.10)
K = 10                     # credibility weighting for rates, the same strength as Track A
# Behaviours still worked out (they stay in the final dataset) but left out of the model and its reasons.
# goods_spread ("many different kinds of goods per declaration"): describes general merchants and consolidators
# rather than risky behaviour, and more goods went with FEWER top-ups per check (DECISIONS 103). Compare with
# python main.py discovery --compare-without goods_spread before deciding.
DROPPED = {'goods_spread'}

# -----------------------------------------------------------------------------------------
# The behaviour features. (column, direction, rate-of, plain label)
#   direction +1: higher is riskier.  rate-of: the count the rate rests on (for weighting).
# Columns that only exist in version 2 extracts are used when present.
# -----------------------------------------------------------------------------------------
FEATURES = [
    # declaration behaviour
    ('par045_amended_entry_rate', +1, 'entries_24m', 'Declarations amended'),
    ('ctx_unpaid_rate', +1, 'entries_24m', 'Tax left unpaid'),
    ('ctx_implausible_price_rate', +1, 'items_benchmarked', 'Prices so low they look like keying errors'),
    # valuation
    ('par076_shortfall_share', +1, 'items_benchmarked', 'Value below the HS benchmark'),
    ('par076_low_price_item_rate', +1, 'items_benchmarked', 'Items priced below half the benchmark'),
    ('price_deviation_median', +1, None, 'Prices far from other importers (either way)'),
    ('own_price_drop_share', +1, None, 'Price dropped against own history'),
    # classification and duty
    ('low_duty_value_share', +1, None, 'Duty rate below HS peers'),
    ('duty_gap_share', +1, None, 'Duty shortfall against HS peers'),
    ('exemption_apc_value_share', +1, None, 'Value under exemption codes'),
    ('watchlist_apc_value_share', +1, None, 'Value under watch-list exemption codes'),
    ('ctx_preferential_use_rate', +1, None, 'Preferential treatment claimed'),
    # trading pattern
    ('surge', +1, None, 'Sudden rise in declarations'),
    ('station_spread', +1, None, 'Clearing away from the main station'),
    ('goods_spread', +1, None, 'Many different kinds of goods per declaration'),
    ('same_day_split_excess', +1, None, 'Same-day splitting above the norm'),
    ('newness', +1, None, 'Recently started importing'),
]
LABEL = {f: lab for f, _, _, lab in FEATURES}


# =========================================================================================
# 1. Features
# =========================================================================================
def _weighted_rate(d, col, ncol):
    """Credibility weighting, as in Track A: pull a rate towards the average when it rests on few
    declarations, and only ever DOWN (a clean small trader is never given others' behaviour)."""
    x = d[col].astype(float)
    n = d[ncol].fillna(0).astype(float)
    has = x.notna() & (n > 0)
    prior = (x[has] * n[has]).sum() / max(n[has].sum(), 1)
    w = n / (n + K)
    return np.minimum(x, w * x + (1 - w) * prior)


def build_features(raw):
    """What: one row per taxpayer, every behaviour feature that this extract can supply.
    Why:  the same table feeds the peer composite, the learned versions and the reasons."""
    d = raw
    X = pd.DataFrame(index=d.index)
    # derived measures
    quarter_avg = d['entries_24m'] / 8.0
    X['surge'] = np.log((d['entries_last_90d'] + 1) / (quarter_avg + 1))
    X['station_spread'] = 1.0 - d['main_station_share']
    X['goods_spread'] = d['hs_headings_used'] / d['entries_24m'].clip(lower=1)
    if 'days_since_first_in_window' in d:                         # version 2 extracts only
        X['newness'] = -np.log1p(d['days_since_first_in_window'].clip(lower=0))   # fewer days = newer
        if 'new_trader' in d:
            X['newness'] = X['newness'] + np.where(d['new_trader'] == 'Y', 1.0, 0.0)
    for col, _, ncol, _ in FEATURES:
        if col in X or col not in d:
            continue
        X[col] = _weighted_rate(d, col, ncol) if ncol and ncol in d else d[col].astype(float)
    return X


def section_size_groups(raw):
    """HS section x size tier (small, medium, large within the section), for every taxpayer."""
    sec = raw['dominant_hs_chapter'].map(M.hs_section).fillna('Unknown')
    logv = np.log1p(raw['total_customs_value'].clip(lower=0))
    tier = logv.groupby(sec).transform(
        lambda v: pd.qcut(v.rank(method='first'), 3, labels=False) if len(v) >= 3 else 0)
    return sec + ' | ' + tier.astype(str)


def peer_percentiles(X, groups):
    """What: each feature as a percentile within the taxpayer's peer group, direction applied.
    Why:  'higher than 97% of similar importers' is fair across goods and sizes, and reads
          directly as a reason. Missing values sit at the middle (0.5): no evidence either way."""
    P = pd.DataFrame(index=X.index)
    for col, sign, _, _ in FEATURES:
        if col not in X:
            continue
        v = sign * X[col]
        P[col] = v.groupby(groups).rank(pct=True).fillna(0.5)
    return P


# =========================================================================================
# 2. Scores. Each returns one number per taxpayer (higher = more worth a look).
# =========================================================================================
def score_peer_composite(P, train=None):
    """Unsupervised: average of how far above the peer median each feature sits (0 below it).
    Nothing is learned, so it cannot overfit; the yardstick the learned versions must beat."""
    return ((P - 0.5) / 0.5).clip(lower=0).mean(axis=1)


def _rows(P, raw, mask):
    """Two weighted rows per checked taxpayer (hit / no hit), so the model learns hits per check."""
    m = raw['out_checked'].to_numpy(float)
    y = raw['out_checked_hits'].to_numpy(float)
    keep = (m > 0) & mask.to_numpy()
    Xk = P.to_numpy()[keep]
    Xr = np.vstack([Xk, Xk])
    yr = np.r_[np.ones(keep.sum()), np.zeros(keep.sum())]
    wr = np.r_[y[keep], (m - y)[keep]]
    ok = wr > 0
    return Xr[ok], yr[ok], wr[ok]


SEGMENTS = {'regular': lambda r: r['entries_24m'] >= M.ADEQUATE_ENTRIES,
            'small': lambda r: r['entries_24m'] < M.ADEQUATE_ENTRIES}
SEGMENT = {'name': 'regular'}          # which segment the learned scores train on (set by evaluate)


def in_scope(raw):
    """No top-up history AND in the current segment: who Track B is being judged on."""
    return no_history(raw) & SEGMENTS[SEGMENT['name']](raw)


def _train_rows(train, cols):
    """The weighted training rows of every training snapshot, stacked: (features, labels, weights)."""
    parts = [_rows(Pt[cols], rt, in_scope(rt)) for rt, Pt in train]
    X = np.vstack([p[0] for p in parts])
    y = np.concatenate([p[1] for p in parts])
    w = np.concatenate([p[2] for p in parts])
    return X, y, w


def _boosting_model(n_features):
    """Additive monotone boosting: every feature may only raise risk (monotonic_cst = +1), and each
    feature is learned on its own (no interactions), so a score splits exactly into one part per feature."""
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, min_samples_leaf=300,
                                          random_state=M.SEED, monotonic_cst=[1] * n_features,
                                          interaction_cst=[[i] for i in range(n_features)])


def score_logistic(P, train):
    """Learned weights on the peer percentiles, trained on earlier snapshots' no-history taxpayers.
    Negative weights are not allowed to stand: a feature can only add risk (rule 3)."""
    cols = list(P.columns)
    X, y, w = _train_rows(train, cols)
    lr = LogisticRegression(C=0.5, max_iter=3000).fit(X, y, sample_weight=w)
    coef = pd.Series(np.clip(lr.coef_[0], 0, None), index=cols)
    score_logistic.last_weights = coef
    return (P[cols] * coef).sum(axis=1)


def score_boosting(P, train):
    """Additive monotone boosting on the same percentiles: learns a shape per feature (risk may
    only rise with the percentile), still one curve per feature, so every point is explainable."""
    cols = list(P.columns)
    X, y, w = _train_rows(train, cols)
    gb = _boosting_model(len(cols)).fit(X, y, sample_weight=w)
    return pd.Series(gb.predict_proba(P[cols].to_numpy())[:, 1], index=P.index)


SCORES = {'Track B: peer composite (nothing learned)': score_peer_composite,
          'Track B: learned weights': score_logistic,
          'Track B: monotone boosting': score_boosting}
LEARNED = {'Track B: learned weights', 'Track B: monotone boosting'}


# =========================================================================================
# 3. Measuring discovery
# =========================================================================================
def no_history(raw):
    """Taxpayers with no top-up in their 24-month history: the group Track B is for."""
    return raw['total_top_up'].fillna(0) <= 0


def _top(score, share):
    k = max(1, int(round(share * len(score))))
    return score.rank(ascending=False, method='first') <= k


def discovery_measures(raw, score, share):
    """Lift, hits and money within the no-history group of the current segment, at the top
    `share` of that group."""
    g = in_scope(raw)
    r, s = raw[g], score[g]
    base = r['out_checked_hits'].sum() / max(r['out_checked'].sum(), 1)
    t = r[_top(s, share)]
    hr = t['out_checked_hits'].sum() / max(t['out_checked'].sum(), 1)
    return dict(lift=hr / base if base else np.nan, hits=int(t['out_checked_hits'].sum()),
                checks=int(t['out_checked'].sum()), money=float(t['out_top_up'].sum()),
                money_share=float(t['out_top_up'].sum() / max(r['out_top_up'].sum(), 1)))


def auc_per_check(raw, score):
    """ROC AUC with each red or yellow check as one case (the main measure, DECISIONS 84 and 88),
    within the group being judged. 0.5 = no better than chance."""
    from sklearn.metrics import roc_auc_score
    h, c = raw['out_checked_hits'].to_numpy(float), raw['out_checked'].to_numpy(float)
    m = c > 0
    y = np.r_[np.ones(m.sum()), np.zeros(m.sum())]
    w = np.r_[h[m], c[m] - h[m]]
    sc = np.nan_to_num(np.r_[score[m], score[m]], nan=np.nanmin(score) if np.isfinite(score).any() else 0)
    k = w > 0
    if len(set(y[k])) < 2:
        return np.nan
    return roc_auc_score(y[k], sc[k], sample_weight=w[k])


def evaluate(extracts, test_from=2):
    """Every Track B score, plus Track A and single features for reference, on each test snapshot."""
    snaps = list(extracts)
    prepared = {}
    for s in snaps:
        raw = extracts[s].reset_index(drop=True)
        P = peer_percentiles(build_features(raw), section_size_groups(raw))
        prepared[s] = (raw, P)
    cols = sorted(set.intersection(*[set(P.columns) for _, P in prepared.values()]),
                  key=[f for f, *_ in FEATURES].index)
    cols = [c for c in cols if c not in DROPPED]
    rows, weights = [], {}
    for seg in SEGMENTS:
        SEGMENT['name'] = seg
        for t in range(test_from, len(snaps)):
            s = snaps[t]
            raw, P = prepared[s]
            P = P[cols]
            train = [(prepared[u][0], prepared[u][1][cols]) for u in snaps[:t]]
            scores = {name: f(P, train) for name, f in SCORES.items()}
            weights[(seg, s)] = score_logistic.last_weights
            scores['Track A: scorecard (reference)'] = M.layer2_scorecard(M.derive(raw))[0].sum(axis=1)
            for c in ['par045_amended_entry_rate', 'par076_shortfall_share']:
                scores[f'Single feature: {LABEL[c]}'] = P[c]
            g = in_scope(raw)
            for name, sc in scores.items():
                row = dict(segment=seg, snapshot=s, model=name, group_size=int(g.sum()),
                           group_hits=int(raw.loc[g, 'out_checked_hits'].sum()),
                           auc_per_check=auc_per_check(raw[g], np.asarray(sc, dtype=float)[g.to_numpy()]))
                for sh in SHARES:
                    m = discovery_measures(raw, sc, sh)
                    row.update({f'disc_{k}_top{int(sh * 100)}': v for k, v in m.items()})
                rows.append(row)
    detail = pd.DataFrame(rows)
    num = [c for c in detail.columns if c not in ('segment', 'snapshot', 'model')]
    table = detail.groupby(['segment', 'model'], sort=False)[num].mean()
    # How many test snapshots each score beats Track A on (discovery lift in the top 5%)
    track_a = (detail[detail.model == 'Track A: scorecard (reference)']
               .set_index(['segment', 'snapshot'])['disc_lift_top5'])
    d2 = detail.set_index(['segment', 'snapshot'])
    beats = d2['disc_lift_top5'] > track_a.reindex(d2.index)
    table['tests_beating_track_A'] = (beats.groupby([d2.index.get_level_values(0), d2['model']]).sum()
                                      .reindex(table.index).astype(int))
    evaluate.weights = pd.DataFrame(weights).rename(index=LABEL)
    evaluate.features = [LABEL[c] for c in cols]
    return table, detail


# =========================================================================================
# 4. Production: Track B scores, reasons and the discovery list for one snapshot
# =========================================================================================
# Share of each segment's no-history taxpayers put on the discovery list. Working values until
# the Risk Officers give their review capacity (meeting question 1).
DISCOVERY_SHARE = {'regular': 0.05, 'small': 0.01}
REFERENCE_PCT = 0.5          # a feature's contribution is measured against the peer median


def fit_models(train_extracts):
    """One additive monotone boosting model per segment, trained on the no-history taxpayers of
    every training snapshot (all of them must have closed outcome windows)."""
    prepared = []
    for raw in train_extracts:
        raw = raw.reset_index(drop=True)
        prepared.append((raw, peer_percentiles(build_features(raw), section_size_groups(raw))))
    cols = sorted(set.intersection(*[set(P.columns) for _, P in prepared]),
                  key=[f for f, *_ in FEATURES].index)
    cols = [c for c in cols if c not in DROPPED]
    models = {}
    for seg in SEGMENTS:
        SEGMENT['name'] = seg
        X, y, w = _train_rows([(r, P[cols]) for r, P in prepared], cols)
        models[seg] = _boosting_model(len(cols)).fit(X, y, sample_weight=w)
    return models, cols


def score_snapshot_b(raw, train_extracts):
    """What: Track B for every taxpayer: a discovery percentile within their segment, the two
    behaviours that push it up most (plain sentences), and whether they make the discovery list.
    Why:  the model is additive (one curve per behaviour), so each behaviour's share of the score
          is exact: the score with that behaviour at the peer median, subtracted from the score."""
    raw = raw.reset_index(drop=True)
    models, cols = fit_models(train_extracts)
    P = peer_percentiles(build_features(raw), section_size_groups(raw))[cols]
    out = pd.DataFrame({'taxpayer_tin': raw['taxpayer_tin'], 'segment': '', 'no_top_up_history': no_history(raw),
                        'discovery_score': np.nan, 'discovery_percentile': np.nan, 'on_discovery_list': 'N',
                        'discovery_reason_1': '', 'discovery_reason_2': ''})
    for seg, gb in models.items():
        m = SEGMENTS[seg](raw)
        if not m.any():
            continue
        Ps = P[m]
        dec = gb.decision_function(Ps.to_numpy())
        contrib = pd.DataFrame(index=Ps.index)
        for c in cols:
            ref = Ps.copy()
            ref[c] = REFERENCE_PCT
            contrib[c] = dec - gb.decision_function(ref.to_numpy())
        out.loc[m, 'segment'] = seg
        out.loc[m, 'discovery_score'] = dec
        out.loc[m, 'discovery_percentile'] = pd.Series(dec, index=Ps.index).rank(pct=True)
        # the list: the top share of this segment's no-history taxpayers
        g = m & out['no_top_up_history']
        k = max(1, int(round(DISCOVERY_SHARE[seg] * g.sum())))
        top = out.loc[g, 'discovery_score'].rank(ascending=False, method='first') <= k
        out.loc[top[top].index, 'on_discovery_list'] = 'Y'
        # reasons: the two largest positive contributions, in plain words
        for idx in Ps.index:
            row = contrib.loc[idx]
            best = row[row > 0].sort_values(ascending=False).head(2)
            for j, (c, _) in enumerate(best.items(), start=1):
                out.at[idx, f'discovery_reason_{j}'] = (
                    f'{LABEL[c]}: higher than {min(Ps.at[idx, c], 0.99):.0%} of similar importers '
                    f'(same main HS section and size)')
    return out


# =========================================================================================
# 5. Does leaving a behaviour out help or hurt? The same test with and without it.
# =========================================================================================
def compare_without(extracts, feature):
    """Run the Track B evaluation twice on the same back-test snapshots: with `feature` in the model and without it.
    Returns one row per segment, snapshot and learned model, and the averages."""
    global DROPPED
    keep = set(DROPPED)
    rows = []
    try:
        for label, dropped in [('with', keep - {feature}), ('without', keep | {feature})]:
            DROPPED = dropped
            _, detail = evaluate(extracts)
            d = detail[detail['model'].isin(['Track B: monotone boosting', 'Track B: learned weights'])]
            d = d[['segment', 'snapshot', 'model', 'auc_per_check', 'disc_lift_top5', 'disc_hits_top5',
                   'disc_money_top5']].copy()
            d['version'] = label
            rows.append(d)
    finally:
        DROPPED = keep
    both = pd.concat(rows)
    wide = both.pivot_table(index=['segment', 'model', 'snapshot'], columns='version',
                            values=['auc_per_check', 'disc_lift_top5', 'disc_hits_top5', 'disc_money_top5'])
    wide.columns = [f'{m} {v} {feature}' for m, v in wide.columns]
    for m in ['auc_per_check', 'disc_lift_top5', 'disc_hits_top5', 'disc_money_top5']:
        wide[f'{m} change'] = wide[f'{m} without {feature}'] - wide[f'{m} with {feature}']
    wide = wide.reset_index()
    avg = wide.groupby(['segment', 'model']).agg(
        auc_with=(f'auc_per_check with {feature}', 'mean'), auc_without=(f'auc_per_check without {feature}', 'mean'),
        auc_change=('auc_per_check change', 'mean'),
        dates_better=('auc_per_check change', lambda x: int((x > 0.001).sum())),
        dates_worse=('auc_per_check change', lambda x: int((x < -0.001).sum())),
        lift5_change=('disc_lift_top5 change', 'mean'), hits5_change=('disc_hits_top5 change', 'mean')).reset_index()
    return avg, wide
