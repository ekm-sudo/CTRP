"""
Build the notebook CTRP_EDA_report.ipynb: the EDA report for sign-off, from Hue downloads.

What: one notebook that reads the EDA queries (data/eda_report/Q1..Q8.csv) and the 10 problem tables
      (data/eda_issues/E01.csv ...), shows each finding with the entries and taxpayers behind it, makes the
      features step by step from the Hue extract (data/bt_2026-03-31.csv), and writes the Excel outputs:
      the EDA report workbook, one workbook per problem for the Risk Officers and Data Engineering, and the
      final dataset workbook.
Why:  Zeppelin cannot read the view yet (no SELECT right for our user); Hue can. The heavy counting is done in
      Hue on the full data, the notebook explains it.

    python notebooks/build_eda_report_nb.py      -> notebooks/CTRP_EDA_report.ipynb
"""
import sys
from pathlib import Path

import nbformat as nbf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ctrp import eda_note as N          # noqa: E402
from ctrp import issues as I            # noqa: E402

cells = []


def md(text):
    cells.append(nbf.v4.new_markdown_cell(text.strip()))


def code(text):
    cells.append(nbf.v4.new_code_cell(text.strip()))


md("""
# CTRP: data exploration (EDA) report

**Customs Taxpayer Risk Profiling Model.** Data Science Section, ITID. For review and sign-off.

This notebook shows what we found in the customs view, how we cleaned it, and the features the model uses.
The counting is done in Hue on the full data (IM4 and IM7, the 24 months to 30 Sep 2026); the queries are in
`sql/eda_report/` and `sql/eda_issues/`. The Excel outputs are written at the end.

| Part | What | Hue download it reads |
|---|---|---|
| 1 | Missing data | `data/eda_report/Q1.csv`, `Q2.csv`, `Q3.csv` |
| 2 | Duplicates, where they come from, and lane flags | `Q4.csv`, `Q7.csv`, `Q8.csv` |
| 3 | The 10 data problems, with entries and taxpayers from the view | `data/eda_issues/E01.csv` ... |
| 4 | Cleaning: what each rule removed | `Q6.csv` |
| 5 | The 22 features and their names | none |
| 6 | Making the features step by step, from the Hue extract to the final dataset | `data/bt_2026-03-31.csv` |
| 7 | The Excel outputs | all of the above |

**Before running:** `python main.py eda-report --sql` and `python main.py issues --sql` write the queries; run each
in Hue and save the result under the name it gives. Missing files are listed in the first cell; the parts that
need them are skipped.
""")

code("""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
sys.path.insert(0, str(ROOT / 'src'))
from ctrp import core as M, eda_hue as H, eda_note as N, extract as E, issues as I

pd.set_option('display.max_columns', 40)
pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 120)

FINAL_FOLDER = ROOT / 'data' / 'eda_final'      # where Part 6 writes the final dataset


def read(path):
    d = pd.read_csv(path)
    d.columns = [c.split('.')[-1].lower() for c in d.columns]      # Hue may add a table prefix
    return d


def show_sql(code):
    # the Hue query behind a section
    print(next((ROOT / 'sql' / 'eda_report').glob(f'{code}_*.sql')).read_text())


have = {}
for code, slug, title, _ in H.QUERIES:
    have[code] = (H.DATA / f'{code}.csv').exists()
for code in N.REVIEW_ISSUES:
    have[code] = (I.ISSUE_DATA / f'{code}.csv').exists()
print('Missing downloads:', [k for k, ok in have.items() if not ok] or 'none')
""")

# ------------------------------------------------------------------------------------------- 1
md("""
## 1. Missing data

For every column: how often it is blank, and for numbers how often it is zero or less. The last column says what
a blank means for the model and what the model does with it.
""")
code("""
q1 = read(H.DATA / 'Q1.csv').iloc[0]
columns = H.TEXT + H.NUMBERS + H.LANES
missing = pd.DataFrame({
    'column': columns,
    'blank %': [100 * q1['blank_' + c] for c in columns],
    'zero or less, % of filled rows': [100 * q1['zero_or_less_' + c] if c in H.NUMBERS else np.nan for c in columns],
    'what a blank means and what the model does': [N.BLANK_MEANS.get(c, '') for c in columns],
}).sort_values('blank %', ascending=False)
print(f"{int(q1['item_rows']):,} item rows")
missing.round(2)
""")
code("""
shown = missing[missing['blank %'] > 0].sort_values('blank %')
shown.plot.barh(x='column', y='blank %', legend=False, figsize=(8, 0.35 * len(shown) + 1), color='#1F4FD8')
plt.title('Share of rows where the column is blank (%)')
plt.tight_layout()
plt.show()
""")
md("""
### 1.1 Is it getting better or worse?

Blank share per year for the columns the model leans on.
""")
code("""
q2 = read(H.DATA / 'Q2.csv').set_index('year')
by_year = (100 * q2.filter(like='blank_')).round(2)
by_year.columns = [c.replace('blank_', '') for c in by_year.columns]
by_year
""")
md("""
### 1.2 Test of "blank original tax means unchanged" (problem E08)

If a blank original tax means the tax never changed, declarations **with** a top-up flag should almost never have
a blank original tax, because a top-up changes the tax.
""")
code("""
q3 = read(H.DATA / 'Q3.csv')
q3['original tax blank %'] = (100 * q3['original_tax_blank']).round(1)
q3[['top_up_flag', 'declarations', 'original tax blank %']]
""")

