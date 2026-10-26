"""
Shared helper utilities: where things live, reading an extract, and the measuring stick.

What: project paths; load_extract() for a Hue CSV; the measures every comparison uses
      (top_mask, hit_rate, lift, revenue_share, paired_diff_ci).
Why:  the model (core.py), the challengers, the pipeline, the notebook and the tests all use the
      same few helpers, so a ranking is always measured exactly the same way.
"""
from pathlib import Path

import numpy as np
import pandas as pd

# ---- where things live (the project folder is two levels above this file: src/ctrp/utils.py) ----
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / 'data'                 # CSVs downloaded from Hue (never committed)
RESULTS_DIR = PROJECT_ROOT / 'results'           # workbooks (never committed)
CHARTS_DIR = RESULTS_DIR / 'charts'              # every notebook chart as a PNG
SQL_DIR = PROJECT_ROOT / 'sql'                   # the generated Hue queries
TEMPLATE_SQL = Path(__file__).resolve().parent / 'sql' / 'features_outcomes.sql'


# =========================================================================================
# Reading extracts
# =========================================================================================
def load_extract(path):
    """What: read one Hue CSV.  Why: TINs must stay text (leading zeros) and appear once."""
    d = pd.read_csv(path, dtype={'taxpayer_tin': str})
    d.columns = [c.split('.')[-1].lower() for c in d.columns]      # Hue may prefix "table."
    if d['taxpayer_tin'].duplicated().any():
        raise ValueError(f'{path}: more than one row for some TINs')
    return d


def backtest_extracts(pattern='bt_*.csv'):
    """Every back-test extract in data/, as {snapshot date: DataFrame}, oldest first."""
    files = sorted(DATA_DIR.glob(pattern))
    if not files:
        raise SystemExit(f'No back-test files matching data/{pattern}. Run the queries in sql/ first.')
    return {f.stem.replace('bt_', ''): load_extract(f) for f in files}


# =========================================================================================
# The measuring stick
# Lift = hit rate of the taxpayers a ranking puts in its top group, divided by the hit rate of
# everyone. 1.0 means no better than picking at random; 4.0 means four times as many hits per
# check. Always read it together with hits caught and revenue caught (DECISIONS 48).
# =========================================================================================
def top_mask(score, share):
    """True for the top `share` of taxpayers by score (ties broken by position, so exactly k)."""
    score = pd.Series(np.asarray(score, dtype=float))
    k = max(1, int(round(share * len(score))))
    return score.rank(ascending=False, method='first').to_numpy() <= k


def hit_rate(frame):
    """Hits divided by checked (red or yellow lane) declarations in the outcome window."""
    return frame['out_checked_hits'].sum() / max(frame['out_checked'].sum(), 1)


def lift(raw, score, share):
    """Hit rate of the top `share` by score divided by everyone's hit rate."""
    return hit_rate(raw[top_mask(score, share)]) / hit_rate(raw)


def revenue_share(raw, score, share):
    """Share of all top-up revenue in the outcome window that the top `share` accounts for."""
    return raw.loc[top_mask(score, share), 'out_top_up'].sum() / max(raw['out_top_up'].sum(), 1)


def paired_diff_ci(raw, a, b, share=0.05, reps=300, seed=42):
    """What: 90% interval for (lift of a) minus (lift of b), resampling taxpayers with replacement.
    Why:  a difference only counts if it is bigger than what chance alone would produce.
    (seed 42 = the model's SEED, so the interval is the same every run)"""
    rng = np.random.default_rng(seed)
    raw = raw.reset_index(drop=True)
    a, b = pd.Series(np.asarray(a, dtype=float)), pd.Series(np.asarray(b, dtype=float))
    n = len(raw)
    out = []
    for _ in range(reps):
        i = rng.integers(0, n, n)                      # one resample of the taxpayers
        raw_i = raw.iloc[i].reset_index(drop=True)
        a_i, b_i = a.iloc[i].reset_index(drop=True), b.iloc[i].reset_index(drop=True)
        out.append(lift(raw_i, a_i, share) - lift(raw_i, b_i, share))
    return np.percentile(out, [5, 95])
