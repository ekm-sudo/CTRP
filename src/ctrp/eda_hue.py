"""
The EDA report through Hue, for as long as Zeppelin cannot read the view.

What: six small Hue queries (sql/eda_report/) that give the same EDA numbers as Parts 2 and 3 of the Zeppelin
      note: missing data per column and per year, the test of "blank original tax = unchanged", the duplicates at
      every level, the copies of an item against the inspection actions on its declaration, and the cleaning log.
      Each returns a few rows only. Then build() turns the downloads into one workbook.
Why:  Zeppelin runs as your own user, which has no SELECT right on the view; Hue does. The officer workbooks
      (sql/eda_issues/) and the final dataset (eda-excel --from-extract) already come from Hue downloads.
Window: IM4 and IM7 in the 24 months before the live snapshot, as in the note (the cleaning log uses the
      36 months the features need, all regimes, so it can show what each rule removes).

    python main.py eda-report --sql    -> sql/eda_report/Q1_missing_by_column.sql ... Q6_cleaning_log.sql
    python main.py eda-report          -> results/CTRP_EDA_report_<date>.xlsx from data/eda_report/Q1.csv ... Q6.csv
"""
import pandas as pd

from ctrp import eda_note as N
from ctrp import issues as I
from ctrp import extract as E
from ctrp.issues import HDR, INSP, ITM
from ctrp.utils import DATA_DIR, RESULTS_DIR, SQL_DIR

OUT_SQL = SQL_DIR / 'eda_report'
DATA = DATA_DIR / 'eda_report'
VIEW = 'dm_modeled_ura_datascience.vw_cstm_AEO_model'

_snap = pd.Timestamp(E.LIVE_SNAPSHOT)
SNAP = E.ymd(_snap)
HIST_START = E.ymd(_snap - pd.offsets.MonthEnd(24))
HIST3_START = E.ymd(_snap - pd.offsets.MonthEnd(36))
WINDOW_24M = (f"assessment_dt_wid > '{HIST_START}' AND assessment_dt_wid <= '{SNAP}'"
              " AND regime_cd IN ('IM4', 'IM7')")
ENTRY_KEY = 'COALESCE(concat(entry_num, clearance_station_cd, dec_ref_yer), instance_id)'

TEXT = ['instance_id', 'entry_num', 'dec_ref_yer', 'clearance_station_cd', 'taxpayer_tin', 'taxpayer_nm',
        'consignee_tin', 'hsc_cd', 'gds_org_cty', 'cpc_cd', 'extended_proc_cd', 'decl_status', 'pay_status',
        'key_itm_nbr', 'top_up_flg', 'amendment_flg', 'preferential_treatment_flag', 'assessment_dt_wid']
NUMBERS = ['customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt', 'final_amt',
           'top_up_amt']
LANES = ['is_red_flg', 'is_yellow_flg']
BY_YEAR = ['original_tax_amt', 'hsc_cd', 'gds_org_cty', 'supplementary_qnty', 'net_weight', 'tax_assessed',
           'cpc_cd', 'entry_num', 'decl_status', 'clearance_station_cd']


def _blank(c):
    return f"AVG(CASE WHEN {c} IS NULL THEN 1D ELSE 0D END) AS blank_{c}"


def q_missing_by_column():
    cols = [_blank(c) for c in TEXT + NUMBERS + LANES]
    cols += [f"AVG(CASE WHEN {c} <= 0 THEN 1D WHEN {c} IS NULL THEN NULL ELSE 0D END) AS zero_or_less_{c}"
             for c in NUMBERS]
    return ('SELECT COUNT(*) AS item_rows,\n       ' + ',\n       '.join(cols) +
            f'\nFROM {VIEW}\nWHERE {WINDOW_24M}\n')


def q_missing_by_year():
    cols = [_blank(c) for c in BY_YEAR]
    return ('SELECT substr(assessment_dt_wid, 1, 4) AS year, COUNT(*) AS item_rows,\n       ' + ',\n       '.join(cols) +
            f'\nFROM {VIEW}\nWHERE {WINDOW_24M}\nGROUP BY substr(assessment_dt_wid, 1, 4)\nORDER BY year\n')


def q_original_tax_test():
    return ("SELECT COALESCE(flag, 'blank') AS top_up_flag, COUNT(*) AS declarations,\n"
            "       AVG(CASE WHEN original_tax IS NULL THEN 1D ELSE 0D END) AS original_tax_blank\n"
            "FROM (SELECT instance_id, MAX(top_up_flg) AS flag, MAX(original_tax_amt) AS original_tax\n"
            f"      FROM {VIEW}\n      WHERE {WINDOW_24M}\n      GROUP BY instance_id) d\n"
            "GROUP BY COALESCE(flag, 'blank')\n")