# ------------------------------------------------------------------------------------------- 2
md("""
## 2. Duplicates, and where they come from

The same thing can appear more than once at four levels: a row copied, an item repeated, an entry under several
declaration IDs, and one declaration ID with more than one taxpayer or date.
""")
code("""
q4 = read(H.DATA / 'Q4.csv').iloc[0]
pd.DataFrame({'check': [
        'Item rows', 'Rows that repeat another row exactly', 'Rows that repeat an item',
        'Items whose copies are not identical', 'Most copies of one item', 'Entries under more than one declaration ID',
        'Declaration IDs with more than one TIN', 'Declaration IDs with more than one date'],
    'count': [q4['item_rows'], q4['item_rows'] - q4['different_rows'], q4['item_rows'] - q4['items'],
              q4['items_with_copies_not_identical'], q4['most_copies_of_one_item'], q4['entries_under_several_ids'],
              q4['ids_with_several_tins'], q4['ids_with_several_dates']]})
""")
md("""
### 2.1 Where the repeated items come from

The view joins the declaration header, item and inspection tables on the declaration ID. The repeats come from
the item table, and almost all of them are on motor vehicle declarations, which the model drops (R15). The items
themselves are in problem E02 (Part 3).
""")
code("""
q7 = read(H.DATA / 'Q7.csv').iloc[0]
pd.Series({
    'Repeated items': q7['repeated_items'],
    'Item row repeats': q7['items_whose_item_row_repeats'],
    'Header row repeats': q7['items_whose_header_repeats'],
    'Inspection rows repeat': q7['items_with_several_inspection_rows'],
    'On motor vehicle declarations': q7['items_on_vehicle_declarations'],
}).map('{:,.0f}'.format).to_frame('items')
""")
md("""
### 2.2 Lane flags

Half the rows have a blank red flag and a quarter a blank yellow flag. The model counts a declaration as checked
when red or yellow is 1, so a blank counts as not checked. The view also has green and blue flags: this table shows
every combination per declaration, blanks included, to see what a blank means.
""")
code("""
read(H.DATA / 'Q8.csv')
""")

