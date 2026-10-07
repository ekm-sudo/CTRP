"""
Challenger models: other ways of ranking the same taxpayers, compared fairly with the scorecard.

What: builds each challenger on the same extracts, scores the same taxpayers, and measures all
      of them the same way (later hit-rate lift, revenue captured, stability).
Why:  a model is only "good" next to its alternatives. This file answers "would a different
      approach rank taxpayers better?" without touching the production model (ctrp.core).

    from ctrp.models import challengers as CH
    table, detail, weights = CH.compare(extracts)    # extracts = {snapshot: raw DataFrame}
    or from the project folder:  python main.py challengers

The challengers (first round; see DECISIONS 47 and the research report)
  Baseline           rank on past top-up ratio alone (the simplest possible rule)
  Scorecard          the adopted model (champion)
  Learned weights    logistic regression on the same 8 scaled parameters: lets outcomes set the weights
  Data-set shrinkage the scorecard, but small-count rates shrunk by a strength estimated from the data
  Monotone boosting  gradient boosting, additive, forced to respect each parameter's risk direction
  Peer percentile    unsupervised: how much worse than peers in the same HS section (one-sided)
  Ensemble (S&D)     unsupervised: Isolation Forest + PCA on one-sided peer deviations
  K-Means (S&D)      unsupervised: distance from the nearest cluster centre, one-sided deviations
  Gaussian mixture   unsupervised: how unlikely the taxpayer is under a fitted mixture, one-sided deviations
  Blends             average rank position across several of the above (DECISIONS 52 to 54)
  Stacked blend      members weighted by a logistic regression trained on earlier snapshots

Supervised challengers are trained only on EARLIER snapshots whose 6-month outcome window had
closed before the test snapshot, so no challenger ever sees the future it is scored on.
"""
import numpy as np
import pandas as pd
from scipy import optimize, stats
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from ctrp import core as M
from ctrp.utils import lift, paired_diff_ci, revenue_share, top_mask

SHARES = (0.01, 0.05, 0.10)
BOOT = 300                      # bootstrap resamples for the confidence interval on the difference
# Rates built from counts: (column, the count it is a share of). These get data-estimated shrinkage.
COUNT_RATES = {'top_up_entry_rate': 'entries_24m', 'par077_severe_top_up_rate': 'entries_24m',
               'par045_amended_entry_rate': 'entries_24m', 'par066_negative_top_up_rate': 'entries_24m',
               'par076_shortfall_share': 'items_benchmarked'}


# =========================================================================================
# Inputs shared by the challengers
# =========================================================================================
def scaled_params(d):
    """The 8 parameters on the scorecard's own 0..1 scale (the same inputs the scorecard uses)."""
    return pd.DataFrame({p['code']: M.scale(d[p['col']].astype(float), p['zero_at'], p['one_at']).fillna(0)
                         for p in M.PARAMS}, index=d.index)


def expert_weights():
    li = pd.Series({p['code']: p['L'] * p['I'] for p in M.PARAMS})
    return li / li.sum()


def section_of(d):
    return d['dominant_hs_chapter'].map(M.hs_section)


def one_sided_deviation(d):
    """What: how far each parameter sits ABOVE the median of the taxpayer's HS section, floored at 0.
    Why:  so unsupervised methods can only react to worse-than-peer behaviour, never to a taxpayer
          who is merely different (the cause of the Stage 6 failure)."""
    x = pd.DataFrame({p['code']: d[p['col']].astype(float).fillna(0) for p in M.PARAMS}, index=d.index)
    x['PAR_076'] = np.log1p(x['PAR_076'].clip(lower=0))
    med = x.groupby(section_of(d)).transform('median')
    return (x - med).clip(lower=0)


def hits_per_check_rows(d, raw, X):
    """What: two weighted rows per checked taxpayer: 'hit' (weight = hits) and 'no hit' (weight =
    checks - hits).  Why: the model then learns hits per check, exactly what lift measures."""
    m = raw['out_checked'].to_numpy(float)
    y = raw['out_checked_hits'].to_numpy(float)
    keep = m > 0
    Xk = X.to_numpy()[keep]
    Xr = np.vstack([Xk, Xk])
    yr = np.r_[np.ones(keep.sum()), np.zeros(keep.sum())]
    wr = np.r_[y[keep], (m - y)[keep]]
    ok = wr > 0
    return Xr[ok], yr[ok], wr[ok]