def q_duplicates():
    cols = ', '.join(c for c in I.DETAIL if c != 'entry_key')
    return (f"WITH base AS (SELECT {ENTRY_KEY} AS entry_key, {cols}\n"
            f"              FROM {VIEW} WHERE {WINDOW_24M}),\n"
            "copies AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies FROM base GROUP BY instance_id, key_itm_nbr),\n"
            "versions AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS versions\n"
            "             FROM (SELECT DISTINCT * FROM base) d GROUP BY instance_id, key_itm_nbr),\n"
            "per_entry AS (SELECT entry_key, COUNT(DISTINCT instance_id) AS ids FROM base GROUP BY entry_key),\n"
            "per_id AS (SELECT instance_id, COUNT(DISTINCT taxpayer_tin) AS tins,\n"
            "                  COUNT(DISTINCT assessment_dt_wid) AS dates FROM base GROUP BY instance_id)\n"
            "SELECT (SELECT SUM(copies) FROM copies) AS item_rows,\n"
            "       (SELECT SUM(versions) FROM versions) AS different_rows,\n"
            "       (SELECT COUNT(*) FROM copies) AS items,\n"
            "       (SELECT SUM(CASE WHEN versions > 1 THEN 1 ELSE 0 END) FROM versions) AS items_with_copies_not_identical,\n"
            "       (SELECT MAX(copies) FROM copies) AS most_copies_of_one_item,\n"
            "       (SELECT SUM(CASE WHEN ids > 1 THEN 1 ELSE 0 END) FROM per_entry) AS entries_under_several_ids,\n"
            "       (SELECT SUM(CASE WHEN tins > 1 THEN 1 ELSE 0 END) FROM per_id) AS ids_with_several_tins,\n"
            "       (SELECT SUM(CASE WHEN dates > 1 THEN 1 ELSE 0 END) FROM per_id) AS ids_with_several_dates\n")


def q_copies_vs_inspections():
    return (f"WITH v AS (SELECT instance_id, key_itm_nbr, sad_sid, op_date_time, inf FROM {VIEW} WHERE {WINDOW_24M}),\n"
            "actions AS (SELECT instance_id, size(collect_set(struct(sad_sid, op_date_time, inf))) AS inspection_actions\n"
            "            FROM v WHERE sad_sid IS NOT NULL OR op_date_time IS NOT NULL OR inf IS NOT NULL\n"
            "            GROUP BY instance_id),\n"
            "items AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies FROM v GROUP BY instance_id, key_itm_nbr)\n"
            "SELECT COUNT(*) AS repeated_items,\n"
            "       SUM(CASE WHEN i.copies = GREATEST(COALESCE(a.inspection_actions, 0), 1) THEN 1 ELSE 0 END)\n"
            "           AS copies_equal_inspection_actions,\n"
            "       MAX(i.copies) AS most_copies\n"
            "FROM items i LEFT JOIN actions a ON i.instance_id = a.instance_id\n"
            "WHERE i.copies > 1\n")


