"""
Ethan's own copy of the EDA and features note, written in a plain, step-by-step style.

What: writes notebooks/zeppelin/CTRP_EDA_and_features_mine.zpln. It does exactly what the review note
      (eda_note.py) does and gives the same numbers, but the code is written the way a student would write it:
      one step at a time, plain variable names, .show() and print() after each step, no helper tricks. Each of
      the 13 data problems has its own section: what it is in plain words, the code that finds it, the evidence
      (counts and example rows from the view), and what the model does about it.
Why:  so Ethan can read, run and explain every line himself.

    python main.py eda-note        (writes both notes)
"""
import json

from ctrp import eda_note as N
from ctrp.utils import PROJECT_ROOT

OUT_NOTE = PROJECT_ROOT / 'notebooks' / 'zeppelin' / 'CTRP_EDA_and_features_mine.zpln'
PARAGRAPHS = []


def md(title, text):
    PARAGRAPHS.append((title, '%md\n' + text.strip()))


def py(title, text):
    PARAGRAPHS.append((title, '%pyspark\n' + text.strip()))


md('Title', r"""
# My CTRP notebook: exploring the data and building the features

Same steps and same numbers as the review note "CTRP EDA and features", written step by step.

Feature names say what is measured, per what, over which window, and end with the unit, for example
`topped_up_per_decl_3y_rate`. Short forms: decl, peer (other importers' middle price), hs4, coo, exempt, pref, dev,
avg, qtr. Track B columns start with `b_`, percentiles end with `pct`, Track A values before the small-numbers step
start with `raw_`.

1. Settings and setup
2. Load the data from the view
3. Explore it: size, missing data, duplicates, values
4. The 13 data problems, one by one, with evidence
5. Clean the data
6. Declarations
7. Track A features (8)
8. Track B features (17)
9. Recency, small numbers, peer groups
10. The final dataset
""")

py('Settings', r"""
# ---------- settings (the only cell to change) ----------
SNAPSHOT = '__LIVE__'          # the date the risk profile is made
WITH_OUTCOMES = False              # True for a past date: also count what happened in the 6 months after
SAMPLE_1_IN = None                 # 20 = try it on 1 in 20 taxpayers first. None = everyone

EXCLUDE_APC_483 = __APC483__              # rule R13
LATEST_DECLARATION_PER_ENTRY = __R14__    # rule R14
EXCLUDE_MOTOR_VEHICLES = __R15__          # rule R15
MOTOR_VEHICLE_HEADINGS = __MV__

SAVE_TO_FOLDER = False             # True = also write CSV files to OUT_DIR
OUT_DIR = '/user/CHANGE_ME/ctrp_eda_mine'
SAVE_TO_SCHEMA = None              # a Hive schema I can write to, if I get one

VIEW = 'dm_modeled_ura_datascience.vw_cstm_AEO_model'
""")

py('Setup', r"""
import datetime
import calendar
import numpy as np
import pandas as pd
import pyspark.sql.functions as F
from pyspark.sql.window import Window


def month_end(date_text, months):
    # last day of the month that is `months` away from the date (negative = before)
    d = datetime.datetime.strptime(date_text, '%Y-%m-%d').date()
    total_months = d.year * 12 + d.month - 1 + months
    year = total_months // 12
    month = total_months % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, last_day)


# the view stores dates as text like '20260930', so I keep my dates in the same format
SNAP = datetime.datetime.strptime(SNAPSHOT, '%Y-%m-%d').strftime('%Y%m%d')
HIST_START = month_end(SNAPSHOT, -24).strftime('%Y%m%d')     # features: 24 months
HIST3_START = month_end(SNAPSHOT, -36).strftime('%Y%m%d')    # recency: 36 months
PRIOR_START = month_end(SNAPSHOT, -60).strftime('%Y%m%d')    # new trader check: the 3 years before that
if WITH_OUTCOMES:
    OUT_END = month_end(SNAPSHOT, 6).strftime('%Y%m%d')
else:
    OUT_END = SNAP
snap_date = F.to_date(F.lit(SNAPSHOT))


def save_table(df, name):
    # keep a result as a table in this session (and write it out if switched on)
    if isinstance(df, pd.DataFrame):
        df = spark.createDataFrame(df)
    df.createOrReplaceTempView(name)
    if SAVE_TO_FOLDER:
        df.coalesce(1).write.mode('overwrite').option('header', True).csv(OUT_DIR + '/' + name)
    if SAVE_TO_SCHEMA:
        df.write.mode('overwrite').saveAsTable(SAVE_TO_SCHEMA + '.' + name)


print('snapshot', SNAP, '| features from', HIST_START, '| recency from', HIST3_START, '| data up to', OUT_END)
""")

# ------------------------------------------------------------------------------------------- load
md('1. Load', r"""
## 1. Load the data

One row in the view = one item on one declaration. I take the columns I need for the 3 years before the
snapshot, give each its type, and add two columns:
* `adate`: the assessment date as a real date
* `entry_key`: entry number + station + year (for example `C12345UGKLA2026`). If any part is blank I use the
  declaration ID instead.
""")

py('1. Load', r"""
view = spark.table(VIEW)

df = view.select(
    # IDs and codes: kept as text so nothing loses its leading zeros
    F.col('instance_id').cast('string').alias('instance_id'),
    F.col('entry_num').cast('string').alias('entry_num'),
    F.col('dec_ref_yer').cast('string').alias('dec_ref_yer'),
    F.col('clearance_station_cd').cast('string').alias('clearance_station_cd'),
    F.col('taxpayer_tin').cast('string').alias('taxpayer_tin'),
    F.col('taxpayer_nm').cast('string').alias('taxpayer_nm'),
    F.col('consignee_tin').cast('string').alias('consignee_tin'),
    F.col('consignee_nm').cast('string').alias('consignee_nm'),
    F.col('hsc_cd').cast('string').alias('hsc_cd'),
    F.col('gds_org_cty').cast('string').alias('gds_org_cty'),
    F.col('cpc_cd').cast('string').alias('cpc_cd'),
    F.col('extended_proc_cd').cast('string').alias('extended_proc_cd'),
    F.col('regime_cd').cast('string').alias('regime_cd'),
    F.col('decl_status').cast('string').alias('decl_status'),
    F.col('pay_status').cast('string').alias('pay_status'),
    F.col('key_itm_nbr').cast('string').alias('key_itm_nbr'),
    F.col('top_up_flg').cast('string').alias('top_up_flg'),
    F.col('amendment_flg').cast('string').alias('amendment_flg'),
    F.col('preferential_treatment_flag').cast('string').alias('preferential_treatment_flag'),
    F.col('assessment_dt_wid').cast('string').alias('assessment_dt_wid'),
    # money, weight and units: numbers
    F.col('customs_value').cast('double').alias('customs_value'),
    F.col('net_weight').cast('double').alias('net_weight'),
    F.col('supplementary_qnty').cast('double').alias('supplementary_qnty'),
    F.col('tax_assessed').cast('double').alias('tax_assessed'),
    F.col('original_tax_amt').cast('double').alias('original_tax_amt'),
    F.col('final_amt').cast('double').alias('final_amt'),
    F.col('top_up_amt').cast('double').alias('top_up_amt'),
    # lanes: 1 = selected
    F.col('is_red_flg').cast('int').alias('is_red_flg'),
    F.col('is_yellow_flg').cast('int').alias('is_yellow_flg'),
)

# keep the 3 years before the snapshot (and the outcome months if asked)
df = df.filter((F.col('assessment_dt_wid') > HIST3_START) & (F.col('assessment_dt_wid') <= OUT_END))

df = df.withColumn('adate', F.to_date('assessment_dt_wid', 'yyyyMMdd'))
entry_key = F.concat('entry_num', 'clearance_station_cd', 'dec_ref_yer')      # blank if any part is blank
df = df.withColumn('entry_key', F.coalesce(entry_key, F.col('instance_id')))

if SAMPLE_1_IN:
    df = df.filter(F.pmod(F.hash('taxpayer_tin'), SAMPLE_1_IN) == 0)

df = df.cache()
n_loaded = df.count()
print('rows loaded:', n_loaded)
df.show(5)
""")