# =========================================================================================
# Data-estimated shrinkage (empirical Bayes, beta-binomial)
# =========================================================================================
def fit_beta_binomial(x, n):
    """What: estimate how much true rates vary between taxpayers (a, b of a beta distribution).
    Why:  K = a + b is the data's own answer to 'how many declarations before we trust a rate',
          instead of the fixed 10 used now."""
    x, n = np.asarray(x, int), np.asarray(n, int)
    keep = n > 0
    x, n = x[keep], n[keep]
    if len(x) > 20000:                                   # a sample is plenty and keeps it fast
        idx = np.random.default_rng(M.SEED).choice(len(x), 20000, replace=False)
        x, n = x[idx], n[idx]

    def nll(t):
        a, b = np.exp(t)
        return -stats.betabinom.logpmf(x, n, a, b).sum()
    m = max(x.sum() / n.sum(), 1e-4)
    res = optimize.minimize(nll, np.log([m * 10, (1 - m) * 10]), method='Nelder-Mead')
    return np.exp(res.x)


def eb_derive(raw):
    """derive() without the fixed one-way weighting, then two-way shrinkage with data-estimated K."""
    keep = M.SHRINK_K
    M.SHRINK_K = None
    try:
        d = M.derive(raw)
    finally:
        M.SHRINK_K = keep
    ks = {}
    for col, ncol in COUNT_RATES.items():
        n = d[ncol].fillna(0).round().astype(int)
        x = (d[col].fillna(0) * n).round().astype(int).clip(upper=n)
        a, b = fit_beta_binomial(x, n)
        d[col] = np.where(n > 0, (x + a) / (n + a + b), np.nan)
        ks[col] = a + b
    return d, ks


# =========================================================================================
# The challengers. Each returns one score per taxpayer (higher = riskier).
# =========================================================================================
def score_baseline(raw, d, train):
    return raw['par048_top_up_ratio'].fillna(0)


def score_scorecard(raw, d, train):
    pts, _, _ = M.layer2_scorecard(d)
    return pts.sum(axis=1)


def score_learned(raw, d, train):
    X = scaled_params(d)
    Xr, yr, wr = zip(*[hits_per_check_rows(td, tr, scaled_params(td)) for tr, td in train])
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(np.vstack(Xr), np.concatenate(yr), sample_weight=np.concatenate(wr))
    score_learned.last_weights = pd.Series(lr.coef_[0], index=X.columns)
    return pd.Series(lr.decision_function(X.to_numpy()), index=d.index)


def score_eb(raw, d, train):
    deb, ks = eb_derive(raw)
    score_eb.last_k = ks
    pts, _, _ = M.layer2_scorecard(deb)
    return pts.sum(axis=1)


def _boosting(raw, d, train, extra):
    def feats(dd):
        return pd.concat([scaled_params(dd), dd[extra].fillna(0)], axis=1)
    Xr, yr, wr = zip(*[hits_per_check_rows(td, tr, feats(td)) for tr, td in train])
    gb = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, min_samples_leaf=200, random_state=M.SEED,
        monotonic_cst=[1] * 8 + [0] * len(extra),
        interaction_cst=[[i] for i in range(8 + len(extra))])      # additive: one shape per feature
    gb.fit(np.vstack(Xr), np.concatenate(yr), sample_weight=np.concatenate(wr))
    return pd.Series(gb.predict_proba(feats(d).to_numpy())[:, 1], index=d.index)


def score_boosting(raw, d, train):
    """Same 8 inputs as the scorecard, so any gain comes from learned shapes, not new data."""
    return _boosting(raw, d, train, [])


def score_boosting_size(raw, d, train):
    """Adds declarations and value. Shown as a WARNING case: it lifts the hit rate by moving the
    top of the list onto small one-off importers, and catches fewer hits and less revenue."""
    return _boosting(raw, d, train, ['log_entries', 'log_value'])


def score_peer_percentile(raw, d, train):
    """Belgian-style baseline: expert-weighted sum of how far above the section median each
    parameter's percentile sits (0 at or below the median)."""
    x = pd.DataFrame({p['code']: d[p['col']].astype(float).fillna(0) for p in M.PARAMS}, index=d.index)
    sec = section_of(d)
    pctl = x.groupby(sec).rank(pct=True)
    above = x.gt(x.groupby(sec).transform('median'))
    part = ((pctl - 0.5) / 0.5).clip(0, 1).where(above, 0)
    return (part * expert_weights()).sum(axis=1)