def q_cleaning_log():
    mv = ', '.join(f"'{h}'" for h in E.MOTOR_VEHICLE_HEADINGS)
    return (f"WITH v AS (SELECT instance_id, key_itm_nbr, assessment_dt_wid, taxpayer_tin, decl_status, regime_cd,\n"
            f"                  cpc_cd, hsc_cd, {ENTRY_KEY} AS entry_key\n"
            f"           FROM {VIEW}\n"
            f"           WHERE assessment_dt_wid > '{HIST3_START}' AND assessment_dt_wid <= '{SNAP}'),\n"
            "s1 AS (SELECT *, COALESCE(taxpayer_tin RLIKE '^[0-9]{10}$', false) AS r1,\n"
            "              COALESCE(decl_status <> 'Cancelled', false) AS r3,\n"
            "              COALESCE(regime_cd IN ('IM4', 'IM7'), false) AS r4,\n"
            "              COALESCE(COALESCE(cpc_cd, '') <> '483', false) AS r13\n"
            "       FROM v),\n"
            "s2 AS (SELECT COALESCE(lpad(instance_id, 20, '0') =\n"
            "                MAX(lpad(instance_id, 20, '0')) OVER (PARTITION BY entry_key), false) AS r14,\n"
            f"              MAX(CASE WHEN substr(hsc_cd, 1, 4) IN ({mv}) THEN 1 ELSE 0 END)\n"
            "                OVER (PARTITION BY instance_id) = 0 AS r15,\n"
            "              ROW_NUMBER() OVER (PARTITION BY instance_id, key_itm_nbr ORDER BY assessment_dt_wid) = 1 AS r5\n"
            "       FROM s1 WHERE r1 AND r3 AND r4 AND r13)\n"
            "SELECT stack(5, 'rows loaded', n, 'R1', a, 'R3', b, 'R4', c, 'R13', d) AS (step, rows_removed)\n"
            "FROM (SELECT COUNT(*) AS n,\n"
            "             SUM(CASE WHEN NOT r1 THEN 1 ELSE 0 END) AS a,\n"
            "             SUM(CASE WHEN r1 AND NOT r3 THEN 1 ELSE 0 END) AS b,\n"
            "             SUM(CASE WHEN r1 AND r3 AND NOT r4 THEN 1 ELSE 0 END) AS c,\n"
            "             SUM(CASE WHEN r1 AND r3 AND r4 AND NOT r13 THEN 1 ELSE 0 END) AS d FROM s1) x\n"
            "UNION ALL\n"
            "SELECT stack(4, 'R14', e, 'R15', f, 'R5', g, 'rows left', h) AS (step, rows_removed)\n"
            "FROM (SELECT SUM(CASE WHEN NOT r14 THEN 1 ELSE 0 END) AS e,\n"
            "             SUM(CASE WHEN r14 AND NOT r15 THEN 1 ELSE 0 END) AS f,\n"
            "             SUM(CASE WHEN r14 AND r15 AND NOT r5 THEN 1 ELSE 0 END) AS g,\n"
            "             SUM(CASE WHEN r14 AND r15 AND r5 THEN 1 ELSE 0 END) AS h FROM s2) y\n")


def q_copies_source():
    """Which of the view's three tables repeats the item. The view joins the declaration header, the item table
    and the inspection actions on the declaration ID only, so an item's copies in the view are exactly
    header rows x item rows x inspection rows (at least 1) for that declaration and item."""
    mv = ', '.join(f"'{h}'" for h in E.MOTOR_VEHICLE_HEADINGS)
    return (f"WITH v AS (SELECT instance_id, key_itm_nbr, hsc_cd, regime_cd FROM {VIEW} WHERE {WINDOW_24M}),\n"
            "rep AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies FROM v\n"
            "        GROUP BY instance_id, key_itm_nbr HAVING COUNT(*) > 1),\n"
            "ids AS (SELECT DISTINCT instance_id FROM rep),\n"
            f"veh AS (SELECT instance_id, MAX(CASE WHEN substr(hsc_cd, 1, 4) IN ({mv}) THEN 1 ELSE 0 END) AS has_vehicle,\n"
            "               MAX(regime_cd) AS regime\n"
            "        FROM v WHERE instance_id IN (SELECT instance_id FROM ids) GROUP BY instance_id),\n"
            f"hdr AS (SELECT instance_id, COUNT(*) AS n FROM {HDR} WHERE instance_id IN (SELECT instance_id FROM ids)\n"
            "        GROUP BY instance_id),\n"
            f"itm AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS n FROM {ITM}\n"
            "        WHERE instance_id IN (SELECT instance_id FROM ids) GROUP BY instance_id, key_itm_nbr),\n"
            f"insp AS (SELECT instance_id, COUNT(*) AS n FROM {INSP} WHERE instance_id IN (SELECT instance_id FROM ids)\n"
            "         GROUP BY instance_id)\n"
            "SELECT COUNT(*) AS repeated_items,\n"
            "       SUM(CASE WHEN r.copies = COALESCE(h.n, 1) * COALESCE(t.n, 1) * GREATEST(COALESCE(a.n, 0), 1)\n"
            "                THEN 1 ELSE 0 END) AS copies_explained_by_the_three_tables,\n"
            "       SUM(CASE WHEN h.n > 1 THEN 1 ELSE 0 END) AS items_whose_header_repeats,\n"
            "       SUM(CASE WHEN t.n > 1 THEN 1 ELSE 0 END) AS items_whose_item_row_repeats,\n"
            "       SUM(CASE WHEN a.n > 1 THEN 1 ELSE 0 END) AS items_with_several_inspection_rows,\n"
            "       MAX(h.n) AS most_header_rows, MAX(t.n) AS most_item_rows, MAX(a.n) AS most_inspection_rows,\n"
            "       SUM(CASE WHEN x.has_vehicle = 1 THEN 1 ELSE 0 END) AS items_on_vehicle_declarations,\n"
            "       SUM(CASE WHEN x.regime = 'IM7' THEN 1 ELSE 0 END) AS items_on_im7_declarations\n"
            "FROM rep r\n"
            "LEFT JOIN hdr h ON r.instance_id = h.instance_id\n"
            "LEFT JOIN itm t ON r.instance_id = t.instance_id AND r.key_itm_nbr = t.key_itm_nbr\n"
            "LEFT JOIN insp a ON r.instance_id = a.instance_id\n"
            "LEFT JOIN veh x ON r.instance_id = x.instance_id\n")


