"""
The end-to-end runs: score one extract, back-test many.

What: the two production-shaped runs, wired from the pieces in core.py and report.py.
Why:  main.py, the notebook and any future scheduler call the same functions, so they always agree.
"""
import pandas as pd

from ctrp import core as M
from ctrp import report as R
from ctrp.utils import RESULTS_DIR, backtest_extracts, load_extract


def score_file(path):
    """What: score one extract and write the officers' workbook plus a CSV copy.
    Why:  this is the production run: one file in, one fixed-layout workbook out."""
    raw = load_extract(path)
    res = M.score_snapshot(raw)
    RESULTS_DIR.mkdir(exist_ok=True)
    xlsx = RESULTS_DIR / f'CTRP_scores_{res.snapshot}.xlsx'
    R.write_workbook(res, xlsx, source_file=str(path))
    res.scores.to_csv(RESULTS_DIR / f'CTRP_scores_{res.snapshot}.csv', index=False)
    print('\n'.join(res.log))
    print(res.scores['band'].value_counts().reindex([b for _, b in M.BANDS]).fillna(0).astype(int).to_string())
    print(f'written {xlsx}  (model {res.version}, settings {res.fingerprint})')
    return res


def backtest_files(pattern='bt_*.csv'):
    """What: score every back-test extract and compare with what happened next.
    Why:  shows whether the model beats ranking on past top-ups alone, snapshot by snapshot."""
    lifts, bands = [], []
    for snap, raw in backtest_extracts(pattern).items():
        res = M.score_snapshot(raw)
        lt, bb, _ = M.backtest(res, raw)
        lifts.append(lt)
        bands.append(bb)
        print(f'{snap}: done')
    lifts, bands = pd.concat(lifts), pd.concat(bands)
    piv = lifts.pivot_table(index=['top_share', 'ranked_by'], columns='snapshot', values='hit_lift')
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / 'CTRP_backtest.xlsx'
    with pd.ExcelWriter(out, engine='xlsxwriter') as w:
        piv.round(2).to_excel(w, sheet_name='Lift by snapshot')
        lifts.to_excel(w, sheet_name='Lift detail', index=False)
        bands.to_excel(w, sheet_name='Hit rate by band', index=False)
    print('\nHIT-RATE LIFT (1.0 = no better than everyone)\n' + piv.round(2).to_string())
    print(f'written {out}')
    return lifts, bands
