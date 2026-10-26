"""What: checks the query dates and the download checks.  Why: a wrong date silently leaks the future."""
from ctrp import extract as E


def test_query_dates_and_placeholders():
    name, sql, hist_start, out_end = E.render('2026-03-31')
    assert name == 'bt_2026-03-31'
    assert str(hist_start) == '2024-03-31' and str(out_end) == '2026-09-30'
    assert '@@' not in sql


def test_live_query_has_no_outcome_window():
    name, sql, hist_start, out_end = E.render('2026-09-30', live=True)
    assert name == 'live_2026-09-30' and str(out_end) == '2026-09-30'


def test_a_clean_download_passes_every_check(tmp_path, extract):
    f = tmp_path / 'bt_2026-03-31.csv'
    extract.to_csv(f, index=False)
    assert E.check(str(f))['checks_failed'] == 0


def test_split_parts_cover_every_column_once():
    """The three part queries together give exactly the full query's columns, once each."""
    import re
    from ctrp import extract as E
    _, parts = E.render_split('2025-03-31')
    cols = []
    for k, q in parts.items():
        sel = q.rsplit('\nSELECT ', 1)[1].split('\nFROM ', 1)[0]
        names = [a for a, _ in E._select_items('SELECT ' + sel)]
        cols += names if k == 'core' else names[1:]
        assert ';' not in q
    assert sorted(cols) == sorted(E.full_columns()) and len(cols) == len(set(cols))
    # the extra parts stop their item scan at the snapshot date
    assert "<= '20250930'" not in parts['own_duty'] and "<= '20250930'" in parts['core']


def test_merge_rebuilds_full_extract(tmp_path, monkeypatch, extract):
    """Cutting a full extract into its parts and merging gives the same file back."""
    from ctrp import extract as E, utils as U
    full = extract.copy()
    for c in E.full_columns():
        if c not in full:
            full[c] = 'N' if c == 'new_trader' else 0.1
    full = full[E.full_columns()]
    (tmp_path / 'split').mkdir()
    for part, cols in E.split_columns().items():
        full[cols].to_csv(tmp_path / 'split' / f'{part}_bt_2025-03-31.csv', index=False)
    (tmp_path / 'bt_2025-03-31.csv').write_text('old')
    monkeypatch.setattr(U, 'DATA_DIR', tmp_path)
    E.merge_split()
    back = U.load_extract(tmp_path / 'bt_2025-03-31.csv')
    assert list(back.columns) == E.full_columns() and len(back) == len(full)
    assert (tmp_path / 'old' / 'bt_2025-03-31.csv').read_text() == 'old'


def test_history_since_2017_and_years_window():
    """18 back-test dates from Sep 2017; the yearly counts read 36 months, the features 24."""
    from ctrp import extract as E
    assert E.BACKTEST_SNAPSHOTS[0] == '2017-09-30' and E.BACKTEST_SNAPSHOTS[-1] == '2026-03-31'
    assert len(E.BACKTEST_SNAPSHOTS) == 18
    _, sql, _, _ = E.render('2017-09-30')
    assert "assessment_dt_wid >  '20140930'" in sql            # 36 months for the yearly counts
    assert "assessment_dt_wid > '20150930' AND" in sql          # 24 months for every other feature
    _, parts = E.render_split('2017-09-30')
    assert "'20140930'" in parts['years'] and "'20140930'" not in parts['core']


def test_years_part_is_added_to_an_existing_extract(tmp_path, monkeypatch, extract):
    from ctrp import extract as E, utils as U
    (tmp_path / 'split').mkdir()
    extract.to_csv(tmp_path / 'bt_2024-03-31.csv', index=False)
    y = extract[['taxpayer_tin']].copy()
    for c in E.split_columns()['years'][1:]:
        y[c] = 1
    y.to_csv(tmp_path / 'split' / 'years_bt_2024-03-31.csv', index=False)
    monkeypatch.setattr(U, 'DATA_DIR', tmp_path)
    E.merge_split()
    back = U.load_extract(tmp_path / 'bt_2024-03-31.csv')
    assert 'y3_entries' in back and len(back) == len(extract)
    assert (tmp_path / 'old' / 'bt_2024-03-31.csv').exists()


def test_hue_plan_runs_years_first_then_newest_dates(tmp_path, monkeypatch):
    from ctrp import extract as E
    plan = E.hue_plan()
    assert [p for _, _, p in plan[:6]] == [['years']] * 6
    assert plan[6][1] == '2022-09-30' and plan[-1][1] == '2018-03-31'
    monkeypatch.setattr(E, 'PLAN_DIR', tmp_path)
    assert E.write_hue_plan() == 66


def test_long_run_query_and_snapshot():
    """The long run fills every date, and a snapshot adds up the right half-years."""
    import pandas as pd
    from ctrp import longrun as L
    sql = L.render()
    assert '@@' not in sql and ';' not in sql and "'20140930'" in sql and 'GROUP BY tin, period_end' in sql
    p = pd.DataFrame({'taxpayer_tin': ['0000000001'] * 6,
                      'period_end': ['2023-09-30', '2024-03-31', '2024-09-30', '2025-03-31', '2025-09-30', '2023-03-31'],
                      'entries': [10, 10, 10, 10, 10, 10], 'items': 20, 'months_active': 6,
                      'customs_value_ugx': 100.0, 'original_tax_ugx': 10.0, 'top_up_ugx': [1.0, 0, 0, 2.0, 5.0, 0],
                      'topped_up': [1, 0, 0, 2, 3, 0], 'severe': 0, 'amended': 1, 'tax_reduced': 0, 'im7_entries': 0,
                      'checked': [2, 2, 2, 2, 4, 2], 'checked_hits': [0, 0, 0, 1, 3, 0], 'red': 1, 'yellow': 1,
                      'last_top_up_dt': ['20230901', None, None, '20250301', '20250901', None], 'first_dt': '20230101'})
    d = L.snapshot(p, '2025-03-31').iloc[0]
    assert d['entries_24m'] == 40 and d['top_up_entry_rate'] == 3 / 40       # Apr 2023 to Mar 2025
    assert d['out_checked'] == 4 and d['out_checked_hits'] == 3               # Apr to Sep 2025
    assert d['par105_days_since_last_top_up'] == 30
    assert d['y1_entries'] + d['y2_entries'] == d['entries_24m'] and d['y3_entries'] == 10


def test_long_run_refuses_a_download_hue_cut_off(tmp_path, monkeypatch):
    import pandas as pd, pytest
    from ctrp import longrun as L, utils as U
    (tmp_path / 'long_run').mkdir()
    pd.DataFrame({'taxpayer_tin': ['1'] * 10, 'period_end': ['2025-03-31'] * 10}).to_csv(
        tmp_path / 'long_run' / 'long_run_all.csv', index=False)
    monkeypatch.setattr(L, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(L, 'HUE_ROW_CAP', 10)
    with pytest.raises(SystemExit):
        L.load()
