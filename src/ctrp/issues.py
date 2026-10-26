"""
EDA issue workbook for the Risk Officers: every data problem found in the EDA, with the full entry and
taxpayer details behind it, so officers can say whether each one is a real data issue or how the system works.

What: one Hue query per issue (sql/eda_issues/E01_... to E13_...). Each returns every item row of the entries
      affected, with entry, taxpayer, goods, tax, lane and status columns. Python turns each download into its own
      small workbook: "Issue" (what we saw, what the model does, how to check it in ASYCUDA and in the data lake,
      the overall verdict), "Entry list" (one row per entry, to search and judge), "Taxpayers" (one row per TIN)
      and "Item rows" (every row behind the entries).
Why:  the cleaning rules (R1 to R15) rest on our reading of these problems. The officers know the system and
      can confirm or correct each reading before the model relies on it.
Order: a view has no fixed row order. Rows are kept in the order Hue returned them (column "Order returned"),
      not sorted, as asked; the entry key column lets officers filter one entry at a time.
Window: the 24 months before the live snapshot (1 Oct 2024 to 30 Sep 2026), IM4 and IM7 unless stated.
Size:  issues that touch very many entries (blank original tax, top-up column) return a random 1-in-K sample of
      entries (pmod(hash(entry key), K) = 0); the sheet says so.

    python main.py issues --sql      -> sql/eda_issues/*.sql
    python main.py issues            -> results/eda_issues/CTRP_EDA_E01_....xlsx, one small workbook per issue
"""
import re
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from ctrp.utils import DATA_DIR, RESULTS_DIR, SQL_DIR

ISSUE_SQL = SQL_DIR / 'eda_issues'
ISSUE_DATA = DATA_DIR / 'eda_issues'
START, END = '20240930', '20260930'
HUE_CAP = 100_000                       # Hue stops a download at this many rows
EXCEL_MAX_ROWS = 1_000_000              # an Excel sheet stops at 1,048,576 rows

# The entry key: entry number + station + year, or the declaration ID where any part is blank
KEY = "COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id)"
# The columns every issue query returns, in this order
DETAIL = ['entry_key', 'entry_num', 'clearance_station_cd', 'dec_ref_yer', 'instance_id', 'key_itm_nbr',
          'assessment_dt_wid', 'taxpayer_tin', 'taxpayer_nm', 'consignee_tin', 'consignee_nm', 'regime_cd',
          'extended_proc_cd', 'cpc_cd', 'decl_status', 'hsc_cd', 'gds_org_cty', 'customs_value', 'net_weight',
          'supplementary_qnty', 'tax_assessed', 'original_tax_amt', 'final_amt', 'top_up_amt', 'top_up_flg',
          'amendment_flg', 'is_red_flg', 'is_yellow_flg', 'pay_status', 'preferential_treatment_flag']
# Their labels in the workbook
NAMES = {
    'entry_key': 'Entry key (entry no. + station + year)', 'entry_num': 'Entry number',
    'clearance_station_cd': 'Station', 'dec_ref_yer': 'Year', 'instance_id': 'Declaration ID (instance_id)',
    'key_itm_nbr': 'Item number', 'assessment_dt_wid': 'Assessment date', 'taxpayer_tin': 'TIN',
    'taxpayer_nm': 'Taxpayer name', 'consignee_tin': 'Consignee TIN', 'consignee_nm': 'Consignee name',
    'regime_cd': 'Regime', 'extended_proc_cd': 'EPC', 'cpc_cd': 'APC', 'decl_status': 'Status',
    'hsc_cd': 'HS code', 'gds_org_cty': 'Origin', 'customs_value': 'Customs value, UGX',
    'net_weight': 'Net weight, kg', 'supplementary_qnty': 'Units', 'tax_assessed': 'Tax on item, UGX',
    'original_tax_amt': 'Original tax, UGX', 'final_amt': 'Final tax, UGX', 'top_up_amt': 'top_up_amt column, UGX',
    'top_up_flg': 'Top-up flag', 'amendment_flg': 'Amended flag', 'is_red_flg': 'Red lane',
    'is_yellow_flg': 'Yellow lane', 'pay_status': 'Payment status', 'preferential_treatment_flag': 'Preference claimed',
}

