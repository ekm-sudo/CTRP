"""
Customs Taxpayer Risk Profiling Model (CTRP).

What: ranks every IM4 and IM7 taxpayer by compliance risk from their last 24 months of
      declarations: a score (0 to 100), a band, up to three reasons and notes.
Why:  officers cannot examine every importer; this gives them an ordered list with reasons,
      produced the same way for everyone.

Public API (what other code should use):

    import ctrp
    raw = ctrp.load_extract('data/live_2026-09-30.csv')
    result = ctrp.score_snapshot(raw)                   # scores, reasons, parameter values
    ctrp.write_workbook(result, 'results/CTRP_scores_2026-09-30.xlsx')
    lifts, by_band, base = ctrp.backtest(result, raw)   # only for extracts with outcomes

Modules
    core      THE MODEL: settings, the four layers, reasons, back-test
    utils     paths, reading an extract, lift and the other measures
    report    the officers' Excel workbook
    extract   the Hue queries and the checks on each download
    pipeline  score one file, back-test many
    models    challenger models and ensembles (experiments; never used for production scores)
"""
from ctrp.core import MODEL_VERSION as __version__
from ctrp.core import Result, backtest, config_fingerprint, derive, score_snapshot, set_profile
from ctrp.report import write_workbook
from ctrp.utils import lift, load_extract

__all__ = ['__version__', 'load_extract', 'derive', 'score_snapshot', 'Result', 'backtest', 'lift',
           'write_workbook', 'set_profile', 'config_fingerprint']