# ------------------------------------------------------------------------------------------- explore
md('2. Explore', r"""
## 2. Explore the data

For the exploration I look at the same window the features use: IM4 and IM7, the 24 months before the snapshot.
""")

py('2.1 Size', r"""
eda = df.filter((F.col('assessment_dt_wid') > HIST_START) & (F.col('assessment_dt_wid') <= SNAP))
eda = eda.filter(F.col('regime_cd').isin('IM4', 'IM7'))

print('Rows, declarations, entries and taxpayers per year:')
eda.groupBy(F.substring('assessment_dt_wid', 1, 4).alias('year')).agg(
    F.count('*').alias('rows'),
    F.countDistinct('instance_id').alias('declarations'),
    F.countDistinct('entry_key').alias('entries'),
    F.countDistinct('taxpayer_tin').alias('taxpayers'),
).orderBy('year').show()
""")

md('2.2 Missing data', r"""
## 2.2 Missing data

For each column: how many rows are blank, and (for numbers) how many are zero or less. Then the same per year,
to see if it is getting better or worse, and a test of what a blank original tax means.
""")

py('2.2 Missing data', r"""
BLANK_MEANS = __BLANK_MEANS__

text_columns = ['taxpayer_tin', 'entry_num', 'clearance_station_cd', 'dec_ref_yer', 'decl_status', 'regime_cd',
                'hsc_cd', 'gds_org_cty', 'cpc_cd', 'top_up_flg', 'amendment_flg', 'pay_status',
                'preferential_treatment_flag', 'assessment_dt_wid']
number_columns = ['customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt',
                  'final_amt', 'top_up_amt', 'is_red_flg', 'is_yellow_flg']

n = eda.count()
results = []
for c in text_columns + number_columns:
    blank = eda.filter(F.col(c).isNull()).count()
    results.append([c, blank, round(100.0 * blank / n, 2), BLANK_MEANS.get(c, '')])
missing = pd.DataFrame(results, columns=['column', 'blank rows', 'blank %', 'what the model does'])
print(missing.sort_values('blank %', ascending=False).to_string(index=False))
""")

py('2.2 Zero or negative numbers', r"""
for c in ['customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt', 'final_amt']:
    filled = eda.filter(F.col(c).isNotNull()).count()
    zero_or_less = eda.filter(F.col(c) <= 0).count()
    print(c, ': zero or less in', zero_or_less, 'of', filled, 'filled rows (%.2f%%)' % (100.0 * zero_or_less / max(filled, 1)))
""")

py('2.2 Missing by year', r"""
print('Blank % per year:')
eda.groupBy(F.substring('assessment_dt_wid', 1, 4).alias('year')).agg(
    F.round(100 * F.avg(F.col('original_tax_amt').isNull().cast('double')), 2).alias('original_tax'),
    F.round(100 * F.avg(F.col('hsc_cd').isNull().cast('double')), 2).alias('hs_code'),
    F.round(100 * F.avg(F.col('gds_org_cty').isNull().cast('double')), 2).alias('origin'),
    F.round(100 * F.avg(F.col('supplementary_qnty').isNull().cast('double')), 2).alias('units'),
    F.round(100 * F.avg(F.col('net_weight').isNull().cast('double')), 2).alias('weight'),
    F.round(100 * F.avg(F.col('cpc_cd').isNull().cast('double')), 2).alias('apc'),
    F.round(100 * F.avg(F.col('entry_num').isNull().cast('double')), 2).alias('entry_number'),
).orderBy('year').show()
""")

py('2.2 Original tax blank', r"""
# If "blank original tax = unchanged" is right, declarations WITH a top-up flag should almost never be blank
one_row_per_declaration = eda.groupBy('instance_id').agg(
    F.max('top_up_flg').alias('top_up_flag'),
    F.max('original_tax_amt').alias('original_tax'),
)
one_row_per_declaration.groupBy('top_up_flag').agg(
    F.count('*').alias('declarations'),
    F.round(100 * F.avg(F.col('original_tax').isNull().cast('double')), 1).alias('original tax blank %'),
).show()
""")

md('2.3 Duplicates', r"""
## 2.3 Duplicates

Four kinds: the same row copied, the same item repeated, the same entry under two or more declaration IDs, and one
declaration ID with more than one taxpayer or date.
""")

py('2.3 Duplicates', r"""
n_rows = eda.count()
n_different_rows = eda.distinct().count()
n_items = eda.select('instance_id', 'key_itm_nbr').distinct().count()
print('rows:', n_rows)
print('rows that are an exact copy of another row:', n_rows - n_different_rows)
print('rows that repeat an item (same declaration ID + item number):', n_rows - n_items)

# are the copies of each item identical? count the different versions of each item
versions = eda.distinct().groupBy('instance_id', 'key_itm_nbr').count()
print('items whose copies are NOT identical:', versions.filter(F.col('count') > 1).count())

copies = eda.groupBy('instance_id', 'key_itm_nbr').count()
print('most copies of one item:', copies.agg(F.max('count')).first()[0])

ids_per_entry = eda.groupBy('entry_key').agg(F.countDistinct('instance_id').alias('ids'))
print('entries under more than one declaration ID:', ids_per_entry.filter(F.col('ids') > 1).count())

per_id = eda.groupBy('instance_id').agg(F.countDistinct('taxpayer_tin').alias('tins'),
                                        F.countDistinct('assessment_dt_wid').alias('dates'))
print('declaration IDs with more than one TIN (expected 0):', per_id.filter(F.col('tins') > 1).count())
print('declaration IDs with more than one date (expected 0):', per_id.filter(F.col('dates') > 1).count())

print('The items with the most copies:')
copies.orderBy(F.desc('count')).show(5)
""")

py('2.4 Values, lanes, top-ups', r"""
print('Customs value per item (middle 50% and the extremes):')
eda.select(
    F.expr('percentile_approx(customs_value, 0.01)').alias('p1'),
    F.expr('percentile_approx(customs_value, 0.5)').alias('median'),
    F.expr('percentile_approx(customs_value, 0.99)').alias('p99'),
).show()

declarations = eda.groupBy('instance_id').agg(F.max('is_red_flg').alias('red'), F.max('is_yellow_flg').alias('yellow'),
                                              F.max('top_up_flg').alias('top_up_flag'))
declarations.select(
    F.count('*').alias('declarations'),
    F.avg((F.col('red') == 1).cast('double')).alias('share red'),
    F.avg((F.col('yellow') == 1).cast('double')).alias('share yellow'),
    F.avg((F.col('top_up_flag') == 'Y').cast('double')).alias('share top-up flag Y'),
).show()
""")

# ------------------------------------------------------------------------------------------- 13 problems
md('3. The 13 problems', r"""
## 3. The 13 data problems

For each problem: what it is, the code that finds it, the evidence (how many, and example rows), and what the model
does about it. Each problem's rows are kept as a table `ctrp_eda_e01` ... `ctrp_eda_e13` for the Risk Officers.

| | Problem | Type |
|---|---|---|
| E01 | One entry saved under two or more declaration IDs | duplicate |
| E02 | The same item row repeated, sometimes hundreds of times | duplicate |
| E03 | TIN blank or not 10 digits | missing or wrong |
| E04 | Cancelled declarations still in the view | not trade |
| E05 | APC 483: destroyed or abandoned goods and dummy entries | not trade |
| E06 | Top-up flag says Y, but the tax did not go up | contradiction |
| E07 | Tax went up, but there is no top-up flag | contradiction |
| E08 | Original tax is blank | missing |
| E09 | `top_up_amt` holds the final tax, not the top-up | wrong column |
| E10 | A declaration marked both red and yellow | contradiction |
| E11 | Value or weight is zero, negative or blank | missing or wrong |
| E12 | Price per kg under 1% of what others declare (weight in the wrong unit) | keying error |
| E13 | One TIN with several taxpayer names | duplicate identity |
""")