# ------------------------------------------------------------------------------------------- 3
md("""
## 3. The 10 data problems, with the entries from the view

For each problem: how many entries and taxpayers it touches, 10 entries straight from the view with only the
columns that show the problem, and the taxpayers with the most entries affected. Every entry is in the problem's
workbook (Part 7).
""")
code("""
from IPython.display import display

ID = ['entry_num', 'clearance_station_cd', 'dec_ref_yer', 'instance_id', 'taxpayer_tin', 'taxpayer_nm']
# the columns that show each problem, and whether it is judged per declaration or per item
PROOF = {
    'E01': (['declaration_ids_on_entry'], 'item'),
    'E02': (['key_itm_nbr', 'hsc_cd', 'copies_of_item'], 'item'),
    'E03': ([], 'item'),
    'E04': (['decl_status'], 'declaration'),
    'E05': (['cpc_cd'], 'declaration'),
    'E06': (['top_up_flg', 'original_tax_amt', 'final_amt'], 'declaration'),
    'E07': (['top_up_flg', 'original_tax_amt', 'final_amt'], 'declaration'),
    'E08': (['top_up_flg', 'original_tax_amt', 'final_amt'], 'declaration'),
    'E09': (['top_up_flg', 'top_up_amt', 'final_amt'], 'declaration'),
    'E11': (['key_itm_nbr', 'hsc_cd', 'customs_value', 'net_weight'], 'item'),
}
LABELS = {**I.NAMES, 'copies_of_item': 'Copies of this item in the view',
          'declaration_ids_on_entry': 'Declaration IDs on the entry'}
SAMPLE = {code: k for code, *_, k in I.ISSUES}
AMOUNTS = I.NUMBER_COLUMNS + ['copies_of_item']


_downloads = {}


def load(code):
    # a problem's Hue download, read once and kept
    if code not in _downloads:
        d = pd.read_csv(I.ISSUE_DATA / f'{code}.csv', dtype=str)
        d.columns = [c.split('.')[-1].lower() for c in d.columns]
        _downloads[code] = d
    return _downloads[code].copy()


def evidence(code, n=10):
    d = load(code)
    if d.empty:
        print('None found in the view.')
        return
    cols, level = PROOF[code]
    cols = [c for c in cols if c in d]
    for c in AMOUNTS:
        if c in d:
            d[c] = pd.to_numeric(d[c], errors='coerce')
    k = SAMPLE[code]
    entries, tins = d['entry_key'].nunique(), d['taxpayer_tin'].nunique()
    if k == 1:
        print(f'{entries:,} entries, {tins:,} taxpayers')
    else:
        print(f'A 1 in {k} sample: {entries:,} entries ({tins:,} taxpayers), so about {k * entries:,} entries in all')
    if level == 'declaration':      # one row per declaration, as the query judged it
        rows = d.groupby(ID, dropna=False)[cols].max().reset_index()
    else:
        rows = d[ID + cols].drop_duplicates()
    if 'copies_of_item' in rows:
        rows = rows.sort_values('copies_of_item', ascending=False)
    for c in AMOUNTS:
        if c in rows:
            rows[c] = rows[c].map(lambda v: 'blank' if pd.isna(v) else f'{v:,.0f}')
    display(rows.head(n).rename(columns=LABELS).reset_index(drop=True))
    top = (d.groupby('taxpayer_tin', dropna=False)
             .agg(taxpayer_nm=('taxpayer_nm', 'first'), entries=('entry_key', 'nunique'))
             .sort_values('entries', ascending=False).head(5).reset_index())
    display(top.rename(columns={**LABELS, 'entries': 'Entries affected'}))
""")

for issue_code, title, saw, rule, *_ in I.ISSUES:
    if issue_code not in N.REVIEW_ISSUES:
        continue
    md(f"""
### {issue_code}: {title}

{rule}
""")
    code(f"evidence('{issue_code}')")

md("""
### Every declaration behind a problem, and looking one up

`declarations('E04')` gives every declaration behind a problem, one row each, with its details from the view: the
entry (number, station, year), the declaration ID, date, taxpayer, consignee, regime, EPC, status, payment, flags
and tax, plus its items, value, HS codes and APCs. Filter it like any table, for example
`e04[e04['TIN'] == '1000012345']`.

`find('...')` takes an entry number, an entry key or a declaration ID, lists the problems it falls under, and shows
every item row the view holds for it.
""")
code("""
DECL_LEVEL = ['entry_key', 'entry_num', 'clearance_station_cd', 'dec_ref_yer', 'assessment_dt_wid', 'taxpayer_tin',
              'taxpayer_nm', 'consignee_tin', 'consignee_nm', 'regime_cd', 'extended_proc_cd', 'decl_status',
              'pay_status', 'top_up_flg', 'amendment_flg', 'is_red_flg', 'is_yellow_flg', 'original_tax_amt',
              'final_amt', 'top_up_amt']
TITLES = {code: title for code, title, *_ in I.ISSUES}
joined = lambda s: ', '.join(sorted(s.dropna().unique()))


def declarations(code):
    d = load(code)
    if d.empty:
        print('None found in the view.')
        return d
    items = d.drop_duplicates(['instance_id', 'key_itm_nbr'])
    g = items.groupby('instance_id', sort=False)
    out = g[[c for c in DECL_LEVEL if c in d]].first()
    out['items'] = g.size()
    out['customs_value'] = g['customs_value'].agg(lambda s: pd.to_numeric(s, errors='coerce').sum())
    out['tax_assessed'] = g['tax_assessed'].agg(lambda s: pd.to_numeric(s, errors='coerce').sum())
    out['hs_codes'] = g['hsc_cd'].agg(joined)
    out['apcs'] = g['cpc_cd'].agg(joined)
    if 'copies_of_item' in d:
        out['copies_of_item'] = d.groupby('instance_id')['copies_of_item'].agg(lambda s: pd.to_numeric(s).max())
    out = out.reset_index()
    print(f'{code} {TITLES[code]}: {len(out):,} declarations'
          + ('' if SAMPLE[code] == 1 else f' (a 1 in {SAMPLE[code]} sample)'))
    return out.rename(columns={**LABELS, 'items': 'Items', 'customs_value': 'Customs value, UGX',
                               'tax_assessed': 'Tax assessed, UGX', 'hs_codes': 'HS codes', 'apcs': 'APCs',
                               'copies_of_item': 'Most copies of an item'})


def find(number):
    number = str(number).strip()
    found = []
    for code in N.REVIEW_ISSUES:
        if not have[code]:
            continue
        d = load(code)
        if d.empty:
            continue
        match = d[(d['instance_id'] == number) | (d['entry_num'] == number) | (d['entry_key'] == number)]
        if len(match):
            print(f'{code} {TITLES[code]}: {match["instance_id"].nunique()} declaration(s)')
            found.append(match)
    if not found:
        print('Not in any problem download.')
        return
    rows = pd.concat(found).drop_duplicates(subset=[c for c in I.DETAIL if c in found[0]])
    display(rows.rename(columns=LABELS).reset_index(drop=True))
""")
code("""
e02 = declarations('E02')      # every declaration with repeated items
e02.head(20)
""")
code("""
find(load('E02')['instance_id'].iloc[0])      # or find('<entry number or declaration ID>')
""")

