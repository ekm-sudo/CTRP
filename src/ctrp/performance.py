"""
Standard performance measures for Track A on every back-test snapshot.

What: precision, recall, ROC AUC, average precision and accuracy, at taxpayer level, plus the hit
      rate in each risk band, for each back-test snapshot (24 months of history, 6 months outcome).
Why:  lift, hits and revenue answer "is the top of the list worth checking?". These answer the
      questions a data-science reviewer will ask, and show whether ranking quality holds over time.

Definitions (taxpayer level, among taxpayers customs checked at least once in the outcome window):
  positive   = at least one check (red or yellow lane) ended in a top-up
  precision  = share of the flagged who were positive
  recall     = share of all positives that were flagged
  ROC AUC    = chance a random positive scores above a random negative (0.5 = coin toss)
  accuracy   = share classified correctly; shown next to "call everyone negative" because with
               few positives that lazy rule already scores high
Flagged = top 5% by History Risk Score, and separately History Risk Band HIGH or VERY HIGH.

Per-check measures (the HEADLINE, DECISIONS 84): every red or yellow check is one case, a hit or not,
and carries its taxpayer's score. This matches how officers judge selectivity (hits per check).
The taxpayer-level label "at least one top-up" rewards being checked often: a taxpayer checked
50 times is almost sure to have one, so it partly measures how often customs looked, not risk.
Unchecked taxpayers are left out: with no check there is no outcome to compare with.

    python main.py performance        -> results/CTRP_performance.xlsx
"""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from ctrp import core as M
from ctrp.utils import RESULTS_DIR, backtest_extracts, top_mask

BANDS = ['VERY HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY LOW']


def _measures(y, flag):
    """Precision, recall and accuracy of a yes or no flag against the outcome y (both boolean arrays)."""
    tp, fp = (flag & y).sum(), (flag & ~y).sum()
    fn, tn = (~flag & y).sum(), (~flag & ~y).sum()
    return dict(precision=tp / max(tp + fp, 1), recall=tp / max(tp + fn, 1),
                accuracy=(tp + tn) / max(tp + tn + fp + fn, 1))


def per_check(raw, score):
    """Precision, recall and ROC AUC with each check as a case (hits per check)."""
    h, c = raw['out_checked_hits'].to_numpy(float), raw['out_checked'].to_numpy(float)
    top = top_mask(score, 0.05)
    m = c > 0
    y = np.r_[np.ones(m.sum()), np.zeros(m.sum())]
    w = np.r_[h[m], c[m] - h[m]]
    sc = np.r_[score[m], score[m]]
    k = w > 0
    return {'Per check: hit rate, everyone': h.sum() / max(c.sum(), 1),
            'Per check: precision, top 5%': h[top].sum() / max(c[top].sum(), 1),
            'Per check: recall, top 5%': h[top].sum() / max(h.sum(), 1),
            'Per check: ROC AUC': roc_auc_score(y[k], sc[k], sample_weight=w[k])}


CUTS = [('Top 1%', 0.01), ('Top 5%', 0.05), ('Top 10%', 0.10), ('Top 20%', 0.20),
        ('VERY HIGH', ['VERY HIGH']), ('HIGH and above', ['HIGH', 'VERY HIGH']),
        ('MEDIUM and above', ['MEDIUM', 'HIGH', 'VERY HIGH']), ('All taxpayers', 1.0)]


def cutoffs(raw, score, band):
    """Per check, for each line officers could draw: precision and recall above the line.
    Why several lines: precision and recall only mean something for a chosen line (who gets
    checked). With every taxpayer above the line, recall is 100% and precision is just the
    average hit rate, which says nothing about the model. The line officers will use is a band."""
    h, c = raw['out_checked_hits'].to_numpy(float), raw['out_checked'].to_numpy(float)
    out = []
    for name, rule in CUTS:
        m = np.isin(band, rule) if isinstance(rule, list) else top_mask(score, rule)
        out.append({'Line': name, 'Share of taxpayers above it': m.mean(),
                    'Share of checks above it': c[m].sum() / max(c.sum(), 1),
                    'Precision (hits per check)': h[m].sum() / max(c[m].sum(), 1),
                    'Recall (share of all hits)': h[m].sum() / max(h.sum(), 1),
                    'Share of top-up money': raw.loc[m, 'out_top_up'].sum() / max(raw['out_top_up'].sum(), 1)})
    return out