py('3.0 Setup for the problems', r"""
# the columns the officers need to judge an entry
DETAIL = __DETAIL__
eda_rows = eda.select(DETAIL)

# one row per declaration, for the tax and lane problems
eda_declarations = eda_rows.groupBy('entry_key', 'instance_id').agg(
    F.max('top_up_flg').alias('flag'),
    F.max('original_tax_amt').alias('orig_raw'),
    F.max('final_amt').alias('fin'),
    F.max('top_up_amt').alias('top_up_amt_max'),
    F.max('is_red_flg').alias('red'),
    F.max('is_yellow_flg').alias('yellow'),
)
eda_declarations = eda_declarations.withColumn('orig', F.coalesce('orig_raw', 'fin')).cache()

SHOW = ['entry_key', 'instance_id', 'key_itm_nbr', 'assessment_dt_wid', 'taxpayer_tin', 'hsc_cd', 'customs_value',
        'net_weight', 'original_tax_amt', 'final_amt', 'top_up_amt', 'top_up_flg', 'is_red_flg', 'is_yellow_flg']
problems = {}      # problem code -> (title, entries, rows, sampled 1 in K)


def all_rows_of(declaration_ids):
    # every item row of these declarations
    ids = declaration_ids.select('instance_id').distinct()
    return eda_rows.join(ids, 'instance_id', 'left_semi').select(DETAIL)


def keep_1_in(rows, k):
    # for very big problems, keep a random 1 in k of the entries (all rows of each entry)
    if k == 1:
        return rows
    return rows.filter(F.pmod(F.hash('entry_key'), k) == 0)


def report(code, title, rows, k=1):
    rows = rows.cache()
    n_entries = rows.select('entry_key').distinct().count()
    n_rows = rows.count()
    problems[code] = (title, n_entries, n_rows, k)
    save_table(rows, 'ctrp_eda_' + code.lower())
    sample_note = '' if k == 1 else ' (a random 1 in %d of the entries, so about %d entries in all)' % (k, k * n_entries)
    print('%s %s: %d entries, %d rows%s' % (code, title, n_entries, n_rows, sample_note))
""")

PROBLEMS = [
    ('E01', 'One entry under several declaration IDs', r"""
**What it is.** An entry is identified by entry number + station + year. Some entries appear under two or more
declaration IDs, so the same entry would be counted twice.

**What the model does.** Rule R14: keep only the latest (highest) declaration ID of each entry.
""", r"""
ids_per_entry = eda_rows.groupBy('entry_key').agg(F.countDistinct('instance_id').alias('declaration_ids_on_entry'))
entries_with_several_ids = ids_per_entry.filter(F.col('declaration_ids_on_entry') > 1)
e01 = entries_with_several_ids.join(eda_rows, 'entry_key').select(['declaration_ids_on_entry'] + DETAIL)
report('E01', 'One entry under several declaration IDs', e01)

print('Evidence: how many IDs an entry has')
ids_per_entry.groupBy('declaration_ids_on_entry').count().orderBy('declaration_ids_on_entry').show()
print('Example: one entry and its declaration IDs')
e01.select(SHOW).orderBy('entry_key', 'instance_id').show(10, truncate=False)
"""),
    ('E02', 'The same item row repeated', r"""
**What it is.** The same declaration and item number appear many times (up to 412 copies). The view joins three
tables on the declaration ID only (header, items, inspection actions), so a repeat in any of them repeats the item.
The copies are identical in every column the model uses.

**What the model does.** Rule R5: each item is kept once.
""", r"""
copies = eda_rows.groupBy('instance_id', 'key_itm_nbr').agg(F.count('*').alias('copies_of_item'))
repeated = copies.filter(F.col('copies_of_item') > 1)
e02 = repeated.join(eda_rows, ['instance_id', 'key_itm_nbr']).select(['copies_of_item'] + DETAIL)
report('E02', 'The same item row repeated', e02)

print('Evidence: the most repeated items')
repeated.orderBy(F.desc('copies_of_item')).show(5)

print('Where do the copies come from? The view joins each item to every inspection action on its declaration.')
print('If that explains it, an item has as many copies as its declaration has inspection actions (1 if none).')
day = F.col('assessment_dt_wid').cast('string')
view_rows = spark.table(VIEW).filter((day > HIST_START) & (day <= SNAP) & F.col('regime_cd').isin('IM4', 'IM7'))
view_rows = view_rows.select(F.col('instance_id').cast('string').alias('instance_id'),
                             F.col('key_itm_nbr').cast('string').alias('key_itm_nbr'),
                             F.col('taxpayer_tin').cast('string').alias('taxpayer_tin'),
                             'sad_sid', 'op_date_time', 'inf')
if SAMPLE_1_IN:
    view_rows = view_rows.filter(F.pmod(F.hash('taxpayer_tin'), SAMPLE_1_IN) == 0)

with_action = view_rows.filter(F.col('sad_sid').isNotNull() | F.col('op_date_time').isNotNull() | F.col('inf').isNotNull())
actions = with_action.groupBy('instance_id').agg(
    F.size(F.collect_set(F.struct('sad_sid', 'op_date_time', 'inf'))).alias('inspection_actions'))
per_item = view_rows.groupBy('instance_id', 'key_itm_nbr').agg(F.count('*').alias('copies'))
per_item = per_item.join(actions, 'instance_id', 'left').fillna(0, subset=['inspection_actions'])
repeated_items = per_item.filter(F.col('copies') > 1)
explained = repeated_items.filter(F.col('copies') == F.greatest('inspection_actions', F.lit(1))).count()
print('repeated items:', repeated_items.count(), '| explained by inspection actions:', explained)
repeated_items.orderBy(F.desc('copies')).show(5)
"""),
    ('E03', 'TIN blank or not 10 digits', r"""
**What it is.** A valid TIN has 10 digits. Some declarations have a blank, short or malformed TIN.

**What the model does.** Rule R1: only 10-digit TINs are scored.
""", r"""
good_tin = F.coalesce(F.col('taxpayer_tin'), F.lit('')).rlike('^[0-9]{10}$')
e03 = eda_rows.filter(~good_tin)
report('E03', 'TIN blank or not 10 digits', e03)

print('Evidence: the bad TINs and how often they appear')
e03.groupBy('taxpayer_tin').count().orderBy(F.desc('count')).show(10)
"""),
    ('E04', 'Cancelled declarations', r"""
**What it is.** Declarations with status Cancelled are still in the view. They are not trade.

**What the model does.** Rule R3: cancelled declarations are left out (a blank status is left out too).
""", r"""
e04 = all_rows_of(eda_rows.filter(F.col('decl_status') == 'Cancelled'))
report('E04', 'Cancelled declarations', e04)

print('Evidence: declarations by status')
eda_rows.groupBy('decl_status').agg(F.countDistinct('instance_id').alias('declarations')).show()
"""),
    ('E05', 'APC 483 (destroyed or abandoned goods, dummy entries)', r"""
**What it is.** The CPC memo describes APC 483 as destroyed or abandoned goods and dummy reconciliation entries,
not trade.

**What the model does.** Rule R13: declarations under APC 483 are left out.
""", r"""
e05 = all_rows_of(eda_rows.filter(F.col('cpc_cd') == '483'))
report('E05', 'APC 483 (destroyed or abandoned goods, dummy entries)', e05)

print('Evidence: some APC 483 items')
e05.select(SHOW + ['cpc_cd']).show(5, truncate=False)
"""),
    ('E06', 'Top-up flag Y, but the tax did not go up', r"""
**What it is.** The top-up flag is Y, but the final tax is not above the original tax.

**What the model does.** Rule R7: a top-up counts only when the flag is Y **and** the final tax is above the
original tax.
""", r"""
flag_but_no_rise = (F.col('flag') == 'Y') & ~(F.col('fin') > F.col('orig'))
e06 = all_rows_of(eda_declarations.filter(flag_but_no_rise))
report('E06', 'Top-up flag Y, but the tax did not go up', e06)

print('Evidence: some of these declarations')
eda_declarations.filter(flag_but_no_rise).show(5)
"""),
    ('E07', 'Tax went up, but no top-up flag', r"""
**What it is.** The final tax is above the original tax, but there is no top-up flag (about 3,000 amended
declarations in our earlier check).

**What the model does.** Not counted as top-ups, because the flag is customs' own marking. To be confirmed by
the officers.
""", r"""
no_flag = F.coalesce(F.col('flag'), F.lit('N')) != 'Y'
rise_without_flag = no_flag & F.col('orig_raw').isNotNull() & (F.col('fin') > F.col('orig_raw'))
e07 = all_rows_of(eda_declarations.filter(rise_without_flag))
report('E07', 'Tax went up, but no top-up flag', e07)

print('Evidence: some of these declarations')
eda_declarations.filter(rise_without_flag).show(5)
"""),
    ('E08', 'Original tax is blank', r"""
**What it is.** The original tax is blank on many declarations (about 37% of those without a top-up, in our
earlier check). Section 2.2 shows it is rarely blank when there is a top-up.

**What the model does.** Blank is read as "unchanged": the final tax is used. This is our reading, not stated in
the data. Big problem, so the table keeps a random 1 in 50 of the entries.
""", r"""
e08 = keep_1_in(all_rows_of(eda_declarations.filter(F.col('orig_raw').isNull())), 50)
report('E08', 'Original tax is blank', e08, 50)

print('Evidence: blank original tax, by top-up flag')
eda_declarations.groupBy('flag').agg(
    F.count('*').alias('declarations'),
    F.round(100 * F.avg(F.col('orig_raw').isNull().cast('double')), 1).alias('blank %')).show()
"""),
    ('E09', 'top_up_amt holds the final tax, not the top-up', r"""
**What it is.** On declarations without a top-up, the `top_up_amt` column usually equals the final tax (99.5% of
the time in our earlier check), so it is not a top-up amount.

**What the model does.** `top_up_amt` is not used. Top-up = final tax minus original tax. The table keeps a random
1 in 50 of the entries.
""", r"""
no_flag = F.coalesce(F.col('flag'), F.lit('N')) != 'Y'
column_is_final_tax = no_flag & (F.col('top_up_amt_max') == F.col('fin')) & (F.col('fin') > 0)
e09 = keep_1_in(all_rows_of(eda_declarations.filter(column_is_final_tax)), 50)
report('E09', 'top_up_amt holds the final tax, not the top-up', e09, 50)

no_top_up = eda_declarations.filter(no_flag & (F.col('fin') > 0))
same = no_top_up.filter(F.col('top_up_amt_max') == F.col('fin')).count()
print('Evidence: on declarations without a top-up flag, top_up_amt equals the final tax on %d of %d (%.1f%%)'
      % (same, no_top_up.count(), 100.0 * same / max(no_top_up.count(), 1)))
"""),
    ('E10', 'Both red and yellow lane', r"""
**What it is.** A declaration can carry both the red and the yellow flag.

**What the model does.** Rule R12: a declaration counts as checked once if either flag is 1. The table keeps a
random 1 in 5 of the entries.
""", r"""
both_lanes = (F.col('red') == 1) & (F.col('yellow') == 1)
e10 = keep_1_in(all_rows_of(eda_declarations.filter(both_lanes)), 5)
report('E10', 'Both red and yellow lane', e10, 5)

print('Evidence: declarations by lane')
eda_declarations.groupBy('red', 'yellow').count().orderBy('red', 'yellow').show()
"""),
    ('E11', 'Value or weight zero, negative or blank', r"""
**What it is.** A few items have no customs value or no weight, so a price per kg cannot be worked out.

**What the model does.** Rule R8: such items are left out of the price features. They still count in their
declaration.
""", r"""
no_value = F.coalesce('customs_value', F.lit(0)) <= 0
no_weight = F.coalesce('net_weight', F.lit(0)) <= 0
e11 = all_rows_of(eda_rows.filter(no_value | no_weight))
report('E11', 'Value or weight zero, negative or blank', e11)

print('Evidence: items with no value:', eda_rows.filter(no_value).count(), '| items with no weight:',
      eda_rows.filter(no_weight).count())
"""),
    ('E12', 'Price per kg under 1% of other importers', r"""
**What it is.** Some items are priced at under 1% of the middle price other importers declare for the same HS code.
Most likely a weight or quantity typed in the wrong unit.

**What the model does.** Rule R9: these are treated as keying errors, counted separately
(`price_keying_error_per_item_24m_rate`) and kept out of the undervaluation measure.
""", r"""
priced = eda_rows.filter((F.col('customs_value') > 0) & (F.col('net_weight') > 0))
middle_price = priced.groupBy('hsc_cd').agg(
    F.expr('percentile_approx(customs_value / net_weight, 0.5)').alias('med_kg'),
    F.countDistinct('taxpayer_tin').alias('importers'))
middle_price = middle_price.filter(F.col('importers') >= 5)
too_cheap = priced.join(middle_price, 'hsc_cd').filter(F.col('customs_value') / F.col('net_weight') < 0.01 * F.col('med_kg'))
e12 = all_rows_of(too_cheap)
report('E12', 'Price per kg under 1% of other importers', e12)

print('Evidence: some of these items, with their price per kg and the middle price')
too_cheap.select('instance_id', 'hsc_cd', 'customs_value', 'net_weight',
                 (F.col('customs_value') / F.col('net_weight')).alias('price_per_kg'), 'med_kg').show(5)
"""),
    ('E13', 'One TIN with several taxpayer names', r"""
**What it is.** Names are typed with variations (addresses mixed in, stray characters), so some TINs carry three or
more names.

**What the model does.** Names are not used; the TIN identifies the taxpayer. The officers are asked to confirm
none of these TINs is shared by different businesses.
""", r"""
names_per_tin = eda_rows.groupBy('taxpayer_tin').agg(F.countDistinct('taxpayer_nm').alias('names'))
tins_with_many_names = names_per_tin.filter(F.col('names') >= 3)
e13 = eda_rows.join(tins_with_many_names, 'taxpayer_tin', 'left_semi').groupBy('taxpayer_tin', 'taxpayer_nm').agg(
    F.countDistinct('instance_id').alias('declarations'),
    F.min('assessment_dt_wid').alias('first_seen'),
    F.max('assessment_dt_wid').alias('last_seen'),
    F.countDistinct('clearance_station_cd').alias('stations'),
    F.max('entry_key').alias('an_entry_key'))
e13 = e13.cache()
problems['E13'] = ('One TIN with several taxpayer names', tins_with_many_names.count(), e13.count(), 1)
save_table(e13, 'ctrp_eda_e13')
print('E13: %d TINs with 3 or more names, %d rows' % (problems['E13'][1], problems['E13'][2]))
e13.orderBy('taxpayer_tin').show(10, truncate=False)
"""),
]