# ---- the SQL building blocks ----------------------------------------------------------------------
# base: every row of the view in the window, with the entry key (@@REGIME@@ becomes IMPORTS)
BASE = f"""base AS (
  SELECT {KEY} AS entry_key,
         {', '.join('v.' + c for c in DETAIL if c != 'entry_key')}
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '{START}' AND v.assessment_dt_wid <= '{END}'@@REGIME@@
)"""
IMPORTS = "\n    AND v.regime_cd IN ('IM4', 'IM7')"
# d: one row per declaration, for the tax and lane issues
DECL = """d AS (
  SELECT entry_key, instance_id, MAX(top_up_flg) AS flag, MAX(original_tax_amt) AS orig_raw,
         COALESCE(MAX(original_tax_amt), MAX(final_amt)) AS orig, MAX(final_amt) AS fin,
         MAX(top_up_amt) AS top_up_amt_max, MAX(is_red_flg) AS red, MAX(is_yellow_flg) AS yellow
  FROM base GROUP BY entry_key, instance_id
)"""

# ---- the issues -----------------------------------------------------------------------------------
# Each issue: (code, title, what we saw in the EDA, what the model does now (rule),
#              extra CTEs, which entries (a JOIN or a WHERE condition), extra columns, keep 1 in K entries)
ISSUES = [
    ('E01', 'Same entry under more than one declaration ID',
     'Entry number + station + year identifies an entry. Some entries appear under two or more declaration IDs '
     '(instance_id).',
     'R14: the entry key is used and only the latest (highest) declaration ID of each entry is kept. Please confirm '
     'which version is the real one.',
     "k AS (SELECT entry_key, COUNT(DISTINCT instance_id) AS declaration_ids_on_entry FROM base\n"
     "       GROUP BY entry_key HAVING COUNT(DISTINCT instance_id) > 1)",
     "JOIN k ON b.entry_key = k.entry_key", "k.declaration_ids_on_entry", 1),
    ('E02', 'The same item row repeated',
     'The same declaration and item number appear many times: 20% of rows repeat an item, up to 412 copies of one '
     'item (24 months to Sep 2026). Except for one item, every copy is identical in every column the model uses. '
     'The view joins three tables on the declaration ID only (header, item, inspection actions), so a repeat in any '
     'of them repeats the item. Q7 shows the item table is the source: for all 7,783 repeated items the item row '
     'repeats, while the header and inspection rows never do. 7,748 of them (99.6%) are on motor vehicle '
     'declarations. This sheet lists each different row once, with how many copies of the item the view holds.',
     'R5: each item is kept once. R15 also removes motor vehicle declarations, which hold almost all the copies.',
     "k AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies_of_item FROM base\n"
     "       GROUP BY instance_id, key_itm_nbr HAVING COUNT(*) > 1)",
     "JOIN k ON b.instance_id = k.instance_id AND b.key_itm_nbr = k.key_itm_nbr", "k.copies_of_item", 1),
    ('E03', 'TIN blank or not 10 digits',
     'Valid TINs are 10 digits. A few IM4/IM7 declarations carry a short or malformed TIN.',
     'R1: only 10-digit TINs are scored.',
     None, "NOT (COALESCE(b.taxpayer_tin, '') RLIKE '^[0-9]{10}$')", None, 1),
    ('E04', 'Cancelled declarations',
     'Declarations with status Cancelled.',
     'R3: cancelled declarations are left out.',
     None, "b.instance_id IN (SELECT instance_id FROM base WHERE decl_status = 'Cancelled')", None, 1),
    ('E05', 'APC 483 (destroyed or abandoned goods, dummy reconciliation entries)',
     'The CPC memo describes APC 483 as destroyed or abandoned goods and dummy reconciliation entries, not trade.',
     'R13: declarations under APC 483 are left out.',
     None, "b.instance_id IN (SELECT instance_id FROM base WHERE cpc_cd = '483')", None, 1),
    ('E06', 'Top-up flag Y, but the final tax is not above the original tax',
     'The top-up flag is set, yet the tax did not rise.',
     'R7: a top-up counts only when the flag is Y AND the final tax is above the original tax.',
     DECL, "b.instance_id IN (SELECT instance_id FROM d WHERE flag = 'Y' AND NOT (fin > orig))", None, 1),
    ('E07', 'Tax rose, but no top-up flag',
     'About 3,000 amended declarations have a higher final tax but no top-up flag.',
     'Decision 18: not counted as top-ups (the flag is customs\' own marking). Please confirm whether these are '
     'top-ups.',
     DECL,
     "b.instance_id IN (SELECT instance_id FROM d WHERE COALESCE(flag, 'N') <> 'Y' AND orig_raw IS NOT NULL "
     "AND fin > orig_raw)",
     None, 1),
    ('E08', 'Original tax blank',
     'Original tax is blank on many declarations (about 37% of those without a top-up).',
     'Blank is read as "unchanged": the final tax is used. This is our inference, not stated in the data.',
     DECL, "b.instance_id IN (SELECT instance_id FROM d WHERE orig_raw IS NULL)", None, 50),
    ('E09', 'top_up_amt holds the final tax on declarations without a top-up',
     'On declarations without a top-up flag, the top_up_amt column equals the final tax 99.5% of the time.',
     'R7: top_up_amt is not used; top-up = final tax minus original tax.',
     DECL,
     "b.instance_id IN (SELECT instance_id FROM d WHERE COALESCE(flag, 'N') <> 'Y' AND top_up_amt_max = fin "
     "AND fin > 0)",
     None, 50),
    ('E10', 'Red and yellow lane on the same declaration',
     'A declaration can carry both the red and the yellow flag.',
     'R12: a declaration counts as checked if either flag is 1.',
     DECL, "b.instance_id IN (SELECT instance_id FROM d WHERE red = 1 AND yellow = 1)", None, 5),
    ('E11', 'Value or weight zero, negative or missing',
     'A few items have no customs value or no weight.',
     'R8: such items are left out of the price features (they still count as declarations).',
     None,
     "b.instance_id IN (SELECT instance_id FROM base WHERE COALESCE(customs_value, 0) <= 0 "
     "OR COALESCE(net_weight, 0) <= 0)",
     None, 1),
    ('E12', 'Price per kg under 1% of the middle price for the HS code',
     'Some items are priced at under 1% of what importers usually declare for the same HS code: most likely a '
     'weight or quantity in the wrong unit.',
     'R9: treated as keying errors and kept out of the undervaluation measure (counted separately).',
     "bench AS (SELECT hsc_cd, percentile_approx(customs_value / net_weight, 0.5) AS med_kg FROM base "
     "WHERE customs_value > 0 AND net_weight > 0 GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),\n"
     "low AS (SELECT DISTINCT x.instance_id FROM base x JOIN bench m ON x.hsc_cd = m.hsc_cd "
     "WHERE x.customs_value > 0 AND x.net_weight > 0 AND x.customs_value / x.net_weight < 0.01 * m.med_kg)",
     "b.instance_id IN (SELECT instance_id FROM low)", None, 1),
]
# E13 is per taxpayer, not per entry: (code, title, what we saw, what the model does)
TIN_NAMES = ('E13', 'One TIN under several taxpayer names',
             'Taxpayer names are typed with variations, addresses mixed in, and in one case a backtick. Some TINs '
             'carry several names.',
             'Names are not used by the model; the TIN identifies the taxpayer. Please confirm none of these TINs is '
             'shared by different businesses.')