# ------------------------------------------------------------------------------------------- 4
md("""
## 4. Cleaning: what each rule removed

The 36 months the features need, all regimes, so each rule shows what it removes. A row is counted at the first
rule it fails.

| Rule | Keeps |
|---|---|
| R1 | TINs of 10 digits (E03) |
| R3 | declarations not cancelled (E04) |
| R4 | IM4 and IM7 |
| R13 | everything except APC 483 (E05) |
| R14 | the latest declaration ID of each entry (E01) |
| R15 | declarations with no motor vehicle item |
| R5 | each item once (E02) |
""")
code("""
q6 = read(H.DATA / 'Q6.csv')
log = q6.set_index('step')['rows_removed']
loaded, left = log['rows loaded'], log['rows left']
removed = log.drop(['rows loaded', 'rows left'])
print(f'Rows loaded: {loaded:,}   removed: {removed.sum():,}   left: {left:,}   adds up: {loaded - removed.sum() == left}')
cleaning = removed.rename('rows removed').to_frame()
cleaning['% of rows loaded'] = (100 * cleaning['rows removed'] / loaded).round(2)
cleaning
""")

# ------------------------------------------------------------------------------------------- 5
md("""
## 5. The 22 features and their names

Each name says what is measured, per what, over which window, and ends with the unit. Track A (the scorecard) has
8 features, Track B (the Risky Behaviour Flag) 17; three are in both.
""")
code("N.feature_sheet()")
code("pd.DataFrame(N.ABBREVIATIONS, columns=['short form', 'meaning'])")

# ------------------------------------------------------------------------------------------- 6
md("""
## 6. Making the features, step by step

The model works in two halves:

1. **In Hue (SQL):** the query `sql/bt_2026-03-31.sql` reads the view, applies the cleaning rules of Part 4
   (R1, R3, R4, R13, R14, R15, R5) and counts, for each taxpayer, what the features need: declarations, top-ups
   per year, values, stations, prices against other importers, and so on. The result is the extract
   `data/bt_2026-03-31.csv`: **one row per taxpayer, real data**.
2. **In Python (here):** those counts are turned into the 25 features, then the final dataset.

The extract is the 31 March 2026 snapshot (the 24 months to that date, plus the 6 months after it as outcomes).
The steps are the same for any snapshot: for the live one, only the file name changes.
""")
code(r"""
EXTRACT = ROOT / 'data' / 'bt_2026-03-31.csv'

d = pd.read_csv(EXTRACT, dtype={'taxpayer_tin': str})      # TINs as text, so no leading zero is lost
d.columns = [c.split('.')[-1].lower() for c in d.columns]
print(f"{len(d):,} taxpayers, {d.shape[1]} columns, snapshot {d['snapshot_date'].iloc[0]}")
print('one row per taxpayer:', d['taxpayer_tin'].is_unique)
d.head()
""")