def _unsup_input(d):
    return StandardScaler().fit_transform(one_sided_deviation(d))


def score_ensemble(raw, d, train):
    """Scope and Design ensemble: Isolation Forest and PCA reconstruction error on one-sided
    deviations, each turned into a percentile, combined by taking the larger."""
    X = _unsup_input(d)
    iso = -IsolationForest(n_estimators=200, random_state=M.SEED).fit(X).score_samples(X)
    pca = PCA(n_components=3, random_state=M.SEED).fit(X)
    rec = ((X - pca.inverse_transform(pca.transform(X))) ** 2).sum(axis=1)
    p1, p2 = pd.Series(iso).rank(pct=True), pd.Series(rec).rank(pct=True)
    return pd.Series(np.maximum(p1, p2).to_numpy(), index=d.index)


def score_kmeans(raw, d, train):
    X = _unsup_input(d)
    km = KMeans(n_clusters=8, n_init=5, random_state=M.SEED).fit(X)
    return pd.Series(km.transform(X).min(axis=1), index=d.index)


def score_gmm(raw, d, train):
    X = _unsup_input(d)
    gm = GaussianMixture(n_components=5, covariance_type='full', random_state=M.SEED).fit(X)
    return pd.Series(-gm.score_samples(X), index=d.index)


CHALLENGERS = {
    'Baseline (past top-up ratio)': score_baseline,
    'Scorecard (champion)': score_scorecard,
    'Learned weights (logistic)': score_learned,
    'Data-set shrinkage': score_eb,
    'Monotone boosting': score_boosting,
    'Monotone boosting + size (warning case)': score_boosting_size,
    'Peer percentile (one-sided)': score_peer_percentile,
    'Ensemble IF + PCA (one-sided)': score_ensemble,
    'K-Means distance (one-sided)': score_kmeans,
    'Gaussian mixture (one-sided)': score_gmm,
}
SUPERVISED = {'Learned weights (logistic)', 'Monotone boosting', 'Monotone boosting + size (warning case)'}

# =========================================================================================
# Ensembles: combining models
# What: a blend gives each taxpayer the AVERAGE of their rank positions in several models
#       (a taxpayer in the top 1% of every member stays at the top). The stacked blend lets
#       the outcomes of earlier snapshots decide how much each member counts.
# Why:  models that make different mistakes can cover for each other. The Scope and Design
#       candidates catch big-revenue traders; the scorecard catches frequent top-ups.
# =========================================================================================
UNSUPERVISED_SD = ['Peer percentile (one-sided)', 'Ensemble IF + PCA (one-sided)',
                   'K-Means distance (one-sided)', 'Gaussian mixture (one-sided)']
BLENDS = {
    'Blend: scorecard + boosting + learned weights': ['Scorecard (champion)', 'Monotone boosting', 'Learned weights (logistic)'],
    'Blend: scorecard + S&D candidates': ['Scorecard (champion)'] + UNSUPERVISED_SD,
    'Blend: scorecard + Gaussian mixture': ['Scorecard (champion)', 'Gaussian mixture (one-sided)'],
    'Blend: all models': ['Scorecard (champion)', 'Monotone boosting', 'Learned weights (logistic)', 'Data-set shrinkage'] + UNSUPERVISED_SD,
}
STACK_MEMBERS = ['Scorecard (champion)', 'Monotone boosting', 'Learned weights (logistic)'] + UNSUPERVISED_SD
STACKED = 'Stacked blend (weights learned from earlier snapshots)'


def rank_pct(score):
    return score.rank(pct=True)


def add_blends(scores):
    for name, members in BLENDS.items():
        scores[name] = pd.concat([rank_pct(scores[m]) for m in members], axis=1).mean(axis=1)
    return scores


def stacked_score(scores, raw, history):
    """Logistic regression on the members' rank positions, trained on EARLIER test snapshots only."""
    if not history:
        return None
    Xr, yr, wr = zip(*[hits_per_check_rows(None, r_, X_) for r_, X_ in history])
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(np.vstack(Xr), np.concatenate(yr), sample_weight=np.concatenate(wr))
    stacked_score.last_weights = pd.Series(lr.coef_[0], index=STACK_MEMBERS)
    X = pd.DataFrame({m: rank_pct(scores[m]) for m in STACK_MEMBERS})
    return pd.Series(lr.decision_function(X.to_numpy()), index=X.index)


