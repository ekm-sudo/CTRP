"""Tests for Track B (discovery), the sensitivity check and the Zeppelin script."""
import copy

from tests.conftest import make_extract


def test_track_b_uses_no_customs_actions():
    """Track B must not see what customs did: no top-ups, no lanes (rule 1 in discovery.py)."""
    from ctrp import discovery as B
    X = B.build_features(make_extract(300))
    banned = ('top_up', 'red_lane', 'yellow_lane', 'negative', 'par077', 'par048', 'par105')
    assert not [c for c in X.columns if any(b in c for b in banned)]


def test_track_b_evaluates_both_segments():
    from ctrp import discovery as B
    snaps = ['2024-09-30', '2025-03-31', '2025-09-30', '2026-03-31']
    ex = {s: make_extract(3000, s, seed=i) for i, s in enumerate(snaps)}
    table, detail = B.evaluate(ex)
    assert set(table.index.get_level_values(0)) == {'regular', 'small'}
    assert detail['snapshot'].nunique() == 2                 # test_from=2: tests on the last two
    assert (table['group_size'] > 0).all()


def test_sensitivity_puts_settings_back():
    from ctrp import core as M, sensitivity as S
    before, k = copy.deepcopy(M.PARAMS), M.SHRINK_K
    with S.settings(k=40, scale={'PAR_045T': 0.5}, levels={'PAR_077': dict(one_at=0.9)}):
        assert M.SHRINK_K == 40
    assert M.PARAMS == before and M.SHRINK_K == k


def test_zeppelin_builds_items_once():
    """The main query must read the cached item table, not rebuild it from the view."""
    from ctrp import zeppelin as Z
    items_sql, main_sql = Z.split_main_template()
    assert 'ROW_NUMBER' in items_sql and 'ctrp_items' not in items_sql
    assert 'ctrp_items' in main_sql and 'ROW_NUMBER() OVER (PARTITION BY v.instance_id' not in main_sql


def test_apc_483_switch():
    from ctrp import extract as E
    keep = E.EXCLUDE_APC_483
    try:
        E.EXCLUDE_APC_483 = False
        assert "<> '483'" not in E.render('2026-03-31')[1]
        E.EXCLUDE_APC_483 = True
        assert "<> '483'" in E.render('2026-03-31')[1]
    finally:
        E.EXCLUDE_APC_483 = keep


def test_overall_band_takes_the_higher_track_but_discovery_caps_at_high():
    import pandas as pd
    from ctrp import report as R
    s = pd.DataFrame({'taxpayer_tin': list('abcd'), 'band': ['VERY LOW', 'MEDIUM', 'VERY HIGH', 'LOW']})
    tb = pd.DataFrame({'taxpayer_tin': list('abcd'), 'on_discovery_list': ['Y', 'Y', 'Y', 'N']})
    out = R.two_tracks(s, tb).set_index('taxpayer_tin')
    assert list(out['overall_band']) == ['HIGH', 'HIGH', 'VERY HIGH', 'LOW']
    assert out.at['a', 'driven_by'] == 'Trading behaviour' and out.at['c', 'driven_by'] == 'Compliance history'


def test_review_query_lists_the_sample(tmp_path, monkeypatch):
    import pandas as pd
    from ctrp import review
    wb = tmp_path / 'scores.xlsx'
    d = pd.DataFrame({'Segment': ['Regular', 'Small trader', 'Small trader'], 'TIN': ['0000000001', '0000000002', '0000000003'],
                      review.PCTL: [0.99, 0.98, 0.97], 'Behaviour reason 1': ['x'] * 3,
                      'Behaviour reason 2': [''] * 3, 'Snapshot': ['2026-09-30'] * 3})
    with pd.ExcelWriter(wb) as w:
        d.to_excel(w, sheet_name='Risky behaviour flags', index=False)
    monkeypatch.setattr(review, 'REVIEW_DIR', tmp_path / 'review')
    sql = review.write_review_sql(wb, regular=1, small=1).read_text()
    assert "'0000000001'" in sql and "'0000000002'" in sql and "'0000000003'" not in sql
    assert '@@' not in sql and ';' not in sql


def test_blind_review_mixes_flagged_and_comparison(tmp_path):
    import pandas as pd
    from ctrp import review
    from ctrp.report import PCTL
    from tests.conftest import make_extract
    raw = make_extract(400)
    raw['total_top_up'] = 0
    raw.to_csv(tmp_path / 'live.csv', index=False)
    tins = raw['taxpayer_tin'].tolist()
    flags = pd.DataFrame({'Segment': ['Regular'] * 10 + ['Small trader'] * 10, 'TIN': tins[:20],
                          PCTL: [0.99] * 20, 'Snapshot': ['2026-09-30'] * 20})
    scores = pd.DataFrame({'TIN': tins, 'Risky Behaviour Flag': ['Y'] * 20 + ['N'] * (len(tins) - 20),
                           'Limited history (under 10 declarations)': ['N', 'Y'] * (len(tins) // 2)})
    wb = tmp_path / 'wb.xlsx'
    with pd.ExcelWriter(wb) as w:
        flags.to_excel(w, sheet_name='Risky behaviour flags', index=False)
        scores.to_excel(w, sheet_name='Scores', index=False)
    k = review.pick_blind(wb, tmp_path / 'live.csv', n=6)
    assert (k['Group'] == 'Flagged').sum() == 6 and (k['Group'] == 'Comparison').sum() == 6
    assert k['TIN'].is_unique and list(k['Code'][:2]) == ['R01', 'R02']
    assert not set(k.loc[k.Group == 'Comparison', 'TIN']) & set(tins[:20])