md("""
### 6.1 All the columns in the extract

What each column counts, how often it is blank, and an example value.
""")
code(r"""
MEANING = {
    'taxpayer_tin': 'TIN',
    'snapshot_date': 'the date the profile is made',
    'limited_history': 'Y if fewer than 10 declarations in the 24 months',
    'entries_24m': 'declarations in the 24 months',
    'active_months': 'months with at least one declaration',
    'avg_items_per_entry': 'items per declaration',
    'total_customs_value': 'customs value, UGX, 24 months',
    'total_original_tax': 'original tax, UGX, 24 months (blank read as unchanged)',
    'total_top_up': 'top-ups, UGX, 24 months (final minus original tax, flag Y)',
    'hs_headings_used': 'different HS headings (4 digits)',
    'origins_used': 'different countries of origin',
    'cpcs_used': 'different APCs',
    'dominant_hs_chapter': 'the HS chapter with most of the value',
    'chapter_value_share': 'share of value in that chapter',
    'stations_used_24m': 'different stations, 24 months',
    'stations_used_90d': 'different stations, last 90 days',
    'main_station_share': 'share of declarations at the busiest station',
    'entries_last_90d': 'declarations in the last 90 days',
    'entries_prev_90d': 'declarations in the 90 days before that',
    'im7_share': 'share of declarations under IM7',
    'distinct_consignees': 'different consignees',
    'consignee_is_self_share': 'share of declarations where the consignee is the taxpayer',
    'par045_amended_entry_rate': 'amended declarations / declarations, 24 months',
    'par048_top_up_ratio': 'top-ups / original tax, 24 months',
    'par066_negative_top_up_rate': 'declarations with tax reduced / declarations, 24 months',
    'par077_severe_top_up_rate': 'top-ups of 30% or more of final tax / declarations, 24 months',
    'par105_days_since_last_top_up': 'days from the last top-up to the snapshot (24 months)',
    'top_up_entry_rate': 'declarations topped up / declarations, 24 months',
    'items_benchmarked': 'items with a price comparison (5 or more importers of the HS code)',
    'par076_low_price_item_rate': 'items under half the middle price of other importers / items compared',
    'par076_shortfall_share': 'value missing on those low items / value',
    'ctx_implausible_price_rate': 'items under 1% of the middle price (keying errors) / items compared',
    'origin_benchmark_share': 'items compared within the same origin / items compared',
    'price_deviation_median': 'middle distance of prices from other importers (log)',
    'hs_codes_compared': 'HS codes with enough own history for the price drop check',
    'own_price_drop_share': 'recent value whose price fell over 30% against own history / recent value',
    'low_duty_value_share': 'value with a duty rate under half the middle rate for the HS code / value compared',
    'duty_gap_share': 'duty missing against the middle rate / value compared',
    'exemption_apc_value_share': 'value under an exemption APC (not 000) / value',
    'watchlist_apc_value_share': 'value under a watchlist APC / value',
    'watchlist_apcs_used': 'which watchlist APCs were used',
    'same_day_split_share': 'declarations sharing a day and HS code with another / declarations',
    'same_day_split_expected': 'the same, if the taxpayer split as often as is normal for their goods',
    'same_day_split_excess': 'split share minus the normal share',
    'max_same_day_same_hs': 'most declarations of one HS code on one day',
    'days_since_first_in_window': 'days from the first declaration in the 24 months to the snapshot',
    'new_trader': 'Y if no imports in the 3 years before the 24 months',
    'ctx_unpaid_rate': 'declarations with tax due and NOT_PAID / declarations',
    'ctx_red_lane_rate': 'declarations in the red lane / declarations',
    'ctx_yellow_lane_rate': 'declarations in the yellow lane / declarations',
    'ctx_preferential_use_rate': 'items claiming preferential treatment / items',
    'days_since_last_top_up_36m': 'days from the last top-up to the snapshot (36 months)',
}
for k in (1, 2, 3):
    when = {1: 'the latest year', 2: 'the year before', 3: 'the year before that'}[k]
    MEANING.update({f'y{k}_entries': f'declarations, {when}', f'y{k}_topped_up': f'declarations topped up, {when}',
                    f'y{k}_severe': f'severe top-ups, {when}', f'y{k}_amended': f'amended declarations, {when}',
                    f'y{k}_tax_reduced': f'declarations with tax reduced, {when}',
                    f'y{k}_top_up_ugx': f'top-ups, UGX, {when}', f'y{k}_original_tax_ugx': f'original tax, UGX, {when}'})
MEANING.update({'out_entries': 'OUTCOME: declarations in the 6 months after', 'out_checked': 'OUTCOME: of those, checked',
                'out_checked_hits': 'OUTCOME: checked and topped up', 'out_topped_up_entries': 'OUTCOME: topped up',
                'out_top_up': 'OUTCOME: top-ups, UGX', 'out_original_tax': 'OUTCOME: original tax, UGX'})

pd.set_option('display.max_rows', 200)
pd.DataFrame({
    'column': d.columns,
    'what it counts': [MEANING.get(c, '') for c in d.columns],
    'blank %': (100 * d.isna().mean()).round(1).values,
    'example': [d[c].dropna().iloc[0] if d[c].notna().any() else '' for c in d.columns],
})
""")

