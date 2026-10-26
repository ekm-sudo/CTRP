"""
Score from the command line, the way production will run it.

    python run_scoring.py data/live_2026-09-30.csv
        -> results/CTRP_scores_2026-09-30.xlsx   (the officers' workbook)
        -> results/CTRP_scores_2026-09-30.csv    (same scores, for loading elsewhere)

    python run_scoring.py --backtest "data/bt_*.csv"
        -> results/CTRP_backtest.xlsx            (lift by snapshot, hit rate by band)

The notebook calls exactly the same functions, so its numbers and these always agree.
"""
import argparse
import glob
from pathlib import Path

import pandas as pd

import ctrp_model as M
import ctrp_report as R

RESULTS = Path('results')


def score_one(path):
    """What: score one extract and write the officers' workbook plus a CSV copy.
    Why:  this is the production run: one file in, one fixed-layout workbook out."""
    raw = M.load_extract(path)
    res = M.score_snapshot(raw)
    RESULTS.mkdir(exist_ok=True)
    xlsx = RESULTS / f'CTRP_scores_{res.snapshot}.xlsx'
    R.write_workbook(res, xlsx, source_file=str(path))
    res.scores.to_csv(RESULTS / f'CTRP_scores_{res.snapshot}.csv', index=False)
    print('\n'.join(res.log))
    print(res.scores['band'].value_counts().reindex([b for _, b in M.BANDS]).fillna(0).astype(int).to_string())
    print(f'written {xlsx}  (model {res.version}, settings {res.fingerprint})')
    return raw, res


def backtest(paths):
    """What: score every back-test extract and compare with what happened next.
    Why:  shows whether the model beats ranking on past top-ups alone, snapshot by snapshot."""
    lifts, bands = [], []
    for p in paths:
        raw = M.load_extract(p)
        res = M.score_snapshot(raw)
        lt, bb, _ = M.backtest(res, raw)
        lifts.append(lt)
        bands.append(bb)
        print(f'{res.snapshot}: done')
    lifts, bands = pd.concat(lifts), pd.concat(bands)
    piv = lifts.pivot_table(index=['top_share', 'ranked_by'], columns='snapshot', values='hit_lift')
    RESULTS.mkdir(exist_ok=True)
    with pd.ExcelWriter(RESULTS / 'CTRP_backtest.xlsx', engine='xlsxwriter') as w:
        piv.round(2).to_excel(w, sheet_name='Lift by snapshot')
        lifts.to_excel(w, sheet_name='Lift detail', index=False)
        bands.to_excel(w, sheet_name='Hit rate by band', index=False)
    print('\nHIT-RATE LIFT (1.0 = no better than everyone)\n' + piv.round(2).to_string())
    print(f'written {RESULTS / "CTRP_backtest.xlsx"}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('file', nargs='?', help='one extract to score')
    ap.add_argument('--backtest', help='wildcard for the back-test extracts, e.g. "data/bt_*.csv"')
    a = ap.parse_args()
    if a.backtest:
        backtest(sorted(glob.glob(a.backtest)))
    elif a.file:
        score_one(a.file)
    else:
        ap.print_help()