# =========================================================================================
# The queries
# =========================================================================================
def _no_semicolons(text):
    """Hue splits statements on semicolons, so none may appear, not even in a comment."""
    return text.replace(';', ',')


def render(issue):
    """The Hue query for one issue: a header comment, the CTEs, and every item row of the entries affected."""
    code, title, saw, rule, ctes, where, extra, k = issue
    regime = IMPORTS
    with_ = [BASE.replace('@@REGIME@@', regime)] + ([ctes] if ctes else [])
    join = where if where.startswith('JOIN') else ''
    cond = 'TRUE' if join else where
    sample = f"\n  AND pmod(hash(b.entry_key), {k}) = 0" if k > 1 else ''
    cols = (extra + ',\n       ' if extra else '') + 'b.*'
    saw, rule = _no_semicolons(saw), _no_semicolons(rule)
    window = (f"{START[:4]}-{START[4:6]}-{START[6:]} (exclusive) to {END[:4]}-{END[4:6]}-{END[6:]}"
              f"{', IM4 and IM7' if regime else ', all regimes'}"
              f"{f', a random 1 in {k} of the entries' if k > 1 else ''}")
    head = (f"-- CTRP EDA issue {code}: {title}\n-- What we saw: {saw}\n-- What the model does: {rule}\n"
            f"-- Every item row of the entries affected, {window}. Contains TINs: internal use only.\n"
            f"-- Run as ONE statement, download as CSV, save as data/eda_issues/{code}.csv\n")
    from_ = 'FROM base b' + ('\n' + join if join else '')
    # E02's copies are identical, and all of them are about 900,000 rows: past Hue's 100,000-row cap. Each different
    # row once is enough, since copies_of_item already says how many times the view holds the item.
    select = 'SELECT DISTINCT' if code == 'E02' else 'SELECT'
    sql = head + 'WITH ' + ',\n'.join(with_) + f"\n{select} {cols}\n{from_}\nWHERE {cond}{sample}\n"
    assert ';' not in sql
    return sql