md("""
### 6.2 Dropping the columns I do not need

I keep what a feature, the peer groups or the small-numbers step uses, plus the outcomes (what happened in the 6
months after the snapshot, used to test the model, never as a feature). Lane rates go: Track B must not use what
customs did.
""")
code(r"""
YEARLY = [f'y{k}_{c}' for k in (1, 2, 3)
          for c in ['entries', 'topped_up', 'severe', 'amended', 'tax_reduced', 'top_up_ugx', 'original_tax_ugx']]
NEEDED = (['taxpayer_tin', 'snapshot_date', 'entries_24m', 'total_customs_value', 'total_original_tax', 'total_top_up',
           'items_benchmarked', 'dominant_hs_chapter', 'hs_headings_used', 'main_station_share', 'entries_last_90d',
           # Track A
           'top_up_entry_rate', 'par077_severe_top_up_rate', 'par045_amended_entry_rate', 'par066_negative_top_up_rate',
           'par105_days_since_last_top_up', 'par076_shortfall_share'] + YEARLY +
          # Track B
          ['ctx_unpaid_rate', 'ctx_implausible_price_rate', 'par076_low_price_item_rate', 'price_deviation_median',
           'own_price_drop_share', 'low_duty_value_share', 'duty_gap_share', 'exemption_apc_value_share',
           'watchlist_apc_value_share', 'ctx_preferential_use_rate', 'same_day_split_share', 'same_day_split_expected',
           'same_day_split_excess', 'days_since_first_in_window', 'new_trader'] +
          [c for c in d.columns if c.startswith('out_')])
dropped = [c for c in d.columns if c not in NEEDED]
print(f'Dropping {len(dropped)} columns:', ', '.join(dropped))
d = d[NEEDED].copy()
print('Keeping', d.shape[1], 'columns')
""")

md("""
### 6.3 Track A: the compliance history scorecard (8 features)

**Recency.** Five history rates use 3 years, with the latest year counting 1, the year before 0.5 and the year
before that 0.25:

rate = (1 x count in year 1 + 0.5 x count in year 2 + 0.25 x count in year 3) / (the same for declarations)

So an old top-up weighs less than a recent one, and a trader who cleaned up recovers within about 2 years. A
taxpayer with no declarations in the 3 years keeps the 24-month rate.
""")
code(r"""
WEIGHTS = {1: 1.0, 2: 0.5, 3: 0.25}


def weighted(count):
    # the 3-year total of one count, each year weighted
    return sum(w * d[f'y{k}_{count}'].fillna(0) for k, w in WEIGHTS.items())


n_3y = weighted('entries')
has_3y = n_3y > 0
a = pd.DataFrame({'taxpayer_tin': d['taxpayer_tin']})
a['topped_up_per_decl_3y_rate'] = (weighted('topped_up') / n_3y).where(has_3y, d['top_up_entry_rate'])
a['severe_top_up_per_decl_3y_rate'] = (weighted('severe') / n_3y).where(has_3y, d['par077_severe_top_up_rate'])
a['amended_per_decl_3y_rate'] = (weighted('amended') / n_3y).where(has_3y, d['par045_amended_entry_rate'])
a['tax_reduced_per_decl_3y_rate'] = (weighted('tax_reduced') / n_3y).where(has_3y, d['par066_negative_top_up_rate'])

# top-ups / final tax, over the same weighted 3 years (final tax = original tax + top-ups)
top_up_3y = weighted('top_up_ugx').where(has_3y, d['total_top_up'])
original_3y = weighted('original_tax_ugx').where(has_3y, d['total_original_tax'])
final_tax_3y = original_3y + top_up_3y
a['top_up_per_final_tax_3y_rate'] = (top_up_3y / final_tax_3y).where(final_tax_3y > 0)

# the other three stay at 24 months
a['peer_price_shortfall_per_value_24m_rate'] = d['par076_shortfall_share']
a['top_up_last_180d_flag'] = (d['par105_days_since_last_top_up'] <= 180).astype(float)
a['away_from_main_station_per_decl_24m_rate'] = 1.0 - d['main_station_share']

# example: one taxpayer's yearly counts and the rate they give
i = d['y1_entries'].fillna(0).gt(20).idxmax()
print('Example TIN', d.loc[i, 'taxpayer_tin'])
print(d.loc[i, ['y1_entries', 'y1_topped_up', 'y2_entries', 'y2_topped_up', 'y3_entries', 'y3_topped_up']].to_string())
print('rate =', round(a.loc[i, 'topped_up_per_decl_3y_rate'], 4))
a.describe().round(3)
""")