for code, title, explain, code_text in PROBLEMS:
    md(f'{code} {title}', f'### {code}: {title}\n\n' + explain.strip())
    py(f'{code} {title}', code_text)

py('3.14 Summary of the problems', r"""
summary = pd.DataFrame([[code] + list(problems[code]) for code in sorted(problems)],
                       columns=['issue', 'title', 'entries_or_taxpayers', 'rows', 'sample_1_in'])
save_table(summary, 'ctrp_eda_summary')
print(summary.to_string(index=False))
""")

# ------------------------------------------------------------------------------------------- clean
md('4. Clean', r"""
## 4. Clean the data

One rule at a time, printing how many rows each one removes. A blank answer to a rule counts as a fail (for
example a blank status is removed with the cancelled ones).
""")

py('4. Clean', r"""
log = []
rows_now = n_loaded

# R1: TIN must be 10 digits
clean = df.filter(F.col('taxpayer_tin').rlike('^[0-9]{10}$'))
n = clean.count(); log.append(['R1', 'TIN must be 10 digits', rows_now, rows_now - n, n]); rows_now = n

# R3: drop cancelled declarations
clean = clean.filter(F.col('decl_status') != 'Cancelled')
n = clean.count(); log.append(['R3', 'drop cancelled declarations', rows_now, rows_now - n, n]); rows_now = n

# R4: imports only
clean = clean.filter(F.col('regime_cd').isin('IM4', 'IM7'))
n = clean.count(); log.append(['R4', 'imports only: IM4 (home use) and IM7 (bond)', rows_now, rows_now - n, n]); rows_now = n

# R13: drop APC 483
if EXCLUDE_APC_483:
    clean = clean.filter(F.coalesce(F.col('cpc_cd'), F.lit('')) != '483')
n = clean.count(); log.append(['R13', 'drop APC 483', rows_now, rows_now - n, n]); rows_now = n
clean = clean.cache()

# R14: keep the latest declaration ID of each entry (IDs padded with zeros so that '99' is not above '100')
if LATEST_DECLARATION_PER_ENTRY:
    padded_id = F.lpad('instance_id', 20, '0')
    clean = clean.withColumn('latest_id', F.max(padded_id).over(Window.partitionBy('entry_key')))
    clean = clean.filter(padded_id == F.col('latest_id')).drop('latest_id')
n = clean.count(); log.append(['R14', 'latest declaration ID per entry', rows_now, rows_now - n, n]); rows_now = n

# R15: drop every declaration that has a motor vehicle item
if EXCLUDE_MOTOR_VEHICLES:
    is_vehicle = F.when(F.substring('hsc_cd', 1, 4).isin(MOTOR_VEHICLE_HEADINGS), 1).otherwise(0)
    clean = clean.withColumn('has_vehicle', F.max(is_vehicle).over(Window.partitionBy('instance_id')))
    clean = clean.filter(F.col('has_vehicle') == 0).drop('has_vehicle')
n = clean.count(); log.append(['R15', 'drop motor vehicle declarations', rows_now, rows_now - n, n]); rows_now = n

# R5: keep each item once
copy_number = F.row_number().over(Window.partitionBy('instance_id', 'key_itm_nbr').orderBy('assessment_dt_wid'))
items = clean.withColumn('copy', copy_number).filter(F.col('copy') == 1).drop('copy').cache()
n = items.count(); log.append(['R5', 'keep each item once', rows_now, rows_now - n, n]); rows_now = n

cleaning_log = pd.DataFrame(log, columns=['rule', 'what it does', 'rows before', 'rows removed', 'rows left'])
save_table(cleaning_log, 'ctrp_cleaning_log')
print(cleaning_log.to_string(index=False))
""")