def render_names():
    """The Hue query for E13: one row per TIN and name, for TINs with 3 or more names."""
    code, title, saw, rule = TIN_NAMES
    saw, rule = _no_semicolons(saw), _no_semicolons(rule)
    return (f"-- CTRP EDA issue {code}: {title}\n-- What we saw: {saw}\n-- What the model does: {rule}\n"
            f"-- One row per TIN and name. Run as ONE statement, save as data/eda_issues/{code}.csv\n"
            f"WITH {BASE.replace('@@REGIME@@', IMPORTS)},\n"
            "multi AS (SELECT taxpayer_tin FROM base GROUP BY taxpayer_tin HAVING COUNT(DISTINCT taxpayer_nm) >= 3)\n"
            "SELECT b.taxpayer_tin, b.taxpayer_nm, COUNT(DISTINCT b.instance_id) AS declarations,\n"
            "       MIN(b.assessment_dt_wid) AS first_seen, MAX(b.assessment_dt_wid) AS last_seen,\n"
            "       COUNT(DISTINCT b.clearance_station_cd) AS stations, MAX(b.entry_key) AS an_entry_key\n"
            "FROM base b\nWHERE b.taxpayer_tin IN (SELECT taxpayer_tin FROM multi)\n"
            "GROUP BY b.taxpayer_tin, b.taxpayer_nm\n")


def _slug(t):
    """A title as a short file-name part, e.g. 'Cancelled declarations' -> 'cancelled_declarations'."""
    return re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')[:50]


def write_queries():
    ISSUE_SQL.mkdir(parents=True, exist_ok=True)
    for i in ISSUES:
        (ISSUE_SQL / f'{i[0]}_{_slug(i[1])}.sql').write_text(render(i))
    (ISSUE_SQL / f'E13_{_slug(TIN_NAMES[1])}.sql').write_text(render_names())
    print(f'written {len(ISSUES) + 1} queries in sql/eda_issues/; save each result as data/eda_issues/<code>.csv')