md("""
**Small numbers.** One top-up in 2 declarations is a 50% rate but says little. Each rate is pulled towards
everyone's average with the weight n / (n + 10), where n is the taxpayer's declarations (items compared, for the
price shortfall). It only ever lowers a rate, so a clean small trader never takes on other people's behaviour. The
value before this step is kept as `raw_<name>`.
""")
code(r"""
def credibility(rate, n, k=10):
    rate = rate.astype(float)
    n = n.fillna(0).astype(float)
    has_value = rate.notna() & (n > 0)
    average = (rate[has_value] * n[has_value]).sum() / max(n[has_value].sum(), 1)
    weight = n / (n + k)
    return np.minimum(rate, weight * rate + (1 - weight) * average)


TRACK_A = list(N.TRACK_A_NAMES.values())
for c in TRACK_A:
    a['raw_' + c] = a[c]
    n = d['items_benchmarked'] if c == 'peer_price_shortfall_per_value_24m_rate' else d['entries_24m']
    a[c] = credibility(a[c], n)

# what the step does to the smallest traders
show = a.assign(decl_24m_count=d['entries_24m'])
show.sort_values('decl_24m_count')[['taxpayer_tin', 'decl_24m_count', 'raw_topped_up_per_decl_3y_rate',
                                    'topped_up_per_decl_3y_rate']].head(10)
""")

md("""
### 6.4 Track B: behaviour (17 features)

Only what the taxpayer declared, nothing customs did (no top-ups, no lanes). Over the 24 months. The five rates that
rest on a count get the same small-numbers step; the rest are used as they are or worked out from two columns.
""")
code(r"""
b = pd.DataFrame({'taxpayer_tin': d['taxpayer_tin']})

# rates with the small-numbers step
b['amended_per_decl_24m_rate'] = credibility(d['par045_amended_entry_rate'], d['entries_24m'])
b['unpaid_tax_per_decl_24m_rate'] = credibility(d['ctx_unpaid_rate'], d['entries_24m'])
b['price_keying_error_per_item_24m_rate'] = credibility(d['ctx_implausible_price_rate'], d['items_benchmarked'])
b['peer_price_shortfall_per_value_24m_rate'] = credibility(d['par076_shortfall_share'], d['items_benchmarked'])
b['price_under_half_peer_per_item_24m_rate'] = credibility(d['par076_low_price_item_rate'], d['items_benchmarked'])

# used as they come from the SQL
b['median_price_dev_from_peer_24m_log'] = d['price_deviation_median']
b['own_price_drop_per_recent_value_6m_rate'] = d['own_price_drop_share']
b['duty_under_half_peer_per_value_24m_rate'] = d['low_duty_value_share']
b['duty_gap_vs_peer_per_value_24m_rate'] = d['duty_gap_share']
b['exempt_apc_per_value_24m_rate'] = d['exemption_apc_value_share']
b['watchlist_apc_per_value_24m_rate'] = d['watchlist_apc_value_share']
b['pref_claimed_per_item_24m_rate'] = d['ctx_preferential_use_rate']

# worked out from two columns
quarter_avg = d['entries_24m'] / 8.0                                     # 24 months = 8 quarters
b['decl_90d_per_avg_qtr_24m_log'] = np.log((d['entries_last_90d'] + 1) / (quarter_avg + 1))
b['away_from_main_station_per_decl_24m_rate'] = 1.0 - d['main_station_share']
b['hs4_per_decl_24m_ratio'] = d['hs_headings_used'] / d['entries_24m'].clip(lower=1)
b['same_day_split_per_decl_vs_norm_24m_diff'] = d['same_day_split_excess']
b['new_importer_24m_score'] = (-np.log1p(d['days_since_first_in_window'].clip(lower=0))
                               + np.where(d['new_trader'] == 'Y', 1.0, 0.0))

# check: the split excess is the split share minus the normal share
gap = (d['same_day_split_share'] - d['same_day_split_expected'] - d['same_day_split_excess']).abs().max()
print('split excess = share - normal share:', gap < 1e-6)
TRACK_B = list(N.TRACK_B_NAMES.values())
b[TRACK_B].describe().round(3).T
""")

md("""
### 6.5 Peer groups and percentiles (Track B)

Each Track B feature becomes a percentile within the taxpayer's peer group: importers of the same main goods (the
HS section of their main chapter) and size (thirds of customs value inside the section). "Higher than 97% of
similar importers" is fair across goods and sizes. A blank sits in the middle (0.5): no evidence either way.
""")
code(r"""
section = d['dominant_hs_chapter'].map(M.hs_section).fillna('Unknown')
log_value = np.log1p(d['total_customs_value'].clip(lower=0))
tier = log_value.groupby(section).transform(
    lambda v: pd.qcut(v.rank(method='first'), 3, labels=False) if len(v) >= 3 else 0)
peer_group = section + ', ' + tier.map({0: 'small', 1: 'medium', 2: 'large'})


def percentile_name(c):
    return 'b_' + c.rsplit('_', 1)[0] + '_pct'          # the unit at the end becomes pct


pct = pd.DataFrame({percentile_name(c): b[c].groupby(peer_group).rank(pct=True).fillna(0.5) for c in TRACK_B})
print(peer_group.nunique(), 'peer groups')
peer_group.value_counts().head(10)
""")