# ------------------------------------------------------------------------------------------- declarations
md('5. Declarations', r"""
## 5. Declarations

Tax, top-up, lane and status repeat on every item of a declaration, so I group items into one row per declaration.
* original tax blank = unchanged, so it takes the final tax (E08)
* topped up = flag Y **and** final tax above original tax (E06); top-up amount = final minus original (E09)
* tax reduced = final tax below original tax
* severe = top-up of 30% or more of the final tax
""")

py('5. Declarations', r"""
decl = items.groupBy('instance_id').agg(
    F.max('taxpayer_tin').alias('taxpayer_tin'),
    F.max('taxpayer_nm').alias('taxpayer_nm'),
    F.max('adate').alias('adate'),
    F.max('assessment_dt_wid').alias('dt'),
    F.max('regime_cd').alias('regime'),
    F.coalesce(F.max('original_tax_amt'), F.max('final_amt')).alias('orig_tax'),
    F.max('final_amt').alias('final_tax'),
    F.max('top_up_flg').alias('top_up_flg'),
    F.max('amendment_flg').alias('amended'),
    F.max('clearance_station_cd').alias('station'),
    F.max('is_red_flg').alias('red'),
    F.max('is_yellow_flg').alias('yellow'),
    F.max('pay_status').alias('pay_status'),
    F.sum('customs_value').alias('value'),
    F.count('*').alias('n_items'),
)

is_top_up = (F.col('top_up_flg') == 'Y') & (F.col('final_tax') > F.col('orig_tax'))
decl = decl.withColumn('topped_up', F.when(is_top_up, 1).otherwise(0))
decl = decl.withColumn('top_up', F.when(is_top_up, F.col('final_tax') - F.col('orig_tax')).otherwise(0.0))
decl = decl.withColumn('negative_top_up', F.when(F.col('final_tax') < F.col('orig_tax'), 1).otherwise(0))
is_severe = (F.col('topped_up') == 1) & (F.col('top_up') >= 0.30 * F.col('final_tax'))
decl = decl.withColumn('severe', F.when(is_severe, 1).otherwise(0))
decl = decl.cache()

# the 24 months the features use
hist = decl.filter((F.col('dt') > HIST_START) & (F.col('dt') <= SNAP)).cache()
hist_items = items.filter((F.col('assessment_dt_wid') > HIST_START) & (F.col('assessment_dt_wid') <= SNAP)).cache()
print('declarations in the 24 months:', hist.count())
hist.show(5)
""")

py('5.1 Taxpayers', r"""
# the starting table: one row per taxpayer
base = hist.groupBy('taxpayer_tin').agg(
    F.max(F.struct('dt', 'taxpayer_nm')).getField('taxpayer_nm').alias('taxpayer_nm'),   # name on the latest declaration
    F.count('*').alias('decl_24m_count'),
    F.sum('value').alias('customs_value_24m_ugx'),
    F.sum('orig_tax').alias('original_tax_24m_ugx'),
    F.sum('top_up').alias('top_up_24m_ugx'),
).cache()
print('taxpayers:', base.count())
base.show(5)
""")

# ------------------------------------------------------------------------------------------- Track A
md('6. Track A', r"""
## 6. Track A features (the scorecard)

Each one is a rate over the taxpayer's declarations in the 24 months. Section 8 then gives recent years more
weight and protects small traders.
""")

py('6.1 topped_up_per_decl_24m_rate', r"""
# PAR_045T: declarations topped up / declarations
top_up_rate = hist.groupBy('taxpayer_tin').agg(F.avg('topped_up').alias('topped_up_per_decl_24m_rate'))
top_up_rate.show(5)
""")

py('6.2 severe_top_up_per_decl_24m_rate', r"""
# PAR_077: severe top-ups (30% or more of the final tax) / declarations
severe_rate = hist.groupBy('taxpayer_tin').agg(F.avg('severe').alias('severe_top_up_per_decl_24m_rate'))
severe_rate.show(5)
""")

py('6.3 amended_per_decl_24m_rate', r"""
# PAR_045: amended declarations / declarations (also used in Track B)
amended_rate = hist.groupBy('taxpayer_tin').agg(
    F.avg(F.when(F.col('amended') == 'Y', 1.0).otherwise(0.0)).alias('amended_per_decl_24m_rate'))
amended_rate.show(5)
""")

py('6.4 top_up_per_final_tax_24m_rate', r"""
# PAR_048: top-ups / final tax (final tax = original tax + top-ups)
final_tax = F.col('original_tax_24m_ugx') + F.col('top_up_24m_ugx')
top_up_share = base.select('taxpayer_tin',
                           F.when(final_tax > 0, F.col('top_up_24m_ugx') / final_tax).alias('top_up_per_final_tax_24m_rate'))
top_up_share.show(5)
""")

py('6.5 tax_reduced_per_decl_24m_rate', r"""
# PAR_066: declarations whose tax was reduced / declarations
reduced_rate = hist.groupBy('taxpayer_tin').agg(F.avg('negative_top_up').alias('tax_reduced_per_decl_24m_rate'))
reduced_rate.show(5)
""")

py('6.6 top_up_last_180d_flag', r"""
# PAR_105: 1 if the last top-up was within 180 days of the snapshot
last_top_up = hist.groupBy('taxpayer_tin').agg(
    F.max(F.when(F.col('topped_up') == 1, F.col('adate'))).alias('last_top_up_date'))
recent_top_up = last_top_up.withColumn('days_since_last_top_up', F.datediff(snap_date, F.col('last_top_up_date')))
recent_top_up = recent_top_up.withColumn(
    'top_up_last_180d_flag', F.when(F.col('days_since_last_top_up') <= 180, 1.0).otherwise(0.0))
recent_top_up = recent_top_up.drop('last_top_up_date')
recent_top_up.show(5)
""")

py('6.7 away_from_main_station_per_decl_24m_rate', r"""
# PAR_023: 1 - share of declarations at the main (busiest) station
per_station = hist.groupBy('taxpayer_tin', 'station').count()
stations = per_station.groupBy('taxpayer_tin').agg((F.max('count') / F.sum('count')).alias('main_station_per_decl_24m_rate'))
stations = stations.withColumn('away_from_main_station_per_decl_24m_rate', 1.0 - F.col('main_station_per_decl_24m_rate'))
stations.show(5)
""")