# =========================================================================================
# How to check each issue: for the Risk Officers (in ASYCUDA) and for Data Engineering (in the data lake)
# The view's sources (from its definition): header columns come from dm_modeled_ura.ft_cstm_decl_hdr, item columns
# (including station, regime, APC, values and payment status) from dm_modeled_ura.ft_cstm_decl_item_tax, and
# inspection actions from awunadm.insp_act_tab_t, all joined on instance_id (the declaration ID).
# =========================================================================================
HDR, ITM, INSP = 'dm_modeled_ura.ft_cstm_decl_hdr', 'dm_modeled_ura.ft_cstm_decl_item_tax', 'awunadm.insp_act_tab_t'
HOW_TO_CHECK = {
    'E01': ('Search each entry in ASYCUDA by entry number, station and year (sheet "Entry list"). Which declaration '
            'ID is the current one, and what happened to the others (replaced, cancelled, lodged again after an '
            'amendment)? Tell us if the highest ID is not always the current one.',
            f'Look up the declaration IDs listed for the entry (instance_id) in {HDR}. The station comes from '
            f'{ITM} (clearance_station_cd). Is there a column that marks the current version of an entry?'),
    'E02': ('Nothing to check in ASYCUDA: the copies come from how the view is built.',
            f'The view joins {HDR}, {ITM} and {INSP} on instance_id only, so a declaration or item with more than '
            'one row in any of them repeats in the view. Which table has the repeated rows for these declarations, '
            'and is that intended? A view with one row per item would remove the copies.'),
    'E03': ('Open the declaration by entry number, station and year. Who is the importer, and is the TIN missing or '
            'mistyped? Are these importers who have no TIN (for example diplomatic, government or individuals)?',
            f'taxpayer_tin in {HDR}: is it blank or short at the source, or lost when the data is loaded?'),
    'E04': ('Confirm in ASYCUDA that these declarations are cancelled, and that no goods were released and no tax '
            'paid on them.',
            f'decl_status in {HDR}: do cancelled declarations keep their tax amounts and flags?'),
    'E05': ('Confirm that declarations under APC 483 are destroyed or abandoned goods, or dummy reconciliation '
            'entries, and not trade.',
            f'cpc_cd in {ITM}.'),
    'E06': ('Open the declaration: why is the top-up flag set when the final tax is not above the original tax? '
            'Was a top-up reversed later, or raised on something other than the tax amounts shown?',
            f'top_up_flg, original_tax_amt and final_amt in {HDR}: when is the flag set, and are the amounts updated '
            'at the same time?'),
    'E07': ('Open the declaration: the tax went up but there is no top-up flag. Was it an amendment by the '
            'declarant, or a customs top-up that was not flagged?',
            f'amendment_flg, top_up_flg, original_tax_amt and final_amt in {HDR}.'),
    'E08': ('For a few of these entries, confirm in ASYCUDA that the tax was not changed after assessment.',
            f'original_tax_amt in {HDR}: is it filled only when the tax changes?'),
    'E09': ('Nothing to check in ASYCUDA.',
            f'What does top_up_amt in {HDR} hold? On declarations without a top-up it equals the final tax.'),
    'E10': ('Was the declaration sent to both lanes, or moved from one lane to the other?',
            f'is_red_flg and is_yellow_flg in {HDR}: can both be set on one declaration, and what does it mean?'),
    'E11': ('Open the item: is the value or the weight really zero or missing on the declaration?',
            f'customs_value and net_weight in {ITM}.'),
    'E12': ('Open the item: is the weight or the quantity in the wrong unit?',
            f'net_weight and supplementary_qnty in {ITM}.'),
    'E13': ('Check the taxpayer register: is each TIN one business with its name typed in different ways, or '
            'several businesses sharing a TIN?',
            f'taxpayer_nm in {HDR}: is it typed on each declaration or taken from the taxpayer register?'),
}
HOW_TO_SEARCH = ('Sheet "Entry list" has one row per entry: search ASYCUDA with the entry number, station and year. '
                 'Sheet "Taxpayers" has one row per TIN. Sheet "Item rows" has every row behind each entry, as the '
                 'view returned it; filter it on the entry key to see one entry. In the data lake the declaration '
                 f'ID is instance_id ({HDR}, {ITM}).')


