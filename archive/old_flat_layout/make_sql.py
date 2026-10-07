"""
Generate one Hue query per snapshot from templates/features_outcomes.sql.

    python make_sql.py

Writes sql/<name>.sql for each snapshot below. Paste each into Hue, run it, download the
result as CSV and save it as data/<name>.csv. The dates are worked out here so that no
one types them by hand.

Six back-test snapshots, six months apart, each with 24 months of history before it and
6 months of outcomes after it. The live snapshot has no outcome window yet.
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
BACKTEST_SNAPSHOTS = ['2023-09-30', '2024-03-31', '2024-09-30', '2025-03-31', '2025-09-30', '2026-03-31']
LIVE_SNAPSHOT = '2026-09-30'
HISTORY_MONTHS = 24
OUTCOME_MONTHS = 6
PRIOR_MONTHS = 36          # look-back used only to tell whether a taxpayer is new


def ymd(ts):
    """Date -> 'YYYYMMDD', the format of assessment_dt_wid in the view."""
    return ts.strftime('%Y%m%d')


def render(snap, live=False):
    """What: fill the template's @@...@@ placeholders for one snapshot.
    Why:  every extract uses identical SQL; only the dates change."""
    s = pd.Timestamp(snap)
    hist_start = s - pd.offsets.MonthEnd(HISTORY_MONTHS)
    prior_start = hist_start - pd.offsets.MonthEnd(PRIOR_MONTHS)
    out_end = s if live else s + pd.offsets.MonthEnd(OUTCOME_MONTHS)
    name = f"{'live' if live else 'bt'}_{snap}"
    sql = (HERE / 'templates' / 'features_outcomes.sql').read_text()
    for k, v in {'@@SNAP_DATE@@': snap, '@@SNAP@@': ymd(s), '@@HIST_START@@': ymd(hist_start),
                 '@@OUT_END@@': ymd(out_end), '@@PRIOR_START@@': ymd(prior_start), '@@FILE@@': name}.items():
        sql = sql.replace(k, v)
    return name, sql, hist_start.date(), out_end.date()


if __name__ == '__main__':
    out_dir = HERE / 'sql'
    out_dir.mkdir(exist_ok=True)
    (HERE / 'data').mkdir(exist_ok=True)
    jobs = [(s, False) for s in BACKTEST_SNAPSHOTS] + [(LIVE_SNAPSHOT, True)]
    for snap, live in jobs:
        name, sql, h, o = render(snap, live)
        (out_dir / f'{name}.sql').write_text(sql)
        print(f'sql/{name}.sql   history {h} to {snap}   outcomes to {o}')
    print(f'\nEarliest data needed: {render(BACKTEST_SNAPSHOTS[0])[2]}')