py('6.8 peer_price_shortfall_per_value_24m_rate', r"""
# PAR_076: value missing on items priced under half the middle price of other importers / value
# step 1: price per kg and per unit
priced = hist_items.filter((F.col('customs_value') > 0) & (F.col('net_weight') > 0))
priced = priced.withColumn('price_kg', F.col('customs_value') / F.col('net_weight'))
priced = priced.withColumn('price_unit', F.when(F.col('supplementary_qnty') > 0,
                                                F.col('customs_value') / F.col('supplementary_qnty')))

# step 2: middle price per HS code, and per HS code + origin (5 or more importers each)
bench_hs = priced.groupBy('hsc_cd').agg(
    F.expr('percentile_approx(price_kg, 0.5)').alias('med_kg'),
    F.expr('percentile_approx(price_unit, 0.5)').alias('med_unit'),
    F.countDistinct('taxpayer_tin').alias('importers'))
bench_hs = bench_hs.filter(F.col('importers') >= 5).drop('importers')

bench_origin = priced.groupBy('hsc_cd', 'gds_org_cty').agg(
    F.expr('percentile_approx(price_kg, 0.5)').alias('med_kg_o'),
    F.expr('percentile_approx(price_unit, 0.5)').alias('med_unit_o'),
    F.countDistinct('taxpayer_tin').alias('importers'))
bench_origin = bench_origin.filter(F.col('importers') >= 5).drop('importers')

# step 3: each item gets its benchmark (the origin one where there is one)
it = priced.join(bench_hs, 'hsc_cd')
it = it.join(bench_origin, ['hsc_cd', 'gds_org_cty'], 'left')
has_origin_bench = F.col('med_kg_o').isNotNull()
it = it.withColumn('bm_kg', F.when(has_origin_bench, F.col('med_kg_o')).otherwise(F.col('med_kg')))
it = it.withColumn('bm_unit', F.when(has_origin_bench, F.col('med_unit_o')).otherwise(F.col('med_unit')))
it = it.withColumn('on_origin_bench', has_origin_bench.cast('int'))

# step 4: mark each item
units = F.col('supplementary_qnty')
low_per_unit_too = (F.col('bm_unit').isNull() | units.isNull() | (units <= 0)
                    | (F.col('customs_value') / units < 0.5 * F.col('bm_unit')))
it = it.withColumn('implausible', F.when(F.col('price_kg') < 0.01 * F.col('bm_kg'), 1).otherwise(0))
it = it.withColumn('low_price', F.when((F.col('price_kg') < 0.5 * F.col('bm_kg'))
                                       & (F.col('price_kg') >= 0.01 * F.col('bm_kg')) & low_per_unit_too, 1).otherwise(0))
gap_per_kg = F.col('bm_kg') * F.col('net_weight') - F.col('customs_value')
gap_per_unit = F.when((units > 0) & F.col('bm_unit').isNotNull(), F.col('bm_unit') * units - F.col('customs_value'))
it = it.withColumn('shortfall', F.least(gap_per_kg, gap_per_unit))
it = it.withColumn('price_deviation', F.abs(F.log(F.col('price_kg') / F.col('bm_kg'))))
it = it.cache()

# step 5: per taxpayer
counted = F.when((F.col('low_price') == 1) & (F.col('shortfall') > 0), F.col('shortfall')).otherwise(0)
shortfall = it.groupBy('taxpayer_tin').agg(
    F.count('*').alias('priced_items_24m_count'),
    (F.sum(counted) / F.sum('customs_value')).alias('peer_price_shortfall_per_value_24m_rate'))
shortfall.orderBy(F.desc('peer_price_shortfall_per_value_24m_rate')).show(5)
""")

# ------------------------------------------------------------------------------------------- Track B
md('7. Track B', r"""
## 7. Track B features (behaviour)

No input that records what customs did (no top-ups, no lanes). Three come from Track A: amended (6.3), shortfall
(6.8), station (6.7).
""")

py('7.1 unpaid_tax_per_decl_24m_rate', r"""
# tax due and NOT_PAID / declarations
unpaid = F.when((F.col('pay_status') == 'NOT_PAID') & (F.col('final_tax') > 0), 1.0).otherwise(0.0)
unpaid_rate = hist.groupBy('taxpayer_tin').agg(F.avg(unpaid).alias('unpaid_tax_per_decl_24m_rate'))
unpaid_rate.show(5)
""")

py('7.2 pref_claimed_per_item_24m_rate', r"""
# items claiming preferential treatment / items
claims = F.when(F.col('preferential_treatment_flag') == 'Y', 1.0).otherwise(0.0)
preference_rate = hist_items.groupBy('taxpayer_tin').agg(F.avg(claims).alias('pref_claimed_per_item_24m_rate'))
preference_rate.show(5)
""")

py('7.3 price features', r"""
# from the item table of 6.8
price_features = it.groupBy('taxpayer_tin').agg(
    F.avg('implausible').alias('price_keying_error_per_item_24m_rate'),          # under 1% of the benchmark
    F.avg('low_price').alias('price_under_half_peer_per_item_24m_rate'),            # under half the benchmark
    F.expr('percentile_approx(CASE WHEN implausible = 0 THEN price_deviation END, 0.5)').alias('median_price_dev_from_peer_24m_log'),
    F.avg('on_origin_bench').alias('priced_on_coo_peer_per_item_24m_rate'))
price_features.show(5)
""")

py('7.4 own_price_drop_per_recent_value_6m_rate', r"""
# for each HS code: the taxpayer's own price in the last 6 months against the 18 months before
six_months_back = F.add_months(snap_date, -6)
late = F.col('adate') > six_months_back
early = F.col('adate') <= six_months_back
own = priced.withColumn('early_kg', F.when(early, F.col('price_kg')))
own = own.withColumn('late_kg', F.when(late, F.col('price_kg')))
own = own.withColumn('early_u', F.when(early, F.col('price_unit')))
own = own.withColumn('late_u', F.when(late, F.col('price_unit')))
own = own.groupBy('taxpayer_tin', 'hsc_cd').agg(
    F.expr('percentile_approx(early_kg, 0.5)').alias('early_kg'),
    F.expr('percentile_approx(late_kg, 0.5)').alias('late_kg'),
    F.expr('percentile_approx(early_u, 0.5)').alias('early_u'),
    F.expr('percentile_approx(late_u, 0.5)').alias('late_u'),
    F.sum(F.when(late, F.col('customs_value')).otherwise(0)).alias('late_value'),
    F.sum(early.cast('int')).alias('n_early'),
    F.sum(late.cast('int')).alias('n_late'))
own = own.filter((F.col('n_early') >= 2) & (F.col('n_late') >= 1) & (F.col('early_kg') > 0))

dropped = (F.col('late_kg') < 0.7 * F.col('early_kg')) & (
    F.col('early_u').isNull() | F.col('late_u').isNull() | (F.col('late_u') < 0.7 * F.col('early_u')))
own_drop = own.groupBy('taxpayer_tin').agg(
    F.count('*').alias('hs_codes_compared_count'),
    (F.sum(F.when(dropped, F.col('late_value')).otherwise(0)) / F.sum('late_value')).alias('own_price_drop_per_recent_value_6m_rate'))
own_drop.show(5)
""")

py('7.5 duty features', r"""
# median duty rate per HS code with no exemption (APC 000), 5 or more importers
taxed = hist_items.filter((F.col('customs_value') > 0) & (F.col('tax_assessed') >= 0))
taxed = taxed.withColumn('rate', F.col('tax_assessed') / F.col('customs_value'))
duty_bench = taxed.filter(F.col('cpc_cd') == '000').groupBy('hsc_cd').agg(
    F.expr('percentile_approx(rate, 0.5)').alias('med_rate'),
    F.countDistinct('taxpayer_tin').alias('importers'))
duty_bench = duty_bench.filter(F.col('importers') >= 5).drop('importers')
taxed = taxed.join(duty_bench, 'hsc_cd', 'left')

compared = (F.col('cpc_cd') == '000') & (F.col('med_rate') > 0)
value_compared = F.sum(F.when(compared, F.col('customs_value')).otherwise(0))
low_rate_value = F.sum(F.when(compared & (F.col('rate') < 0.5 * F.col('med_rate')), F.col('customs_value')).otherwise(0))
missing_tax = F.greatest(F.col('med_rate') * F.col('customs_value') - F.col('tax_assessed'), F.lit(0))
duty = taxed.groupBy('taxpayer_tin').agg(
    (low_rate_value / value_compared).alias('duty_under_half_peer_per_value_24m_rate'),
    (F.sum(F.when(compared, missing_tax).otherwise(0)) / value_compared).alias('duty_gap_vs_peer_per_value_24m_rate'))
duty.show(5)
""")

