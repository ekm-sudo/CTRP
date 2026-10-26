"""What: checks the rules of the model itself.
Why:  if one of these fails after a change, the change broke a promise the model makes."""
import numpy as np
import pandas as pd
import pytest

from ctrp import core as M


def test_scale_is_zero_below_concern_and_one_at_maximum():
    x = pd.Series([0.0, 0.03, 0.215, 0.40, 0.9])
    s = M.scale(x, 0.03, 0.40)
    assert list(s.round(3)) == [0.0, 0.0, 0.5, 1.0, 1.0]


@pytest.mark.parametrize('score,band', [(0, 'VERY LOW'), (15, 'VERY LOW'), (16, 'LOW'), (35, 'LOW'),
                                        (36, 'MEDIUM'), (51, 'HIGH'), (80, 'HIGH'), (81, 'VERY HIGH')])
def test_band_edges(score, band):
    assert M.band_of(score) == band


def test_small_count_weighting_only_lowers_and_keeps_the_raw_value(extract):
    d = M.derive(extract)
    for p in M.PARAMS:
        raw, w = d[p['col'] + '_raw'], d[p['col']]
        ok = raw.notna()
        assert (w[ok] <= raw[ok] + 1e-12).all(), p['code']


def test_weights_add_to_100_and_missing_parameters_are_reweighted(extract):
    d = M.derive(extract)
    d.loc[d.index[:10], 'par076_shortfall_share'] = np.nan
    _, available, weights = M.layer2_scorecard(d)
    assert weights.sum(axis=1).round(0).eq(100).all()
    assert not available.loc[d.index[:10], 'PAR_076'].any()


def test_scoring_is_repeatable_and_complete(extract):
    a, b = M.score_snapshot(extract), M.score_snapshot(extract)
    pd.testing.assert_frame_equal(a.scores, b.scores)
    s = a.scores
    assert len(s) == len(extract) and list(s['rank']) == list(range(1, len(s) + 1))
    assert s['score'].between(0, 100).all()
    assert (s['band'] == s['score'].map(M.band_of)).all()


def test_pattern_check_adds_no_points(extract):
    s = M.score_snapshot(extract).scores
    assert (s['score'] == s['scorecard_points'].round().clip(0, 100).astype(int)).all()
    assert set(s['flag_unusual_pattern']) <= {'Y', 'N'}


def test_every_reason_belongs_to_a_parameter_with_points(extract):
    r = M.score_snapshot(extract)
    assert (r.reasons['points'] > 0).all()
    assert set(r.reasons['code']) <= {p['code'] for p in M.PARAMS}


def test_fingerprint_changes_when_a_setting_changes():
    before = M.config_fingerprint()
    M.set_profile('officers_andrew')
    try:
        assert M.config_fingerprint() != before
    finally:
        M.set_profile('adopted')
    assert M.config_fingerprint() == before


def test_backtest_returns_lift_for_model_and_baseline(extract):
    r = M.score_snapshot(extract)
    lt, bands, base = M.backtest(r, extract)
    assert set(lt['ranked_by']) == {'Model', 'Past top-ups only'}
    assert lt['hit_lift'].notna().all()


def test_recency_weights_rebuild_rates_from_yearly_counts():
    import pandas as pd
    from ctrp import core as M
    d = pd.DataFrame({'top_up_entry_rate': [0.5], 'par077_severe_top_up_rate': [0.0], 'par045_amended_entry_rate': [0.0],
                      'par066_negative_top_up_rate': [0.0], 'total_top_up': [1.0], 'total_original_tax': [10.0],
                      'par048_top_up_ratio': [0.1]})
    for k, (n, t) in zip((1, 2, 3), [(10, 0), (10, 10), (10, 10)]):
        d[f'y{k}_entries'], d[f'y{k}_topped_up'] = n, t
        for c in ['severe', 'amended', 'tax_reduced', 'top_up_ugx']:
            d[f'y{k}_{c}'] = 0
        d[f'y{k}_original_tax_ugx'] = 10.0
    out = M.apply_recency(d)
    assert abs(out['top_up_entry_rate'][0] - (0.5 * 10 + 0.25 * 10) / (17.5)) < 1e-12   # recent clean year counts most
    assert bool(out['recency_applied'][0])
    assert not M.apply_recency(d.drop(columns=['y3_entries']))['recency_applied'].any()   # no counts: 24-month rates kept
