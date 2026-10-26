"""The candidate-parameter tools: the add-on query renders cleanly and the register is complete."""
from ctrp import addon, register


def test_addon_query_renders_for_every_year():
    for y in addon.YEARS:
        sql = addon.render(y)
        assert '@@' not in sql and ';' not in sql
        assert f"'{y - 1}0930'" in sql and f"'{y}0930'" in sql   # one year only, like a long-run piece
        assert sql.count('OVER (') == 3 and 'percentile' not in sql   # only the cleaning windows (R5, R14, R15)


def test_sensitive_list_is_the_cet_si_lines():
    assert len(addon.SENSITIVE_HS8) == 50 and all(len(c) == 8 for c in addon.SENSITIVE_HS8)


def test_register_rows_complete():
    statuses = {'Scored', 'Tested', 'Query written', 'Data request', 'Not for this score'}
    for row in register.REGISTER:
        assert len(row) == len(register.COLUMNS)
        assert any(row[3].startswith(s) for s in statuses), row[0]
    assert [r[0] for r in register.DATA_REQUEST] == list(range(1, len(register.DATA_REQUEST) + 1))


def test_entry_and_vehicle_switches():
    from ctrp import extract as E
    keep = (E.LATEST_DECLARATION_PER_ENTRY, E.EXCLUDE_MOTOR_VEHICLES)
    try:
        E.LATEST_DECLARATION_PER_ENTRY, E.EXCLUDE_MOTOR_VEHICLES = True, True
        sql = E.render('2026-03-31')[1]
        assert '-- R14 latest declaration ID per entry' in sql and '-- R15 no motor vehicle declarations' in sql
        assert "'8703'" in sql and '@@' not in sql
        E.LATEST_DECLARATION_PER_ENTRY, E.EXCLUDE_MOTOR_VEHICLES = False, False
        sql = E.render('2026-03-31')[1]
        assert '-- R14 latest declaration ID per entry' not in sql and '-- R15 no motor vehicle declarations' not in sql
    finally:
        E.LATEST_DECLARATION_PER_ENTRY, E.EXCLUDE_MOTOR_VEHICLES = keep


def test_issue_queries_render():
    from ctrp import issues as I
    for i in I.ISSUES:
        sql = I.render(i)
        assert ';' not in sql and 'entry_key' in sql
    assert ';' not in I.render_names()