py('7.6 APC features', r"""
WATCHLIST = __WATCHLIST__
valued = hist_items.filter(F.col('customs_value') > 0)
exempt_value = F.sum(F.when(F.col('cpc_cd') != '000', F.col('customs_value')).otherwise(0))
watchlist_value = F.sum(F.when(F.col('cpc_cd').isin(WATCHLIST), F.col('customs_value')).otherwise(0))
apc = valued.groupBy('taxpayer_tin').agg(
    (exempt_value / F.sum('customs_value')).alias('exempt_apc_per_value_24m_rate'),
    (watchlist_value / F.sum('customs_value')).alias('watchlist_apc_per_value_24m_rate'))
apc.show(5)
""")

py('7.7 same_day_split_per_decl_vs_norm_24m_diff', r"""
# leave out cement and salt (25), fuel (27) and fuel transit (EPC 4080, 7180)
splittable = hist_items.filter(~F.substring('hsc_cd', 1, 2).isin('25', '27'))
splittable = splittable.filter(~F.coalesce(F.col('extended_proc_cd'), F.lit('')).isin('4080', '7180'))

# declarations per taxpayer, per day, per HS code
per_day = splittable.groupBy('taxpayer_tin', 'assessment_dt_wid', 'hsc_cd').agg(
    F.countDistinct('instance_id').alias('n'))
per_day = per_day.withColumn('n_repeat', F.when(F.col('n') >= 2, F.col('n')).otherwise(0))

# the norm for each HS code across all importers
norm = per_day.groupBy('hsc_cd').agg((F.sum('n_repeat') / F.sum('n')).alias('norm_share'))

split = per_day.join(norm, 'hsc_cd').groupBy('taxpayer_tin').agg(
    (F.sum('n_repeat') / F.sum('n')).alias('same_day_split_per_decl_24m_rate'),
    (F.sum(F.col('n') * F.col('norm_share')) / F.sum('n')).alias('same_day_norm_per_decl_24m_rate'))
split = split.withColumn('same_day_split_per_decl_vs_norm_24m_diff', F.col('same_day_split_per_decl_24m_rate') - F.col('same_day_norm_per_decl_24m_rate'))
split.orderBy(F.desc('same_day_split_per_decl_vs_norm_24m_diff')).show(5)
""")

py('7.8 decl_90d_per_avg_qtr_24m_log', r"""
# declarations in the last 90 days against an average quarter (24 months / 8), log scale
in_last_90_days = F.when(F.col('adate') > F.date_sub(snap_date, 90), 1).otherwise(0)
surge = hist.groupBy('taxpayer_tin').agg(F.count('*').alias('n'), F.sum(in_last_90_days).alias('decl_90d_count'))
surge = surge.withColumn('decl_90d_per_avg_qtr_24m_log', F.log((F.col('decl_90d_count') + 1) / (F.col('n') / 8.0 + 1))).drop('n')
surge.orderBy(F.desc('decl_90d_per_avg_qtr_24m_log')).show(5)
""")

py('7.9 hs4_per_decl_24m_ratio', r"""
headings = hist_items.groupBy('taxpayer_tin').agg(F.countDistinct(F.substring('hsc_cd', 1, 4)).alias('hs4_24m_count'))
goods = base.select('taxpayer_tin', 'decl_24m_count').join(headings, 'taxpayer_tin', 'left')
goods = goods.withColumn('hs4_per_decl_24m_ratio', F.col('hs4_24m_count') / F.greatest('decl_24m_count', F.lit(1)))
goods = goods.drop('decl_24m_count')
goods.show(5)
""")

py('7.10 new_importer_24m_score', r"""
# who imported in the 3 years before the 24 months?
day = F.col('assessment_dt_wid').cast('string')
earlier = spark.table(VIEW).filter((day > PRIOR_START) & (day <= HIST_START))
earlier = earlier.filter(F.col('regime_cd').isin('IM4', 'IM7') & (F.col('decl_status') != 'Cancelled'))
earlier = earlier.filter(F.col('taxpayer_tin').cast('string').rlike('^[0-9]{10}$'))
earlier = earlier.select(F.col('taxpayer_tin').cast('string').alias('taxpayer_tin')).distinct()
earlier = earlier.withColumn('imported_before', F.lit(1))

newness = hist.groupBy('taxpayer_tin').agg(F.datediff(snap_date, F.min('adate')).alias('days_since_first_decl_24m'))
newness = newness.join(earlier, 'taxpayer_tin', 'left')
newness = newness.withColumn('new_trader', F.when(F.col('imported_before').isNull(), 'Y').otherwise('N'))
newness = newness.withColumn('new_importer_24m_score', -F.log1p(F.greatest('days_since_first_decl_24m', F.lit(0)))
                             + F.when(F.col('new_trader') == 'Y', 1.0).otherwise(0.0))
newness = newness.drop('imported_before')
newness.show(5)
""")

# ------------------------------------------------------------------------------------------- after
md('8. After the features', r"""
## 8. Recency, small numbers, peer groups

1. **Recency (Track A):** over 3 years, a declaration counts 1 in the latest year, 0.5 the year before, 0.25 the year
   before that.
2. **Small numbers (both tracks):** rate pulled towards everyone's average by weight n / (n + 10), only ever down.
3. **Peer groups (Track B):** each feature becomes a percentile among importers with the same main goods and size.
""")

py('8.1 Recency', r"""
year_weight = F.when(F.col('adate') > F.add_months(snap_date, -12), 1.0)
year_weight = year_weight.when(F.col('adate') > F.add_months(snap_date, -24), 0.5).otherwise(0.25)
d3 = decl.filter(F.col('dt') <= SNAP).withColumn('w', year_weight)
w = F.col('w')
recency = d3.groupBy('taxpayer_tin').agg(
    (F.sum(w * F.col('topped_up')) / F.sum(w)).alias('topped_up_per_decl_3y_rate'),
    (F.sum(w * F.col('severe')) / F.sum(w)).alias('severe_top_up_per_decl_3y_rate'),
    (F.sum(w * F.when(F.col('amended') == 'Y', 1).otherwise(0)) / F.sum(w)).alias('amended_per_decl_3y_rate'),
    (F.sum(w * F.col('negative_top_up')) / F.sum(w)).alias('tax_reduced_per_decl_3y_rate'),
    F.sum(w * F.col('top_up')).alias('w_top_up'),
    F.sum(w * F.col('orig_tax')).alias('w_orig_tax'))
w_final_tax = F.col('w_orig_tax') + F.col('w_top_up')
recency = recency.withColumn('top_up_per_final_tax_3y_rate', F.when(w_final_tax > 0, F.col('w_top_up') / w_final_tax))
recency = recency.drop('w_top_up', 'w_orig_tax')
recency.show(5)
""")

py('8.2 Put the features together', r"""
features = base
features = features.join(top_up_rate, 'taxpayer_tin', 'left')
features = features.join(severe_rate, 'taxpayer_tin', 'left')
features = features.join(amended_rate, 'taxpayer_tin', 'left')
features = features.join(top_up_share, 'taxpayer_tin', 'left')
features = features.join(reduced_rate, 'taxpayer_tin', 'left')
features = features.join(recent_top_up, 'taxpayer_tin', 'left')
features = features.join(stations, 'taxpayer_tin', 'left')
features = features.join(shortfall, 'taxpayer_tin', 'left')
features = features.join(unpaid_rate, 'taxpayer_tin', 'left')
features = features.join(preference_rate, 'taxpayer_tin', 'left')
features = features.join(price_features, 'taxpayer_tin', 'left')
features = features.join(own_drop, 'taxpayer_tin', 'left')
features = features.join(duty, 'taxpayer_tin', 'left')
features = features.join(apc, 'taxpayer_tin', 'left')
features = features.join(split, 'taxpayer_tin', 'left')
features = features.join(surge, 'taxpayer_tin', 'left')
features = features.join(goods, 'taxpayer_tin', 'left')
features = features.join(newness, 'taxpayer_tin', 'left')
features = features.join(recency, 'taxpayer_tin', 'left')
save_table(features, 'ctrp_feature_inputs')

# one row per taxpayer is small enough for pandas
tp = features.orderBy('taxpayer_tin').toPandas()
print(tp.shape)
print(tp.head().to_string())
""")