def q_lanes():
    """Lane flags per declaration, blanks included: half the rows have a blank red flag, so what does blank mean?"""
    return ("SELECT red, yellow, green, blue, COUNT(*) AS declarations\n"
            "FROM (SELECT instance_id, MAX(is_red_flg) AS red, MAX(is_yellow_flg) AS yellow,\n"
            "             MAX(is_green_flg) AS green, MAX(is_blue_flg) AS blue\n"
            f"      FROM {VIEW} WHERE {WINDOW_24M} GROUP BY instance_id) d\n"
            "GROUP BY red, yellow, green, blue\n"
            "ORDER BY declarations DESC\n")


QUERIES = [
    ('Q1', 'missing_by_column', 'Missing data: blank share of every column, zero-or-less share of every number',
     q_missing_by_column),
    ('Q2', 'missing_by_year', 'Missing data per year, for the columns the model leans on', q_missing_by_year),
    ('Q3', 'original_tax_test', 'Test of "blank original tax means unchanged" (by top-up flag)', q_original_tax_test),
    ('Q4', 'duplicates', 'Duplicates at every level', q_duplicates),
    ('Q5', 'copies_vs_inspections', 'Copies of an item against the inspection actions on its declaration',
     q_copies_vs_inspections),
    ('Q6', 'cleaning_log', 'Rows removed by each cleaning rule (36 months, all regimes)', q_cleaning_log),
    ('Q7', 'copies_source', 'Which table repeats the item: header, item or inspection rows', q_copies_source),
    ('Q8', 'lanes', 'Lane flags per declaration, blanks included', q_lanes),
]


def write_queries():
    OUT_SQL.mkdir(parents=True, exist_ok=True)
    for code, slug, title, build in QUERIES:
        sql = (f'-- CTRP EDA report {code}: {title}\n'
               f'-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/{code}.csv\n' + build())
        assert ';' not in sql                          # Hue splits statements on semicolons
        (OUT_SQL / f'{code}_{slug}.sql').write_text(sql)
    print(f'written {len(QUERIES)} queries in sql/eda_report/; save each result as data/eda_report/<code>.csv')


def _read(code):
    path = DATA / f'{code}.csv'
    if not path.exists():
        print(f'{code}: no download yet ({path.relative_to(DATA_DIR.parent)})')
        return None
    d = pd.read_csv(path)
    d.columns = [c.split('.')[-1].lower() for c in d.columns]
    return d


def build():
    """One workbook with a sheet per query, missing data turned into one row per column with what a blank means."""
    sheets = {}
    d = _read('Q1')
    if d is not None:
        row = d.iloc[0]
        cols = TEXT + NUMBERS + LANES
        sheets['Missing data'] = pd.DataFrame({
            'column': cols,
            'blank %': [round(100 * row[f'blank_{c}'], 2) for c in cols],
            'zero or less, % of filled rows': [round(100 * row[f'zero_or_less_{c}'], 2) if c in NUMBERS else None
                                               for c in cols],
            'what a blank means and what the model does': [N.BLANK_MEANS.get(c, '') for c in cols],
        }).sort_values('blank %', ascending=False)
    names = {'Q2': 'Missing by year', 'Q3': 'Original tax test', 'Q4': 'Duplicates',
             'Q5': 'Copies vs inspections', 'Q6': 'Cleaning log', 'Q7': 'Source of copies', 'Q8': 'Lanes'}
    for code, sheet in names.items():
        d = _read(code)
        if d is not None:
            sheets[sheet] = d.T.reset_index().rename(columns={'index': 'measure', 0: 'value'}) if len(d) == 1 else d
    if not sheets:
        return None
    out = RESULTS_DIR / f'CTRP_EDA_report_{E.LIVE_SNAPSHOT}.xlsx'
    N._write_book(out, sheets)
    print(f'written {out.relative_to(RESULTS_DIR.parent)}')
    return out