# =========================================================================================
# The workbook
# =========================================================================================
VERDICTS = 'Real data issue,How the system works,Not sure'
OUT_DIR = RESULTS_DIR / 'eda_issues'
RENAME = {**NAMES, 'order_returned': 'Order returned', 'officer_verdict': 'Officer verdict',
          'officer_comment': 'Officer comment', 'declaration_ids_on_entry': 'Declaration IDs on this entry',
          'rows_in_view': 'Times the view returned this row',
          'copies_of_item': 'Copies of this item', 'copies_identical': 'Copies identical',
          'declarations': 'Declarations', 'first_seen': 'First seen', 'last_seen': 'Last seen',
          'stations': 'Stations', 'an_entry_key': 'An entry key'}
NUMBER_COLUMNS = ['customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt',
                  'final_amt', 'top_up_amt']
HEADER_FILL = PatternFill('solid', start_color='102A83')


def _rows(code, k):
    """The download for one issue, numbered in the order the view returned it, with the verdict columns."""
    d = pd.read_csv(ISSUE_DATA / f'{code}.csv', dtype=str)
    d.columns = [c.split('.')[-1].lower() for c in d.columns]
    if len(d) and len(d) % HUE_CAP == 0:
        raise SystemExit(f'{code}.csv has exactly {len(d):,} rows: Hue cut the download. '
                         f'Raise K for {code} and run again.')
    same = None
    if code == 'E02' and len(d):
        # are all copies of an item the same in every column?
        cols = [c for c in DETAIL if c in d]
        same = d.groupby(['instance_id', 'key_itm_nbr'])[cols].nunique(dropna=False).max(axis=1) <= 1
    # The view repeats rows (E02), which made some downloads several hundred thousand rows long. Each different
    # row is kept once, in the order it first appeared, with how many times the view returned it.
    d = d.groupby(list(d.columns), dropna=False, sort=False).size().rename('rows_in_view').reset_index()
    d.insert(0, 'order_returned', range(1, len(d) + 1))
    if code == 'E02' and 'copies_of_item' in d:
        d = d.drop(columns='rows_in_view')            # the E02 query is DISTINCT: copies_of_item holds the count
    if same is not None:
        item = d.set_index(['instance_id', 'key_itm_nbr']).index
        d['copies_identical'] = item.map(same).map({True: 'Yes', False: 'No'})
    for c in NUMBER_COLUMNS:
        if c in d:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    return d.rename(columns=RENAME)