def evaluate(extracts):
    """Score every snapshot and measure it: per taxpayer, per check, by band and at each line.
    Returns (measures per snapshot, hit rate by band); the lines are kept in evaluate.cuts."""
    rows, bands, cuts = [], [], []
    for snap, raw in extracts.items():
        raw = raw.reset_index(drop=True)
        s = M.score_snapshot(raw).scores.set_index('taxpayer_tin').reindex(raw['taxpayer_tin'])
        score, band = s['score'].to_numpy(), s['band'].to_numpy()
        chk = (raw['out_checked'] > 0).to_numpy()
        y = (raw['out_checked_hits'] > 0).to_numpy()[chk]
        sc, bd, top = score[chk], band[chk], top_mask(score, 0.05)[chk]
        t5, hi = _measures(y, top), _measures(y, np.isin(bd, ['HIGH', 'VERY HIGH']))
        rows.append({'Snapshot': snap, 'Taxpayers checked': int(chk.sum()),
                     'Per taxpayer: share with a top-up (base rate)': y.mean(),
                     'Per taxpayer: precision, top 5%': t5['precision'],
                     'Per taxpayer: recall, top 5%': t5['recall'],
                     'Per taxpayer: precision, HIGH and above': hi['precision'],
                     'Per taxpayer: recall, HIGH and above': hi['recall'],
                     'Per taxpayer: accuracy, HIGH and above': hi['accuracy'],
                     'Per taxpayer: accuracy, call everyone negative': 1 - y.mean(),
                     'Per taxpayer: ROC AUC': roc_auc_score(y, sc),
                     'Per taxpayer: average precision': average_precision_score(y, sc),
                     **per_check(raw, score)})
        cuts += [{'Snapshot': snap, **r} for r in cutoffs(raw, score, band)]
        for b in BANDS:
            m = bd == b
            bands.append({'Snapshot': snap, 'Band': b, 'Taxpayers checked': int(m.sum()),
                          'Share with a top-up': y[m].mean() if m.any() else np.nan})
    evaluate.cuts = pd.DataFrame(cuts)
    return pd.DataFrame(rows), pd.DataFrame(bands)


def run(long_run=False):
    """The six full extracts (CTRP_performance.xlsx), or with long_run=True the 18 dates since
    Sep 2017 built from the long run (CTRP_performance_since_2017.xlsx; earlier comparison sheets
    in that workbook are kept)."""
    if long_run:
        ex = {k.replace('lr_', ''): v for k, v in backtest_extracts('long_run/lr_20*.csv').items()}
        out = RESULTS_DIR / 'CTRP_performance_since_2017.xlsx'
    else:
        ex, out = backtest_extracts(), RESULTS_DIR / 'CTRP_performance.xlsx'
    keep = {}
    if long_run and out.exists():
        x = pd.ExcelFile(out)
        keep = {s: x.parse(s) for s in x.sheet_names if s.startswith(('Recency', 'Read me'))}
    table, bands = evaluate(ex)
    with pd.ExcelWriter(out) as w:
        for s, df in keep.items():
            df.to_excel(w, sheet_name=s, index=False)
        table.to_excel(w, sheet_name='Measures', index=False)
        hit_rate_by_band = bands.pivot(index='Band', columns='Snapshot', values='Share with a top-up').reindex(BANDS)
        hit_rate_by_band.to_excel(w, sheet_name='Hit rate by band')
        cuts = evaluate.cuts
        cuts.groupby('Line', sort=False).mean(numeric_only=True).to_excel(w, sheet_name='Lines (average)')
        cuts.to_excel(w, sheet_name='Lines (by snapshot)', index=False)
    return table, bands, out