py('8.3 Small numbers', r"""
def credibility(rate, n, k=10):
    # pull a rate towards everyone's average by weight n / (n + k), only ever down
    rate = rate.astype(float)
    n = n.fillna(0).astype(float)
    has_value = rate.notna() & (n > 0)
    average = (rate[has_value] * n[has_value]).sum() / n[has_value].sum()
    weight = n / (n + k)
    return np.minimum(rate, weight * rate + (1 - weight) * average)


final = tp[['taxpayer_tin', 'taxpayer_nm', 'decl_24m_count', 'customs_value_24m_ugx', 'top_up_24m_ugx']].copy()
final.insert(1, 'snapshot_date', SNAPSHOT)

# Track A: five use the 3-year (recency) version, three stay at 24 months
TRACK_A = ['topped_up_per_decl_3y_rate', 'severe_top_up_per_decl_3y_rate', 'amended_per_decl_3y_rate',
           'top_up_per_final_tax_3y_rate', 'peer_price_shortfall_per_value_24m_rate', 'tax_reduced_per_decl_3y_rate',
           'top_up_last_180d_flag', 'away_from_main_station_per_decl_24m_rate']
for col in TRACK_A:
    final['raw_' + col] = tp[col]                      # before the small-numbers step
    if col == 'peer_price_shortfall_per_value_24m_rate':
        n = tp['priced_items_24m_count']
    else:
        n = tp['decl_24m_count']
    final[col] = credibility(tp[col], n)

# Track B: 17 features, all over 24 months. The 5 rates that rest on a count get the small-numbers step too
TRACK_B = ['amended_per_decl_24m_rate', 'unpaid_tax_per_decl_24m_rate', 'price_keying_error_per_item_24m_rate',
           'peer_price_shortfall_per_value_24m_rate', 'price_under_half_peer_per_item_24m_rate',
           'median_price_dev_from_peer_24m_log', 'own_price_drop_per_recent_value_6m_rate',
           'duty_under_half_peer_per_value_24m_rate', 'duty_gap_vs_peer_per_value_24m_rate',
           'exempt_apc_per_value_24m_rate', 'watchlist_apc_per_value_24m_rate', 'pref_claimed_per_item_24m_rate',
           'decl_90d_per_avg_qtr_24m_log', 'away_from_main_station_per_decl_24m_rate', 'hs4_per_decl_24m_ratio',
           'same_day_split_per_decl_vs_norm_24m_diff', 'new_importer_24m_score']
for col in TRACK_B:
    if col in ['amended_per_decl_24m_rate', 'unpaid_tax_per_decl_24m_rate']:
        final['b_' + col] = credibility(tp[col], tp['decl_24m_count'])
    elif col in ['price_keying_error_per_item_24m_rate', 'peer_price_shortfall_per_value_24m_rate',
                 'price_under_half_peer_per_item_24m_rate']:
        final['b_' + col] = credibility(tp[col], tp['priced_items_24m_count'])
    else:
        final['b_' + col] = tp[col].astype(float)

print(final[['taxpayer_tin', 'decl_24m_count', 'raw_amended_per_decl_3y_rate', 'amended_per_decl_3y_rate']].head(10).to_string())
""")

py('8.4 Peer groups', r"""
SECTIONS = __SECTIONS__


def hs_section(chapter):
    try:
        c = int(float(chapter))
    except (TypeError, ValueError):
        return 'Unknown'
    for low, high, name in SECTIONS:
        if low <= c <= high:
            return name
    return 'Unknown'


def size_tier(log_value):
    # small, medium, large = thirds by customs value inside the section
    if len(log_value) < 3:
        return pd.Series('small', index=log_value.index)
    return pd.qcut(log_value.rank(method='first'), 3, labels=['small', 'medium', 'large']).astype(str)


# main goods = the HS chapter with most of the taxpayer's value
by_chapter = hist_items.groupBy('taxpayer_tin', F.substring('hsc_cd', 1, 2).alias('chapter')).agg(
    F.sum('customs_value').alias('v'))
by_chapter = by_chapter.withColumn('rank', F.row_number().over(Window.partitionBy('taxpayer_tin').orderBy(F.desc('v'))))
main_chapter = by_chapter.filter(F.col('rank') == 1).select('taxpayer_tin', F.col('chapter').alias('dominant_hs_chapter'))
final = final.merge(main_chapter.toPandas(), on='taxpayer_tin', how='left')

section = final['dominant_hs_chapter'].map(hs_section).fillna('Unknown')
log_value = np.log1p(final['customs_value_24m_ugx'].clip(lower=0))
final['peer_group'] = section + ', ' + log_value.groupby(section).transform(size_tier)

def percentile_name(col):
    # swap the unit at the end for pct, for example b_amended_per_decl_24m_pct
    return 'b_' + col.rsplit('_', 1)[0] + '_pct'


for col in TRACK_B:
    final[percentile_name(col)] = final['b_' + col].groupby(final['peer_group']).rank(pct=True).fillna(0.5)

print(final['peer_group'].value_counts().head(20))
""")

py('9. Final dataset', r"""
final['limited_history'] = np.where(final['decl_24m_count'] < 10, 'Y', 'N')
final['no_top_up_history'] = np.where(final['top_up_24m_ugx'].fillna(0) <= 0, 'Y', 'N')

if WITH_OUTCOMES:
    after = decl.filter(F.col('dt') > SNAP)
    checked = (F.col('red') == 1) | (F.col('yellow') == 1)
    outcomes = after.groupBy('taxpayer_tin').agg(
        F.count('*').alias('out_entries'),
        F.sum(F.when(checked, 1).otherwise(0)).alias('out_checked'),
        F.sum(F.when(checked & (F.col('topped_up') == 1), 1).otherwise(0)).alias('out_checked_hits'),
        F.sum('topped_up').alias('out_topped_up_entries'),
        F.sum('top_up').alias('out_top_up'),
        F.sum('orig_tax').alias('out_original_tax')).toPandas()
    final = final.merge(outcomes, on='taxpayer_tin', how='left')
    for c in ['out_entries', 'out_checked', 'out_checked_hits', 'out_topped_up_entries', 'out_top_up', 'out_original_tax']:
        final[c] = final[c].fillna(0)

columns = ['taxpayer_tin', 'taxpayer_nm', 'snapshot_date', 'decl_24m_count', 'customs_value_24m_ugx', 'limited_history',
           'no_top_up_history', 'peer_group']
columns = columns + TRACK_A + ['raw_' + c for c in TRACK_A]
columns = columns + ['b_' + c for c in TRACK_B] + [percentile_name(c) for c in TRACK_B]
columns = columns + [c for c in final.columns if c.startswith('out_')]
final_dataset = final[columns]
save_table(final_dataset, 'ctrp_final_dataset')
print(final_dataset.shape)
print(final_dataset.head(10).to_string())
""")


def paragraphs():
    """[(title, text)] with the project settings filled in (same filler as the review note)."""
    return [(title, N._fill(text)) for title, text in PARAGRAPHS]


def script():
    return '\n\n'.join(x.split('\n', 1)[1] for _, x in paragraphs() if x.startswith('%pyspark'))


def write_note(path=OUT_NOTE):
    paras = [N._paragraph(t, x, i) for i, (t, x) in enumerate(paragraphs())]
    for p in paras:
        p['id'] = p['jobName'] = p['id'].replace('ctrp_eda', 'ctrp_mine')
    note = {'paragraphs': paras, 'name': 'CTRP EDA and features (mine)', 'id': 'CTRPEDAMINE01',
            'defaultInterpreterGroup': 'spark', 'version': '0.10.1', 'noteParams': {}, 'noteForms': {},
            'angularObjects': {}, 'config': {'isZeppelinNotebookCronEnable': False}, 'info': {}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(note, indent=2))
    print(f'written {path.relative_to(PROJECT_ROOT)} ({len(paras)} paragraphs)')
    return path