# =========================================================================================
# Measuring them all the same way (the measures live in ctrp.utils)
# =========================================================================================
def compare(extracts, test_from=2, boot=True):
    """Run every challenger on every test snapshot (training only on earlier ones)."""
    snaps = list(extracts)
    D = {s: M.derive(extracts[s]) for s in snaps}
    rows, prev, weights, history, stack_w = [], {}, {}, [], {}
    for t in range(test_from, len(snaps)):
        s = snaps[t]
        raw, d = extracts[s].reset_index(drop=True), D[s].reset_index(drop=True)
        train = [(extracts[u].reset_index(drop=True), D[u].reset_index(drop=True)) for u in snaps[:t]]
        scores = {name: f(raw, d, train).reset_index(drop=True) for name, f in CHALLENGERS.items()}
        weights[s] = score_learned.last_weights
        add_blends(scores)
        st = stacked_score(scores, raw, history)
        if st is not None:
            scores[STACKED] = st
            stack_w[s] = stacked_score.last_weights
        history.append((raw, pd.DataFrame({m: rank_pct(scores[m]) for m in STACK_MEMBERS})))
        champ = scores['Scorecard (champion)']
        champ_top = set(raw.loc[top_mask(champ, 0.05), 'taxpayer_tin'])
        red = raw['ctx_red_lane_rate'].fillna(0)
        for name, sc in scores.items():
            top = raw.loc[top_mask(sc, 0.05)]
            row = dict(snapshot=s, model=name,
                       **{f'lift_top{int(x * 100)}': lift(raw, sc, x) for x in SHARES},
                       hits_top5=top['out_checked_hits'].sum(),
                       revenue_top5=revenue_share(raw, sc, 0.05),
                       small_share_top5=(top['entries_24m'] < M.ADEQUATE_ENTRIES).mean(),
                       checked_in_top5=(top['out_checked'] > 0).mean(),
                       overlap_with_champion=len(set(top['taxpayer_tin']) & champ_top) / len(champ_top),
                       corr_past_red_lane=stats.spearmanr(sc, red).statistic)
            if name in prev:                                   # stability: same taxpayers, next snapshot
                p = prev[name]
                common = raw['taxpayer_tin'].isin(p.index)
                row['rank_stability'] = stats.spearmanr(sc[common.to_numpy()],
                                                        p.loc[raw.loc[common, 'taxpayer_tin']]).statistic
            if boot and name != 'Scorecard (champion)':
                lo, hi = paired_diff_ci(raw, sc, champ, reps=BOOT)
                row['diff_vs_champion_top5_lo'], row['diff_vs_champion_top5_hi'] = lo, hi
            rows.append(row)
        prev = {n: pd.Series(sc.to_numpy(), index=raw['taxpayer_tin']) for n, sc in scores.items()}
    detail = pd.DataFrame(rows)
    table = detail.groupby('model', sort=False).agg(
        lift_top1=('lift_top1', 'mean'), lift_top5=('lift_top5', 'mean'), lift_top10=('lift_top10', 'mean'),
        hits_top5=('hits_top5', 'mean'), revenue_top5=('revenue_top5', 'mean'),
        small_share_top5=('small_share_top5', 'mean'), checked_in_top5=('checked_in_top5', 'mean'),
        overlap_with_champion=('overlap_with_champion', 'mean'), rank_stability=('rank_stability', 'mean'),
        corr_past_red_lane=('corr_past_red_lane', 'mean'))
    if boot:
        sig = detail.dropna(subset=['diff_vs_champion_top5_lo']).groupby('model', sort=False).apply(
            lambda g: f"{(g['diff_vs_champion_top5_lo'] > 0).sum()} better / {(g['diff_vs_champion_top5_hi'] < 0).sum()} worse",
            include_groups=False)
        table['vs_champion_top5 (of tests)'] = sig
    w = pd.DataFrame(weights)
    learned = (w.clip(lower=0).div(w.clip(lower=0).sum())).mean(axis=1)
    weights_table = pd.DataFrame({'expert weight': expert_weights(), 'learned weight (average)': learned})
    compare.stack_weights = pd.DataFrame(stack_w)
    return table, detail, weights_table

