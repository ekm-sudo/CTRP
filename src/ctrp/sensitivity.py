"""
Sensitivity check: does the Track A ranking hold when its settings move?

What: re-scores every back-test snapshot with one setting changed at a time (credibility weight,
      each weight, the minimum risk and maximum levels) and compares with the adopted settings:
      lift, hits and top-up money in the top 5%, and how many of the same taxpayers stay on top.
Why:  the settings were chosen by experts and tested on a few snapshots. A model worth trusting
      ranks almost the same taxpayers when a setting moves a reasonable amount; a model whose
      list changes a lot is resting on that one choice, and the choice needs defending.

    python main.py sensitivity        -> results/CTRP_sensitivity.xlsx
"""
import copy
from contextlib import contextmanager

import pandas as pd
from scipy import stats

from ctrp import core as M
from ctrp.utils import lift, revenue_share, top_mask

TOP = 0.05
MAIN3 = ['PAR_045T', 'PAR_077', 'PAR_045']
SMALL5 = ['PAR_048', 'PAR_076', 'PAR_066', 'PAR_105', 'PAR_023']


@contextmanager
def settings(k=None, scale=None, levels=None):
    """Temporarily change the model settings, then put them back exactly.
    k:      credibility weight K (0 = no weighting)
    scale:  {code: multiplier on its weight}
    levels: {code: dict(zero_at=..., one_at=...)}"""
    keep_params, keep_k = copy.deepcopy(M.PARAMS), M.SHRINK_K
    try:
        if k is not None:
            M.SHRINK_K = k or None
        for p in M.PARAMS:
            if scale and p['code'] in scale:
                p['I'] = p['I'] * scale[p['code']]
            if levels and p['code'] in levels:
                p.update(levels[p['code']])
        yield
    finally:
        M.PARAMS[:] = keep_params
        M.SHRINK_K = keep_k


def score(raw):
    """The Track A scorecard points of every taxpayer, with the settings in force now."""
    return M.layer2_scorecard(M.derive(raw))[0].sum(axis=1)


def variants():
    """The settings tried: (group, label, kwargs for settings())."""
    v = [('Adopted', 'Adopted settings', {})]
    for k in (0, 5, 20, 40):
        v.append(('Credibility weight', f'K = {k}' + (' (no weighting)' if k == 0 else ''), dict(k=k)))
    for code in MAIN3:
        for f in (0.5, 1.5):
            v.append(('Weights', f'{code} weight x{f}', dict(scale={code: f})))
    v.append(('Weights', 'Small five weights x0 (dropped)', dict(scale={c: 0 for c in SMALL5})))
    v.append(('Weights', 'Small five weights x2', dict(scale={c: 2 for c in SMALL5})))
    v.append(('Weights', 'All eight equal', dict(scale={p['code']: 1 / (p['L'] * p['I']) for p in M.PARAMS})))
    rate_params = [p for p in M.PARAMS if p['fmt'] == 'pct']        # PAR_105 (yes or no) has no levels to move
    for f in (0.5, 1.5):
        v.append(('Minimum risk levels', f'All minimum risk levels x{f}',
                  dict(levels={p['code']: dict(zero_at=p['zero_at'] * f) for p in rate_params})))
    for f in (0.75, 1.25):
        v.append(('Maximum levels', f'All maximum levels x{f}',
                  dict(levels={p['code']: dict(one_at=min(p['one_at'] * f, 1.0)) for p in rate_params})))
    for one in (0.10, 0.25, 0.60):
        v.append(('Maximum levels', f'PAR_045T maximum {one:.0%}', dict(levels={'PAR_045T': dict(one_at=one)})))
    return v


def run(extracts):
    """Every variant on every snapshot, against the adopted settings. Returns (average table, detail)."""
    base = {s: score(r.reset_index(drop=True)) for s, r in extracts.items()}
    rows = []
    for group, label, kw in variants():
        with settings(**kw):
            for s, raw in extracts.items():
                raw = raw.reset_index(drop=True)
                sc = score(raw) if kw else base[s]
                top, btop = top_mask(sc, TOP), top_mask(base[s], TOP)
                t = raw[top]
                rows.append(dict(group=group, setting=label, snapshot=s,
                                 lift_top5=lift(raw, sc, TOP),
                                 hits_top5=int(t['out_checked_hits'].sum()),
                                 revenue_top5=revenue_share(raw, sc, TOP),
                                 same_top5_taxpayers=(top & btop).sum() / btop.sum(),
                                 rank_correlation=stats.spearmanr(sc, base[s]).statistic))
    detail = pd.DataFrame(rows)
    table = detail.groupby(['group', 'setting'], sort=False)[
        ['lift_top5', 'hits_top5', 'revenue_top5', 'same_top5_taxpayers', 'rank_correlation']].mean()
    adopted = table.loc[('Adopted', 'Adopted settings')]
    table['lift_change'] = table['lift_top5'] - adopted['lift_top5']
    table['hits_change_pct'] = table['hits_top5'] / adopted['hits_top5'] - 1
    return table, detail
