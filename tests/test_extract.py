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
    """Cutting a full extract into its three parts and merging gives the same file back."""
    from ctrp import extract as E, utils as U
    full = extract.copy()
    for c in E.full_columns():
        if c not in full:
            full[c] = 'N' if c == 'new_trader' else 0.1
    full = full[E.full_columns()]
    (tmp_path / 'split').mkdir()
    own = ['taxpayer_tin', 'hs_codes_compared', 'own_price_drop_share', 'low_duty_value_share', 'duty_gap_share',
           'exemption_apc_value_share', 'watchlist_apc_value_share', 'watchlist_apcs_used']
    spl = ['taxpayer_tin', 'same_day_split_share', 'same_day_split_expected', 'same_day_split_excess',
           'max_same_day_same_hs', 'new_trader']
    core = [c for c in full if c not in own[1:] + spl[1:]]
    full[core].to_csv(tmp_path / 'split' / 'core_bt_2025-03-31.csv', index=False)
    full[own].to_csv(tmp_path / 'split' / 'own_duty_bt_2025-03-31.csv', index=False)
    full[spl].to_csv(tmp_path / 'split' / 'split_new_bt_2025-03-31.csv', index=False)
    (tmp_path / 'bt_2025-03-31.csv').write_text('old')
    monkeypatch.setattr(U, 'DATA_DIR', tmp_path)
    E.merge_split()
    back = U.load_extract(tmp_path / 'bt_2025-03-31.csv')
    assert list(back.columns) == E.full_columns() and len(back) == len(full)
    assert (tmp_path / 'old' / 'bt_2025-03-31.csv').read_text() == 'old'