def _entry_list(d):
    """One row per entry, with what an officer needs to find it in ASYCUDA and judge it. Tax and value come from
    the entry's latest declaration ID; items are counted once each (the view repeats them, see E02)."""
    d = d.copy()
    for c in NUMBER_COLUMNS:
        if c in d:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    d['_id_order'] = d['instance_id'].fillna('').str.zfill(20)
    latest = d['_id_order'] == d.groupby('entry_key')['_id_order'].transform('max')
    items = d[latest].drop_duplicates(['instance_id', 'key_itm_nbr'])
    first = lambda s: s.dropna().iloc[0] if s.notna().any() else None
    joined = lambda s: ', '.join(sorted(s.dropna().astype(str).unique()))
    g = d.groupby('entry_key', sort=False)
    out = pd.DataFrame({
        'Entry number': g['entry_num'].agg(first),
        'Station': g['clearance_station_cd'].agg(first),
        'Year': g['dec_ref_yer'].agg(first),
        'Declaration IDs': g['instance_id'].agg(joined),
        'Latest declaration ID': d[latest].groupby('entry_key')['instance_id'].agg(first),
        'Assessment dates': g['assessment_dt_wid'].agg(joined),
        'TIN': g['taxpayer_tin'].agg(joined),
        'Taxpayer name': g['taxpayer_nm'].agg(joined),
        'Consignee TIN': g['consignee_tin'].agg(joined),
        'Consignee name': g['consignee_nm'].agg(joined),
        'Regime': g['regime_cd'].agg(joined),
        'Status': g['decl_status'].agg(joined),
        'APCs': g['cpc_cd'].agg(joined),
        'Items (latest declaration)': items.groupby('entry_key').size(),
        'Rows in the view': g.size(),
        'Customs value, UGX (latest declaration)': items.groupby('entry_key')['customs_value'].sum(),
        'Original tax, UGX (latest declaration)': d[latest].groupby('entry_key')['original_tax_amt'].max(),
        'Final tax, UGX (latest declaration)': d[latest].groupby('entry_key')['final_amt'].max(),
        'top_up_amt column, UGX (latest declaration)': d[latest].groupby('entry_key')['top_up_amt'].max(),
        'Top-up flag': g['top_up_flg'].agg(joined),
        'Amended flag': g['amendment_flg'].agg(joined),
        'Red lane': g['is_red_flg'].agg(joined),
        'Yellow lane': g['is_yellow_flg'].agg(joined),
        'Payment status': g['pay_status'].agg(joined),
    })
    out.index.name = 'Entry key (entry no. + station + year)'
    out = out.reset_index()
    out['Officer verdict'], out['Officer comment'] = '', ''
    return out


def _taxpayers(d):
    """One row per TIN: who they are and how many of the entries affected are theirs."""
    joined = lambda s: ', '.join(sorted(s.dropna().astype(str).unique()))
    g = d.groupby('taxpayer_tin', dropna=False)
    out = pd.DataFrame({
        'Taxpayer name(s)': g['taxpayer_nm'].agg(joined),
        'Entries affected': g['entry_key'].nunique(),
        'Declaration IDs': g['instance_id'].nunique(),
        'First seen': g['assessment_dt_wid'].min(),
        'Last seen': g['assessment_dt_wid'].max(),
        'Stations': g['clearance_station_cd'].agg(joined),
        'Consignee name(s)': g['consignee_nm'].agg(joined),
    })
    out.index.name = 'TIN'
    return out.reset_index().sort_values('Entries affected', ascending=False)


def _verdict_list():
    return DataValidation(type='list', formula1=f'"{VERDICTS}"', allow_blank=True)


def _write(path, about, rows, entries=None, taxpayers=None):
    """'Issue' (what it is, how to check it, the overall verdict), then 'Entry list' (one row per entry, with a
    verdict per entry), 'Taxpayers' (one row per TIN) and 'Item rows' (every row behind the entries)."""
    sheets = [('Entry list', entries), ('Taxpayers', taxpayers), ('Item rows', rows)]
    sheets = [(name, df) for name, df in sheets if df is not None]
    with pd.ExcelWriter(path, engine='openpyxl') as w:
        about.to_excel(w, sheet_name='Issue', index=False, header=False)
        for name, df in sheets:
            df.to_excel(w, sheet_name=name, index=False)

        ws = w.book['Issue']
        ws.column_dimensions['A'].width, ws.column_dimensions['B'].width = 28, 110
        for r in ws.iter_rows():
            r[0].font = Font(bold=True)
            for c in r:
                c.alignment = Alignment(wrap_text=True, vertical='top')
        dv = _verdict_list()
        ws.add_data_validation(dv)
        row = 1 + list(about[0]).index('Your verdict (choose)')
        dv.add(f'B{row}')                                     # the overall verdict cell

        for name, _ in sheets:
            _format_table(w.book[name])