md("""
### 6.6 The final dataset

One row per taxpayer: who they are, the 8 Track A values the scorecard reads (and their `raw_` values before the
small-numbers step), the 17 Track B features (`b_`), their peer percentiles (`_pct`) and the outcomes (`out_`).
Saved to `data/eda_final/` for the Excel outputs in Part 7.
""")
code(r"""
final_dataset = pd.DataFrame({
    'taxpayer_tin': d['taxpayer_tin'],
    'taxpayer_nm': '',                                   # names are not in the extract
    'snapshot_date': d['snapshot_date'].astype(str).str[:10],
    'decl_24m_count': d['entries_24m'],
    'customs_value_24m_ugx': d['total_customs_value'],
    'limited_history': np.where(d['entries_24m'] < 10, 'Y', 'N'),
    'no_top_up_history': np.where(d['total_top_up'].fillna(0) <= 0, 'Y', 'N'),
    'peer_group': peer_group,
})
final_dataset = pd.concat([final_dataset, a[TRACK_A], a[['raw_' + c for c in TRACK_A]],
                           b[TRACK_B].add_prefix('b_'), pct, d[[c for c in d.columns if c.startswith('out_')]]], axis=1)

FINAL_FOLDER.mkdir(parents=True, exist_ok=True)
final_dataset.to_csv(FINAL_FOLDER / 'ctrp_final_dataset.csv', index=False)
print(final_dataset.shape)
final_dataset.head(10)
""")
code(r"""
# check: the same numbers as the production code (core.derive for Track A, discovery for Track B)
check_path = N.final_dataset_from_extract(EXTRACT, FINAL_FOLDER / 'production_check')
production = pd.read_csv(check_path, dtype={'taxpayer_tin': str})
mine = pd.read_csv(FINAL_FOLDER / 'ctrp_final_dataset.csv', dtype={'taxpayer_tin': str})
differ = []
for c in production.columns:
    x, y = mine[c], production[c]
    if pd.api.types.is_numeric_dtype(y):
        same = np.allclose(x.astype(float), y.astype(float), rtol=1e-9, atol=1e-12, equal_nan=True)
    else:
        same = x.fillna('').astype(str).equals(y.fillna('').astype(str))
    if not same:
        differ.append(c)
print(f'{len(production.columns)} columns compared with production:', 'all the same' if not differ else differ)
""")
code(r"""
# one taxpayer, every feature: the one with the most declarations
final_dataset.sort_values('decl_24m_count').iloc[-1].to_frame('value')
""")
code(r"""
# each feature's spread (the top and bottom 1% left out so a few extreme values do not hide the shape)
features = TRACK_A + ['b_' + c for c in TRACK_B]
fig, axes = plt.subplots(int(np.ceil(len(features) / 5)), 5, figsize=(18, 2.6 * np.ceil(len(features) / 5)))
for ax, c in zip(axes.flat, features):
    v = final_dataset[c].dropna()
    if len(v):
        v = v.clip(v.quantile(0.01), v.quantile(0.99))
        ax.hist(v, bins=40, color='#1F4FD8')
    ax.set_title(c, fontsize=8)
for ax in list(axes.flat)[len(features):]:
    ax.axis('off')
plt.tight_layout()
plt.show()
""")

# ------------------------------------------------------------------------------------------- 7
md("""
## 7. The Excel outputs

* `results/CTRP_EDA_report_2026-09-30.xlsx`: Parts 1, 2 and 4 in one workbook.
* `results/eda_issues/CTRP_EDA_E01_....xlsx`: one per problem. Sheets: **Issue** (what we saw, what the model
  does, how to search and how to check it, the verdict), **Entry list** (one row per entry: entry number, station,
  year, declaration IDs, dates, taxpayer, consignee, APCs, tax and flags, with a verdict per entry),
  **Taxpayers** (one row per TIN) and **Item rows** (every row behind the entries, as the view returned them).
* `results/CTRP_final_dataset_2026-09-30.xlsx`: the final dataset, the 22 features and the names.
""")
code("""
H.build()
written = N.build_excel(FINAL_FOLDER)      # the 10 problem workbooks and the final dataset workbook
""")

nb = nbf.v4.new_notebook()
nb['cells'] = cells
nb['metadata'] = {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                  'language_info': {'name': 'python'}}
out = Path(__file__).parent / 'CTRP_EDA_report.ipynb'
nbf.write(nb, out)
print(f'written {out} ({len(cells)} cells)')