def _format_table(ws):
    """Blue header, sensible widths, UGX as whole numbers, a verdict list where there is one, filters on."""
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = HEADER_FILL
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for col in ws.columns:
        h = str(col[0].value or '')
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:300])
        width = 45 if h == 'Officer comment' else min(max(10, width + 2), 40)
        ws.column_dimensions[col[0].column_letter].width = width
        if 'UGX' in h:
            for c in col[1:]:
                c.number_format = '#,##0'
    hdr = {c.value: c.column_letter for c in ws[1]}
    if 'Officer verdict' in hdr:
        dv = _verdict_list()
        ws.add_data_validation(dv)
        col = hdr['Officer verdict']
        dv.add(f"{col}2:{col}{max(ws.max_row, 2)}")
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = ws.dimensions


def _about(code, title, saw, rule, shown):
    """The 'Issue' sheet: what we saw, what the model does, and where the officers give their verdict."""
    return pd.DataFrame([
        ['Issue', f'{code}: {title}'],
        ['What we saw', saw],
        ['What the model does now', rule],
        ['What is in this workbook', f'{shown} Period: 1 Oct 2024 to 30 Sep 2026, IM4 and IM7.'],
        ['How to search', HOW_TO_SEARCH],
        ['How to check it: Risk Officers', HOW_TO_CHECK.get(code, ('', ''))[0]],
        ['How to check it: Data Engineering', HOW_TO_CHECK.get(code, ('', ''))[1]],
        ['What we ask', 'Is this a real data problem, or is it how the system works? Choose below, and add a comment. '
                        'You can also mark each entry in the "Officer verdict" column of "Entry list".'],
        ['Your verdict (choose)', ''],
        ['Your comment', ''],
        ['Note', 'Contains TINs, names and entry numbers: internal use only. Prepared by Data Science (ITID) for the '
                 'CTRP model.'],
    ])


def build(out_dir=None, codes=None):
    """One workbook per issue in results/eda_issues/, for every issue whose download is in data/eda_issues/.
    codes: only these issues (for example the ones chosen for a review); None = all of them."""
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for code, title, saw, rule, _, _, _, k in ISSUES + [TIN_NAMES + (None, None, None, 1)]:
        if codes is not None and code not in codes:
            continue
        if not (ISSUE_DATA / f'{code}.csv').exists():
            print(f'{code}: no download yet (data/eda_issues/{code}.csv)')
            continue
        rows = _rows(code, k)
        if len(rows) > EXCEL_MAX_ROWS:                     # an Excel sheet holds about a million rows
            print(f'{code}: {len(rows):,} different rows, the first {EXCEL_MAX_ROWS:,} go in "Item rows"')
            rows = rows.head(EXCEL_MAX_ROWS)
        raw = pd.read_csv(ISSUE_DATA / f'{code}.csv', dtype=str)
        raw.columns = [c.split('.')[-1].lower() for c in raw.columns]
        unit = 'taxpayers' if code == 'E13' else 'entries'
        n = rows['TIN'].nunique() if code == 'E13' else rows[NAMES['entry_key']].nunique()
        if k == 1:
            shown = f'All {n:,} {unit} affected ({len(rows):,} rows).'
        else:
            shown = (f'A random 1 in {k} of the entries affected: {n:,} entries ({len(rows):,} rows), '
                     f'so about {k * n:,} entries in all.')
        path = out_dir / f'CTRP_EDA_{code}_{_slug(title)}.xlsx'
        entries = None if code == 'E13' else _entry_list(raw)
        taxpayers = None if code == 'E13' else _taxpayers(raw)
        _write(path, _about(code, title, saw, rule, shown), rows, entries, taxpayers)
        written.append(path)
        print(f'{code}: {path.name}  ({n:,} {unit}, {len(rows):,} rows)')
    return written
