"""
The Zeppelin note for review and sign-off: data exploration (EDA) and the 22 features, in PySpark.

What: writes notebooks/zeppelin/CTRP_EDA_and_features.zpln (import it in Zeppelin) and the same
      paragraphs as text files (notebooks/zeppelin/eda_paragraphs/) for copying one at a time. The note
        1. loads the rows of the view,
        2. explores them (missing data, duplicates) and lists the data problems found, with the rows behind each,
        3. cleans them (R1 to R15) and logs what each rule removed,
        4. builds declarations, then every Track A and Track B feature, one paragraph each,
        5. applies recency, credibility weighting and peer percentiles,
        6. saves the final dataset and checks it against the production extract.
      Then build_excel() turns the downloaded results into Excel workbooks in results/.
Why:  the production extract is one long Hue query, which is hard to review. This note does the same
      steps in plain PySpark on the full view, with the reason for each step written beside it.
      It uses the same rules, windows and settings as the production query (checked in
      tests/test_eda_note.py: same numbers on the same data).

    python main.py eda-note                      -> the .zpln note and the paste files
    python main.py eda-excel data/zeppelin_eda   -> results/eda_issues/*.xlsx and the final dataset workbook
"""
import json
import re
import shutil
from pathlib import Path

import pandas as pd

from ctrp import core as M
from ctrp import extract as E
from ctrp import issues as I
from ctrp.utils import DATA_DIR, PROJECT_ROOT, RESULTS_DIR

OUT_NOTE = PROJECT_ROOT / 'notebooks' / 'zeppelin' / 'CTRP_EDA_and_features.zpln'
PASTE_DIR = PROJECT_ROOT / 'notebooks' / 'zeppelin' / 'eda_paragraphs'

# The data problems shown in the review note (Ethan, 20 Oct 2026: the ones relevant to Stella). The officer
# workbooks keep the same codes, so E10 is skipped here on purpose.
REVIEW_ISSUES = ['E01', 'E02', 'E03', 'E04', 'E05', 'E06', 'E07', 'E08', 'E09', 'E11']

# The feature names used in the notes and the final dataset (Ethan, 20 Oct 2026). Each name says what is
# measured, per what, over which window, and the unit last. The production query keeps its own column names;
# this is the one mapping between the two: production column -> name in the notes.
FEATURE_NAMES = {
    'entries_24m': 'decl_24m_count',
    'total_customs_value': 'customs_value_24m_ugx',
    'total_original_tax': 'original_tax_24m_ugx',
    'total_top_up': 'top_up_24m_ugx',
    'top_up_entry_rate': 'topped_up_per_decl_24m_rate',
    'par077_severe_top_up_rate': 'severe_top_up_per_decl_24m_rate',
    'par045_amended_entry_rate': 'amended_per_decl_24m_rate',
    'par048_top_up_share_final': 'top_up_per_final_tax_24m_rate',
    'par066_negative_top_up_rate': 'tax_reduced_per_decl_24m_rate',
    'par105_days_since_last_top_up': 'days_since_last_top_up',
    'par105_top_up_180d': 'top_up_last_180d_flag',
    'main_station_share': 'main_station_per_decl_24m_rate',
    'par023_station_spread': 'away_from_main_station_per_decl_24m_rate',
    'station_spread': 'away_from_main_station_per_decl_24m_rate',
    'items_benchmarked': 'priced_items_24m_count',
    'par076_shortfall_share': 'peer_price_shortfall_per_value_24m_rate',
    'top_up_entry_rate_3y': 'topped_up_per_decl_3y_rate',
    'par077_severe_top_up_rate_3y': 'severe_top_up_per_decl_3y_rate',
    'par045_amended_entry_rate_3y': 'amended_per_decl_3y_rate',
    'par066_negative_top_up_rate_3y': 'tax_reduced_per_decl_3y_rate',
    'par048_top_up_share_final_3y': 'top_up_per_final_tax_3y_rate',
    'ctx_unpaid_rate': 'unpaid_tax_per_decl_24m_rate',
    'ctx_preferential_use_rate': 'pref_claimed_per_item_24m_rate',
    'ctx_implausible_price_rate': 'price_keying_error_per_item_24m_rate',
    'par076_low_price_item_rate': 'price_under_half_peer_per_item_24m_rate',
    'price_deviation_median': 'median_price_dev_from_peer_24m_log',
    'origin_benchmark_share': 'priced_on_coo_peer_per_item_24m_rate',
    'own_price_drop_share': 'own_price_drop_per_recent_value_6m_rate',
    'hs_codes_compared': 'hs_codes_compared_count',
    'low_duty_value_share': 'duty_under_half_peer_per_value_24m_rate',
    'duty_gap_share': 'duty_gap_vs_peer_per_value_24m_rate',
    'exemption_apc_value_share': 'exempt_apc_per_value_24m_rate',
    'watchlist_apc_value_share': 'watchlist_apc_per_value_24m_rate',
    'same_day_split_share': 'same_day_split_per_decl_24m_rate',
    'same_day_split_expected': 'same_day_norm_per_decl_24m_rate',
    'same_day_split_excess': 'same_day_split_per_decl_vs_norm_24m_diff',
    'entries_last_90d': 'decl_90d_count',
    'surge': 'decl_90d_per_avg_qtr_24m_log',
    'hs_headings_used': 'hs4_24m_count',
    'goods_spread': 'hs4_per_decl_24m_ratio',
    'days_since_first_in_window': 'days_since_first_decl_24m',
    'newness': 'new_importer_24m_score',
}

# The 8 scored Track A features: production column -> the name of the value the scorecard reads
# (five use the 3-year recency version, three stay at 24 months)
TRACK_A_NAMES = {
    'top_up_entry_rate': 'topped_up_per_decl_3y_rate',
    'par077_severe_top_up_rate': 'severe_top_up_per_decl_3y_rate',
    'par045_amended_entry_rate': 'amended_per_decl_3y_rate',
    'par048_top_up_share_final': 'top_up_per_final_tax_3y_rate',
    'par076_shortfall_share': 'peer_price_shortfall_per_value_24m_rate',
    'par066_negative_top_up_rate': 'tax_reduced_per_decl_3y_rate',
    'par105_top_up_180d': 'top_up_last_180d_flag',
    'par023_station_spread': 'away_from_main_station_per_decl_24m_rate',
}
# The 17 Track B features: production column -> name (all over 24 months; columns start with b_ in the dataset)
TRACK_B_NAMES = {col: FEATURE_NAMES[col] for col in [
    'par045_amended_entry_rate', 'ctx_unpaid_rate', 'ctx_implausible_price_rate', 'par076_shortfall_share',
    'par076_low_price_item_rate', 'price_deviation_median', 'own_price_drop_share', 'low_duty_value_share',
    'duty_gap_share', 'exemption_apc_value_share', 'watchlist_apc_value_share', 'ctx_preferential_use_rate',
    'surge', 'station_spread', 'goods_spread', 'same_day_split_excess', 'newness']}
# Short forms and units used in the names (the "Names" sheet of the final dataset workbook)
ABBREVIATIONS = [
    ('decl', 'declaration'),
    ('item', 'one item (line) on a declaration'),
    ('peer', 'the middle price or duty rate of other importers of the same goods'),
    ('coo', 'country of origin'),
    ('hs4', 'HS heading (first 4 digits of the tariff code)'),
    ('apc', 'additional procedure code'),
    ('exempt', 'exemption'),
    ('pref', 'preferential treatment'),
    ('dev', 'deviation (distance)'),
    ('avg', 'average'),
    ('qtr', 'quarter (3 months)'),
    ('original_tax', 'the tax first assessed'),
    ('ugx', 'Uganda shillings'),
    ('3y', 'the 3 years before the snapshot, recent years counting more (1, 0.5, 0.25)'),
    ('24m', 'the 24 months before the snapshot'),
    ('6m', 'the 6 months before the snapshot'),
    ('90d, 180d', 'the 90 or 180 days before the snapshot'),
    ('rate', 'unit: cases divided by the base named after "per" (0 to 1; the shortfall can go above 1)'),
    ('flag', 'unit: 1 = yes, 0 = no'),
    ('log', 'unit: a log ratio (0 = the same, above 0 = higher)'),
    ('ratio', 'unit: one count divided by another'),
    ('diff', 'unit: a rate minus the norm for the same goods'),
    ('score', 'unit: a made-up score; only its order matters'),
    ('count', 'unit: a number of things'),
    ('pct', 'percentile within the peer group (0 to 1): what the Track B model reads'),
    ('b_', 'start of every Track B column'),
    ('raw_', 'a Track A value before the small-numbers step'),
]

# What a blank means in each column, and what the model does with it (shown in Part 2.2 of the note)
BLANK_MEANS = {
    'taxpayer_tin': 'No taxpayer: the row is dropped (R1, E03)',
    'entry_num': 'No entry number: the declaration ID is used as the entry key',
    'clearance_station_cd': 'No station: counted as a station of its own in the station measures',
    'dec_ref_yer': 'No year: the declaration ID is used as the entry key',
    'decl_status': 'No status: the row is dropped with the cancelled ones (R3)',
    'regime_cd': 'No regime: the row is dropped (R4)',
    'hsc_cd': 'No tariff code: no price or duty benchmark for the item; it still counts in its declaration',
    'gds_org_cty': 'No origin: the item is compared with the benchmark for its HS code across all origins',
    'cpc_cd': 'No APC: not counted as exempt, and left out of the duty comparison (that uses APC 000 only)',
    'customs_value': 'No value: left out of the price, duty and APC features (E11)',
    'net_weight': 'No weight: left out of the price features (E11)',
    'supplementary_qnty': 'No units: the price is compared per kg only',
    'tax_assessed': 'No item tax: left out of the duty features',
    'original_tax_amt': 'Read as unchanged: the final tax is used (E08)',
    'final_amt': 'No final tax: no top-up or tax reduction can be counted',
    'top_up_amt': 'Not used by the model (E09)',
    'top_up_flg': 'Read as no top-up',
    'amendment_flg': 'Read as not amended',
    'pay_status': 'Read as not unpaid',
    'preferential_treatment_flag': 'Read as no preference claimed',
    'is_red_flg': 'Read as not red (used only for outcomes)',
    'is_yellow_flg': 'Read as not yellow (used only for outcomes)',
    'assessment_dt_wid': 'No date: outside every window, so not used',
}

# APCs the AC-Trade memo marks "look out for possible abuse" (the same list as the production query)
WATCHLIST_APCS = ['404', '409', '417', '451', '455', '457', '476', '479', '481', '482', '484']

PARAGRAPHS = []      # (title, text) in the order they appear in the note


def md(title, text):
    PARAGRAPHS.append((title, '%md\n' + text.strip()))


def py(title, text):
    PARAGRAPHS.append((title, '%pyspark\n' + text.strip()))


# =========================================================================================
# 0. Title and settings
# =========================================================================================
md('Title', r"""
# CTRP: data exploration (EDA) and features

**Customs Taxpayer Risk Profiling Model.** Data Science Section, ITID. For review and sign-off.

This note starts from the raw rows of the customs view and shows, step by step, what we found in the data,
how we cleaned it, and how each feature is built and why. Everything runs here, on the full view.

| Part | What happens | What it gives |
|---|---|---|
| 1 | Load the rows of the view | |
| 2 | Explore them: missing data, duplicates, and the data problems found | one table per problem for the Risk Officers |
| 3 | Clean them with the agreed rules (R1 to R15) | the cleaning log |
| 4 | From item rows to declarations | |
| 5 | Track A: the 8 compliance history features (the scorecard) | |
| 6 | Track B: the 17 behaviour features (the Risky Behaviour Flag) | |
| 7 | Steps after the features: recency, small numbers, peer groups | |
| 8 | The final dataset, and a check against production | the final dataset |

**22 features.** Track A has 8 and Track B has 17. Three are used by both (declarations amended, value below
other importers, clearing away from the main station), so there are 22 different features.

**How the features are named.** Each name says what is measured, per what, over which window, and ends with the
unit. Example: `topped_up_per_decl_3y_rate` = declarations topped up, per declaration, over 3 years, as a rate.
Short forms: `decl` declaration, `peer` the middle price of other importers, `hs4` HS heading, `coo` country of
origin, `exempt` exemption, `pref` preferential, `dev` deviation, `avg` average, `qtr` quarter. Windows: `3y`
(3 years, recent years count more), `24m`, `6m`, `90d`, `180d`. Units: `rate`, `flag` (1 or 0), `log`, `ratio`,
`diff`, `score`, `count`, `ugx`. Track B columns start with `b_`; a percentile ends with `pct`.

**How to run.** Run the paragraphs from top to bottom (or "Run all"). Only the **Settings** paragraph is meant
to be edited. Each result is kept as a table in this Spark session (names start with `ctrp_`), so it can be
looked at with `%sql` in a new paragraph. Contains TINs: internal use only.
""")

py('Settings', r"""
# ===================== Settings: the only paragraph to edit =====================
SNAPSHOT = '__LIVE__'          # the day the risk profile is made (the last day of a month)
WITH_OUTCOMES = False              # True for a past snapshot: adds what happened in the 6 months after it
SAMPLE_1_IN = None                 # e.g. 20 = a quick trial on 1 in 20 taxpayers. None = every taxpayer

# The agreed cleaning rules that can be switched (all on)
EXCLUDE_APC_483 = __APC483__              # R13 APC 483: destroyed or abandoned goods, dummy entries
LATEST_DECLARATION_PER_ENTRY = __R14__    # R14 one declaration per entry (entry number + station + year)
EXCLUDE_MOTOR_VEHICLES = __R15__          # R15 motor vehicles have their own model
MOTOR_VEHICLE_HEADINGS = __MV__

# Where results go. Every result is always kept as a table in this session.
SAVE_TO_FOLDER = False             # True: also write CSV files under OUT_DIR (needs a folder you can write to)
OUT_DIR = '/user/CHANGE_ME/ctrp_eda'
SAVE_TO_SCHEMA = None              # e.g. 'my_sandbox': also save as Hive tables (download from Hue as Excel)
PRODUCTION_TABLE = None            # optional, for Part 8.2: a table holding the production extract for SNAPSHOT

VIEW = 'dm_modeled_ura_datascience.vw_cstm_AEO_model'
""")

py('Setup', r"""
# ===================== Setup: libraries, dates and small helpers (no need to edit) =====================
import calendar, datetime
from functools import reduce
from pyspark.sql import functions as F, Window
import numpy as np
import pandas as pd

def as_date(date_text):
    return datetime.datetime.strptime(date_text, '%Y-%m-%d').date()

def month_end(date_text, months):
    # The last day of the month `months` away from the date (negative = earlier)
    d = as_date(date_text)
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return datetime.date(y, m + 1, calendar.monthrange(y, m + 1)[1])

def ymd(d):
    return d.strftime('%Y%m%d')       # dates in the view are text like '20260930'

# The windows, all counted back from the snapshot
SNAP = ymd(as_date(SNAPSHOT))
HIST_START = ymd(month_end(SNAPSHOT, -24))     # features use the 24 months before the snapshot
HIST3_START = ymd(month_end(SNAPSHOT, -36))    # recency weighting uses 3 years
PRIOR_START = ymd(month_end(SNAPSHOT, -60))    # "new trader": nothing in the 3 years before the 24 months
OUT_END = ymd(month_end(SNAPSHOT, 6)) if WITH_OUTCOMES else SNAP
snap_date = F.to_date(F.lit(SNAPSHOT))

def median(column_sql):
    # The middle value, as the production query computes it (Spark's percentile_approx)
    return F.expr('percentile_approx(%s, 0.5)' % column_sql)

def peek(df, n=10):
    # Show the first rows of a result
    z.show(df.head(n) if isinstance(df, pd.DataFrame) else df.limit(n))

def save(df, name):
    # Keep a result as a table in this session, and as CSV files or a Hive table when switched on
    if isinstance(df, pd.DataFrame):
        df = spark.createDataFrame(df)
    df.createOrReplaceTempView(name)
    if SAVE_TO_FOLDER:
        df.coalesce(1).write.mode('overwrite').option('header', True).csv(OUT_DIR + '/' + name)
    if SAVE_TO_SCHEMA:
        df.write.mode('overwrite').saveAsTable(SAVE_TO_SCHEMA + '.' + name)

print('Snapshot:', SNAPSHOT)
print('Features use declarations after', HIST_START, 'up to', SNAP, '(24 months)')
print('Recency uses declarations after', HIST3_START, '(36 months)')
print('Outcomes:', ('after ' + SNAP + ' up to ' + OUT_END) if WITH_OUTCOMES else 'none (live snapshot)')
print('Results kept in this session' + (', written to ' + OUT_DIR if SAVE_TO_FOLDER else '')
      + (', saved in schema ' + SAVE_TO_SCHEMA if SAVE_TO_SCHEMA else ''))
""")

# =========================================================================================
# 1. Load
# =========================================================================================
md('1. Load', r"""
## 1. Load the rows of the view

Each row of the view is **one item on one declaration**: a declaration with 5 kinds of goods has 5 rows.
We take the columns below for the 3 years before the snapshot (all regimes, so the cleaning in Part 3 can
show what it removes), and give each column its type.

| Type | Columns |
|---|---|
| Text (codes and IDs) | `instance_id` (declaration ID), `entry_num`, `dec_ref_yer` (year), `clearance_station_cd`, `taxpayer_tin`, `taxpayer_nm`, `consignee_tin`, `consignee_nm`, `hsc_cd` (tariff code), `gds_org_cty` (origin), `cpc_cd` (APC), `extended_proc_cd` (EPC), `regime_cd`, `decl_status`, `pay_status`, `key_itm_nbr` (item number) |
| Yes or no (`Y` or `N`) | `top_up_flg`, `amendment_flg`, `preferential_treatment_flag` |
| Lane (1 = selected) | `is_red_flg`, `is_yellow_flg` |
| Numbers (UGX, kg, units) | `customs_value`, `net_weight`, `supplementary_qnty`, `tax_assessed`, `original_tax_amt`, `final_amt`, `top_up_amt` |
| Date | `assessment_dt_wid` (text `yyyymmdd`), turned into a real date `adate` |

Two columns are added: `adate` (the date) and `entry_key`, the entry number + station + year
(for example `C12345UGKLA2026`), which identifies an entry. Where any part is blank, the declaration ID is used.
""")

py('1.1 Load', r"""
TEXT = ['instance_id', 'entry_num', 'dec_ref_yer', 'clearance_station_cd', 'taxpayer_tin', 'taxpayer_nm',
        'consignee_tin', 'consignee_nm', 'hsc_cd', 'gds_org_cty', 'cpc_cd', 'extended_proc_cd', 'regime_cd',
        'decl_status', 'pay_status', 'key_itm_nbr', 'top_up_flg', 'amendment_flg', 'preferential_treatment_flag',
        'assessment_dt_wid']
NUMBERS = ['customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt', 'final_amt',
           'top_up_amt']
LANES = ['is_red_flg', 'is_yellow_flg']

v = spark.table(VIEW)
rows = (v.select([F.col(c).cast('string').alias(c) for c in TEXT]
                 + [F.col(c).cast('double').alias(c) for c in NUMBERS]
                 + [F.col(c).cast('int').alias(c) for c in LANES])
         .where((F.col('assessment_dt_wid') > HIST3_START) & (F.col('assessment_dt_wid') <= OUT_END))
         .withColumn('adate', F.to_date('assessment_dt_wid', 'yyyyMMdd'))
         .withColumn('entry_key', F.coalesce(F.concat('entry_num', 'clearance_station_cd', 'dec_ref_yer'),
                                             F.col('instance_id'))))
if SAMPLE_1_IN:
    rows = rows.where(F.pmod(F.hash('taxpayer_tin'), SAMPLE_1_IN) == 0)
rows = rows.cache()

n_loaded = rows.count()
print('Item rows loaded: {:,}'.format(n_loaded))
peek(rows)
""")

py('1.2 Columns', r"""
# Each column: its type, an example, and how often it is blank
blank = rows.select([F.avg(F.col(c).isNull().cast('double')).alias(c) for c in rows.columns]).first().asDict()
example = rows.limit(1000).toPandas()
overview = pd.DataFrame({
    'column': rows.columns,
    'type': [t for _, t in rows.dtypes],
    'example': [example[c].dropna().iloc[0] if example[c].notna().any() else None for c in rows.columns],
    'blank %': [round(100 * blank[c], 1) for c in rows.columns],
})
overview['example'] = overview['example'].astype(str)
z.show(overview)
""")

# =========================================================================================
# 2. EDA
# =========================================================================================
md('2. Explore', r"""
## 2. Explore the rows (EDA)

Before building anything we look at what the data holds: how much there is, what is **missing**, what is
**duplicated**, then values, goods, lanes and top-ups.
Then we list every **data problem** we found. Each problem leads to a cleaning rule in Part 3 or a choice in the
features. The Risk Officers are asked to confirm each one (Part 2.7 gives them the rows behind each problem).

The exploration uses the same window as the features: IM4 and IM7 declarations in the 24 months before the
snapshot.
""")

py('2.1 Size', r"""
eda = rows.where((F.col('assessment_dt_wid') > HIST_START) & (F.col('assessment_dt_wid') <= SNAP)
                 & F.col('regime_cd').isin('IM4', 'IM7'))

# How much data, per year (rows repeat items, so declarations and entries are counted as distinct IDs)
size = (eda.groupBy(F.substring('assessment_dt_wid', 1, 4).alias('year'))
           .agg(F.count('*').alias('item_rows'),
                F.countDistinct('instance_id').alias('declarations'),
                F.countDistinct('entry_key').alias('entries'),
                F.countDistinct('taxpayer_tin').alias('taxpayers'))
           .orderBy('year'))
z.show(size)
""")

md('2.2 Missing data', r"""
## 2.2 Missing data

A blank (null) cell can mean "not recorded", "not applicable" or "unchanged". For each column the table gives the
share of rows that are blank, and for numbers the share that are zero or less. The last column says what a blank
means for the model and what the model does with it. The next two tables check whether blanks are getting more or
less common over time, and test our reading of the most important blank, the original tax (E08).
""")

py('2.2 Missing data', r"""
BLANK_MEANS = __BLANK_MEANS__
columns = TEXT + NUMBERS + LANES
blank = eda.select([F.avg(F.col(c).isNull().cast('double')).alias(c) for c in columns]).first().asDict()
zero = eda.select([F.avg((F.col(c) <= 0).cast('double')).alias(c) for c in NUMBERS]).first().asDict()
missing = pd.DataFrame({
    'column': columns,
    'blank %': [round(100 * blank[c], 2) for c in columns],
    'zero or less, % of filled rows': [round(100 * zero[c], 2) if c in zero else None for c in columns],
    'what a blank means and what the model does': [BLANK_MEANS.get(c, '') for c in columns],
})
z.show(missing.sort_values('blank %', ascending=False))
""")

py('2.2 Missing data by year', r"""
# Is it getting better or worse? Blank % per year for the columns the model leans on
WATCH = ['original_tax_amt', 'hsc_cd', 'gds_org_cty', 'supplementary_qnty', 'net_weight', 'tax_assessed', 'cpc_cd',
         'entry_num', 'decl_status', 'clearance_station_cd']
blank_pct = [F.round(100 * F.avg(F.col(c).isNull().cast('double')), 2).alias(c) for c in WATCH]
z.show(eda.groupBy(F.substring('assessment_dt_wid', 1, 4).alias('year')).agg(*blank_pct).orderBy('year'))
""")

py('2.2 Original tax blank', r"""
# Test of "blank original tax means unchanged" (E08): if it is true, declarations WITH a top-up should almost
# never have a blank original tax, because a top-up changes the tax
per_declaration = eda.groupBy('instance_id').agg(F.max('top_up_flg').alias('flag'),
                                                 F.max('original_tax_amt').alias('original_tax'))
z.show(per_declaration
       .groupBy(F.coalesce(F.col('flag'), F.lit('blank')).alias('top-up flag'))
       .agg(F.count('*').alias('declarations'),
            F.round(100 * F.avg(F.col('original_tax').isNull().cast('double')), 1).alias('original tax blank %')))
""")

md('2.3 Duplicates', r"""
## 2.3 Duplicates

The same thing can appear more than once at four levels: the same row copied, the same item repeated, the same
entry under more than one declaration ID, and one declaration ID carrying more than one taxpayer or date. The
table counts each. If the copies of an item are all identical, keeping one copy loses nothing (rule R5).

**Where the repeated items come from.** The view joins three tables on the declaration ID only: the declaration
header, the items, and the inspection actions (`awunadm.insp_act_tab_t`). A declaration or item with more than one
row in any of them repeats in the view. The copies are identical in every column the model uses, so keeping one copy
of each item (R5) loses nothing. The last paragraph tests the inspection actions as the cause.
""")

py('2.3 Duplicates', r"""
n_rows = eda.count()
n_distinct_rows = eda.distinct().count()
n_items = eda.select('instance_id', 'key_itm_nbr').distinct().count()
item_versions = eda.distinct().groupBy('instance_id', 'key_itm_nbr').count()          # different versions of an item
copies = eda.groupBy('instance_id', 'key_itm_nbr').count()                             # copies of an item
ids_per_entry = eda.groupBy('entry_key').agg(F.countDistinct('instance_id').alias('ids'))
per_id = eda.groupBy('instance_id').agg(F.countDistinct('taxpayer_tin').alias('tins'),
                                        F.countDistinct('assessment_dt_wid').alias('dates'))
duplicates = pd.DataFrame([
    ('Item rows (24 months, IM4 and IM7)', n_rows, ''),
    ('Rows that are an exact copy of another row', n_rows - n_distinct_rows, 'R5 keeps one copy'),
    ('Rows that repeat an item (same declaration ID and item number)', n_rows - n_items, 'E02, R5'),
    ('Items whose copies are NOT all identical', item_versions.where('count > 1').count(),
     '0 means keeping one copy loses nothing'),
    ('Most copies of one item', copies.agg(F.max('count')).first()[0], ''),
    ('Entries under more than one declaration ID', ids_per_entry.where('ids > 1').count(), 'E01, R14'),
    ('Declaration IDs with more than one TIN', per_id.where('tins > 1').count(), 'expected 0'),
    ('Declaration IDs with more than one assessment date', per_id.where('dates > 1').count(), 'expected 0'),
], columns=['check', 'count', 'note'])
z.show(duplicates)
""")

py('2.3 Copies per item', r"""
# How many copies items have
copy_band = (F.when(F.col('count') == 1, '1 (no copy)').when(F.col('count') == 2, '2')
              .when(F.col('count') <= 10, '3 to 10').when(F.col('count') <= 100, '11 to 100').otherwise('over 100'))
z.show(copies.groupBy(copy_band.alias('copies of the item')).agg(F.count('*').alias('items')).orderBy('copies of the item'))
""")

py('2.3 Where the copies come from', r"""
# The view's definition joins each item to every inspection action recorded on its declaration
# (awunadm.insp_act_tab_t). If that is where the copies come from, an item has as many copies as its declaration
# has inspection actions (or 1 copy when there are none).
day = F.col('assessment_dt_wid').cast('string')
view_rows = (spark.table(VIEW)
             .where((day > HIST_START) & (day <= SNAP) & F.col('regime_cd').isin('IM4', 'IM7'))
             .select(F.col('instance_id').cast('string').alias('instance_id'),
                     F.col('key_itm_nbr').cast('string').alias('key_itm_nbr'),
                     F.col('taxpayer_tin').cast('string').alias('taxpayer_tin'),
                     'sad_sid', 'op_date_time', 'inf'))
if SAMPLE_1_IN:
    view_rows = view_rows.where(F.pmod(F.hash('taxpayer_tin'), SAMPLE_1_IN) == 0)

has_action = F.col('sad_sid').isNotNull() | F.col('op_date_time').isNotNull() | F.col('inf').isNotNull()
actions = (view_rows.where(has_action).groupBy('instance_id')
                    .agg(F.size(F.collect_set(F.struct('sad_sid', 'op_date_time', 'inf'))).alias('inspection_actions')))
per_item = (view_rows.groupBy('instance_id', 'key_itm_nbr').agg(F.count('*').alias('copies'))
                     .join(actions, 'instance_id', 'left')
                     .fillna(0, subset=['inspection_actions']))
repeated = per_item.where('copies > 1')
explained = F.col('copies') == F.greatest('inspection_actions', F.lit(1))
z.show(repeated.select(F.count('*').alias('repeated items'),
                       F.avg(explained.cast('double')).alias('share whose copies = inspection actions on the declaration')))
z.show(repeated.orderBy(F.desc('copies')).limit(10))
""")

py('2.4 Values', r"""
# Customs value per item is very skewed, so percentiles say more than the average
q = [0.01, 0.25, 0.5, 0.75, 0.95, 0.99]
spread = eda.select(
    *[F.expr('percentile_approx(customs_value, %s)' % p).alias('value p%d' % round(100 * p)) for p in q],
    F.avg((F.coalesce('customs_value', F.lit(0)) <= 0).cast('double')).alias('share value 0 or blank'),
    F.avg((F.coalesce('net_weight', F.lit(0)) <= 0).cast('double')).alias('share weight 0 or blank'),
    F.avg((F.coalesce('supplementary_qnty', F.lit(0)) > 0).cast('double')).alias('share with units'))
z.show(spread)
""")

py('2.5 Goods', r"""
# Share of customs value by HS chapter, origin and APC (APC 000 = no exemption claimed).
# Choose the bar chart in the result to see it as a picture.
total_value = eda.agg(F.sum('customs_value')).first()[0]

def top10(column, label):
    return (eda.groupBy(column.alias(label))
               .agg((F.sum('customs_value') / total_value).alias('share_of_value'))
               .orderBy(F.desc('share_of_value')).limit(10))

z.show(top10(F.substring('hsc_cd', 1, 2), 'hs_chapter'))
""")

py('2.5 Origins', r"""
z.show(top10(F.col('gds_org_cty'), 'origin'))
""")

py('2.5 APCs', r"""
z.show(top10(F.col('cpc_cd'), 'apc'))
""")

py('2.6 Lanes and top-ups', r"""
# One row per declaration for these shares (lane, top-up flag and tax repeat on every item)
per_decl = eda.groupBy('instance_id').agg(F.max('is_red_flg').alias('red'), F.max('is_yellow_flg').alias('yellow'),
                                          F.max('top_up_flg').alias('flag'), F.max('original_tax_amt').alias('orig'))
z.show(per_decl.select(
    F.count('*').alias('declarations'),
    F.avg((F.col('red') == 1).cast('double')).alias('red lane'),
    F.avg((F.col('yellow') == 1).cast('double')).alias('yellow lane'),
    F.avg((F.col('flag') == 'Y').cast('double')).alias('top-up flag Y'),
    F.avg(F.col('orig').isNull().cast('double')).alias('original tax blank')))
""")


def _issue_table():
    lines = ['| Issue | What we saw | What the model does |', '|---|---|---|']
    for code, title, saw, rule, *_ in I.ISSUES:
        if code in REVIEW_ISSUES:
            lines.append(f'| **{code}** {title} | {saw} | {rule} |')
    return '\n'.join(lines)


md('2.7 The data problems', r"""
## 2.7 The data problems found

__ISSUES__

For each problem the next paragraph collects **every item row of the entries affected**, with entry, taxpayer,
goods, tax, lane and status columns, so the Risk Officers can say whether it is a real data problem or how the
system works. Two problems touch very many entries (E08, E09), so their tables keep a random 1 in 50 of the
entries; the summary says so. The tables are named after the problem, for example `ctrp_eda_e01`.
""".replace('__ISSUES__', _issue_table()))

py('2.8 Problem checks', r"""
# Every column the officers need to judge an entry, in the order of the officer workbooks
DETAIL = __DETAIL__
eda_rows = eda.select(*DETAIL)

def rows_of(selected, key='instance_id'):
    # Every item row of the declarations (or entries) in `selected`
    return eda_rows.join(selected.select(key).distinct(), key, 'left_semi').select(*DETAIL)

# One row per declaration, for the tax and lane checks
eda_decl = (eda_rows.groupBy('entry_key', 'instance_id')
                    .agg(F.max('top_up_flg').alias('flag'),
                         F.max('original_tax_amt').alias('orig_raw'),
                         F.max('final_amt').alias('fin'),
                         F.max('top_up_amt').alias('top_up_amt_max'),
                         F.max('is_red_flg').alias('red'),
                         F.max('is_yellow_flg').alias('yellow'))
                    .withColumn('orig', F.coalesce('orig_raw', 'fin'))
                    .cache())
flag, fin, orig_raw = F.col('flag'), F.col('fin'), F.col('orig_raw')
not_flagged = F.coalesce(flag, F.lit('N')) != 'Y'

def e01():
    ids = (eda_rows.groupBy('entry_key').agg(F.countDistinct('instance_id').alias('declaration_ids_on_entry'))
                   .where('declaration_ids_on_entry > 1'))
    return ids.join(eda_rows, 'entry_key').select('declaration_ids_on_entry', *DETAIL)

def e02():
    copies = (eda_rows.groupBy('instance_id', 'key_itm_nbr').agg(F.count('*').alias('copies_of_item'))
                      .where('copies_of_item > 1'))
    return copies.join(eda_rows, ['instance_id', 'key_itm_nbr']).select('copies_of_item', *DETAIL)

def e03():
    return eda_rows.where(~F.coalesce(F.col('taxpayer_tin'), F.lit('')).rlike('^[0-9]{10}$'))

def e04():
    return rows_of(eda_rows.where(F.col('decl_status') == 'Cancelled'))

def e05():
    return rows_of(eda_rows.where(F.col('cpc_cd') == '483'))

def e06():
    return rows_of(eda_decl.where((flag == 'Y') & ~(fin > F.col('orig'))))

def e07():
    return rows_of(eda_decl.where(not_flagged & orig_raw.isNotNull() & (fin > orig_raw)))

def e08():
    return rows_of(eda_decl.where(orig_raw.isNull()))

def e09():
    return rows_of(eda_decl.where(not_flagged & (F.col('top_up_amt_max') == fin) & (fin > 0)))

def e11():
    no_value = F.coalesce('customs_value', F.lit(0)) <= 0
    no_weight = F.coalesce('net_weight', F.lit(0)) <= 0
    return rows_of(eda_rows.where(no_value | no_weight))

# (code, title, check, keep 1 in K of the entries)
ISSUES = __ISSUES_LIST__

def sample(df, k):
    # A random 1 in k of the entries (all rows of each entry kept), when a problem touches too many to read
    return df if k == 1 else df.where(F.pmod(F.hash('entry_key'), k) == 0)

print('%d problem checks defined' % len(ISSUES))
""")

py('2.9 Run the checks', r"""
summary = []
for code, title, check, k in ISSUES:
    found = sample(check(), k).cache()
    n_found, n_rows = found.select('entry_key').distinct().count(), found.count()
    save(found, 'ctrp_eda_' + code.lower())
    summary.append((code, title, n_found, n_rows, k))
    print('%s  %-70s %10s %s  %10s rows' % (code, title[:70], format(n_found, ','),
                                           'entries ', format(n_rows, ',')))

eda_summary = pd.DataFrame(summary, columns=['issue', 'title', 'entries_or_taxpayers', 'rows', 'sample_1_in'])
save(eda_summary, 'ctrp_eda_summary')
z.show(eda_summary)
""")

py('2.10 Look at one problem', r"""
# Choose a problem in the list to see its first 200 rows (all rows are in the table named below)
code = z.select('Problem', [(c, c + ': ' + t) for c, t, _, _ in ISSUES], 'E01')
print('Table: ctrp_eda_' + code.lower())
z.show(spark.table('ctrp_eda_' + code.lower()).limit(200))
""")

md('2.11 What the EDA tells us', r"""
### What the EDA tells us

* Items repeat (the view joins three tables on the declaration ID only), so each item must be kept **once** before
  anything is counted (E02).
* Some entries sit under more than one declaration ID: one declaration per entry is kept (E01).
* Cancelled declarations, invalid TINs and APC 483 are not trade and must go (E03, E04, E05).
* Motor vehicles have their own model, so declarations with vehicles or their parts are left out.
* Values and weights span many orders of magnitude: comparisons must be **ratios** (price per kg against other
  importers), not raw amounts (2.2).
* Tax amounts sit on every item row of a declaration, so taxes are taken **once per declaration**.
* The top-up flag alone is not enough (E06), and `top_up_amt` holds the final tax on unflagged declarations (E09):
  a top-up is the flag **and** a rise in tax, measured as final tax minus original tax.
* Original tax is often blank when nothing changed (E08), so blank means "same as the final tax".
""")

# =========================================================================================
# 3. Clean
# =========================================================================================
md('3. Clean', r"""
## 3. Clean the rows

Each rule is a yes or no question asked of every row. A row is kept only if it passes every rule. The log shows
how many rows each rule removed, in order.

| Rule | Keeps | Why |
|---|---|---|
| R1 | TINs of 10 digits | a TIN identifies the taxpayer (E03) |
| R3 | declarations not cancelled | cancelled declarations are not trade (E04) |
| R4 | regimes IM4 (home use) and IM7 (bond) | the model is about imports |
| R13 | everything except APC 483 | destroyed or abandoned goods, dummy entries (E05) |
| R14 | the latest declaration ID of each entry | one entry, one declaration (E01) |
| R15 | declarations with no motor vehicle item (HS __MV_TEXT__) | separate motor vehicle model. The whole declaration goes, because tax and top-ups are recorded per declaration |
| R5 | each item once | the view repeats items (E02) |
""".replace('__MV_TEXT__', ', '.join(E.MOTOR_VEHICLE_HEADINGS)))

py('3.1 Apply the rules', r"""
def passes(condition):
    # A rule as a yes or no column (a blank answer counts as no)
    return F.coalesce(condition, F.lit(False))

def removed_by_rule(df, rules):
    # How many rows each rule removes, counting a row only at the first rule it fails
    passed_so_far, counts = F.lit(True), []
    for code, _ in rules:
        counts.append(F.sum((passed_so_far & ~F.col(code)).cast('int')).alias(code))
        passed_so_far = passed_so_far & F.col(code)
    return df.select(counts).first().asDict()

# Step 1: rules about one row at a time
ROW_RULES = [
    ('R1', 'TIN must be 10 digits', F.col('taxpayer_tin').rlike('^[0-9]{10}$')),
    ('R3', 'drop cancelled declarations', F.col('decl_status') != 'Cancelled'),
    ('R4', 'imports only: IM4 (home use) and IM7 (bond)', F.col('regime_cd').isin('IM4', 'IM7')),
    ('R13', 'drop APC 483', (F.coalesce(F.col('cpc_cd'), F.lit('')) != '483') if EXCLUDE_APC_483 else F.lit(True)),
]
step1 = rows.select('*', *[passes(test).alias(code) for code, _, test in ROW_RULES])
removed1 = removed_by_rule(step1, [(c, t) for c, t, _ in ROW_RULES])
row_rule_codes = [c for c, _, _ in ROW_RULES]
kept1 = step1.where(reduce(lambda a, b: a & b, [F.col(c) for c in row_rule_codes])).drop(*row_rule_codes)

# Step 2: rules that look at the other rows of the same entry, declaration or item
padded_id = F.lpad('instance_id', 20, '0')                      # so '99' does not sort above '100'
latest_id_of_entry = F.max(padded_id).over(Window.partitionBy('entry_key'))
is_vehicle = F.substring('hsc_cd', 1, 4).isin(MOTOR_VEHICLE_HEADINGS)
declaration_has_vehicle = F.max(F.when(is_vehicle, 1).otherwise(0)).over(Window.partitionBy('instance_id'))
copy_number = F.row_number().over(Window.partitionBy('instance_id', 'key_itm_nbr').orderBy('assessment_dt_wid'))
SET_RULES = [
    ('R14', 'latest declaration ID per entry',
     (padded_id == latest_id_of_entry) if LATEST_DECLARATION_PER_ENTRY else F.lit(True)),
    ('R15', 'drop motor vehicle declarations',
     (declaration_has_vehicle == 0) if EXCLUDE_MOTOR_VEHICLES else F.lit(True)),
    ('R5', 'keep each item once', copy_number == 1),
]
step2 = kept1.select('*', *[passes(test).alias(code) for code, _, test in SET_RULES]).cache()
removed2 = removed_by_rule(step2, [(c, t) for c, t, _ in SET_RULES])
items = step2.where(F.col('R14') & F.col('R15') & F.col('R5')).drop('R14', 'R15', 'R5').cache()
n_items = items.count()
step2.unpersist()

# The cleaning log
log, left = [], n_loaded
for code, text, _ in ROW_RULES + SET_RULES:
    gone = {**removed1, **removed2}[code]
    log.append((code, text, left, gone, left - gone))
    left -= gone
assert left == n_items, 'the log does not add up'
cleaning_log = pd.DataFrame(log, columns=['rule', 'what it does', 'rows before', 'rows removed', 'rows left'])
save(cleaning_log, 'ctrp_cleaning_log')
z.show(cleaning_log)
""")

py('3.2 After cleaning', r"""
print('Clean item rows: {:,}   declarations: {:,}   taxpayers: {:,}'.format(
    n_items, items.select('instance_id').distinct().count(), items.select('taxpayer_tin').distinct().count()))
""")

# =========================================================================================
# 4. Declarations
# =========================================================================================
md('4. Declarations', r"""
## 4. From item rows to declarations

Many features count **declarations** (for example "share of declarations amended"). Tax, top-up, lane and status
are the same on every item of a declaration, so the items are grouped into one row per declaration:

* **Value** = the sum of the items' customs values. **Items** = how many items.
* **Original tax**: blank means unchanged, so it is filled with the final tax (E08).
* **Topped up** = the top-up flag is `Y` **and** the final tax is above the original tax (E06).
  **Top-up amount** = final tax minus original tax (E09: `top_up_amt` is not used).
* **Tax reduced** = the final tax is below the original tax.
* **Severe top-up** = a top-up of 30% or more of the final tax.
""")

py('4.1 Declarations', r"""
decl = (items.groupBy('instance_id')
             .agg(F.max('taxpayer_tin').alias('taxpayer_tin'),
                  F.max('taxpayer_nm').alias('taxpayer_nm'),
                  F.max('adate').alias('adate'),
                  F.max('assessment_dt_wid').alias('dt'),
                  F.max('regime_cd').alias('regime'),
                  F.coalesce(F.max('original_tax_amt'), F.max('final_amt')).alias('orig_tax'),   # blank = unchanged
                  F.max('final_amt').alias('final_tax'),
                  F.max('top_up_flg').alias('top_up_flg'),
                  F.max('amendment_flg').alias('amended'),
                  F.max('clearance_station_cd').alias('station'),
                  F.max('is_red_flg').alias('red'),
                  F.max('is_yellow_flg').alias('yellow'),
                  F.max('pay_status').alias('pay_status'),
                  F.sum('customs_value').alias('value'),
                  F.count('*').alias('n_items')))

topped_up = (F.col('top_up_flg') == 'Y') & (F.col('final_tax') > F.col('orig_tax'))
decl = (decl.withColumn('topped_up', F.when(topped_up, 1).otherwise(0))
            .withColumn('top_up', F.when(topped_up, F.col('final_tax') - F.col('orig_tax')).otherwise(0.0))
            .withColumn('negative_top_up', F.when(F.col('final_tax') < F.col('orig_tax'), 1).otherwise(0))
            .withColumn('severe', F.when((F.col('topped_up') == 1)
                                         & (F.col('top_up') >= 0.30 * F.col('final_tax')), 1).otherwise(0))
            .cache())

# The 24-month history window used by the features (never anything after the snapshot)
in_history = (F.col('dt') > HIST_START) & (F.col('dt') <= SNAP)
hist = decl.where(in_history).cache()
hist_items = items.where((F.col('assessment_dt_wid') > HIST_START) & (F.col('assessment_dt_wid') <= SNAP)).cache()
print('Declarations in the 24 months: {:,}'.format(hist.count()))
peek(hist.select('instance_id', 'taxpayer_tin', 'dt', 'regime', 'n_items', 'value', 'orig_tax', 'final_tax',
                 'top_up_flg', 'topped_up', 'top_up', 'severe', 'negative_top_up', 'amended', 'red', 'yellow',
                 'station'))
""")

md('4.2 One row per taxpayer', r"""
### 4.2 One row per taxpayer: the starting table

Every taxpayer with at least one clean declaration in the 24 months gets a row. Each feature below is built as a
small table (one row per taxpayer) and kept in `parts`; Part 8 puts them side by side.
""")

py('4.2 Starting table', r"""
base = (hist.groupBy('taxpayer_tin')
            .agg(F.max(F.struct('dt', 'taxpayer_nm')).getField('taxpayer_nm').alias('taxpayer_nm'),  # latest name
                 F.count('*').alias('decl_24m_count'),                     # declarations in 24 months
                 F.sum('value').alias('customs_value_24m_ugx'),
                 F.sum('orig_tax').alias('original_tax_24m_ugx'),
                 F.sum('top_up').alias('top_up_24m_ugx'))
            .cache())
parts = {}
print('Taxpayers: {:,}'.format(base.count()))
peek(base)
""")

# =========================================================================================
# 5. Track A
# =========================================================================================
md('5. Track A', r"""
## 5. Track A: the compliance history (8 features)

These are the scored parameters agreed with the Risk Officers. Each is a **rate**, so a large and a small importer
can be compared fairly. Here they are first built over 24 months; Part 7 then gives recent years more weight (the
`3y` versions) and protects small traders, as production does.

| Feature the scorecard reads | Parameter | Points (likelihood x impact) |
|---|---|---|
__TRACK_A_TABLE__
""".replace('__TRACK_A_TABLE__', '\n'.join(
    f"| `{TRACK_A_NAMES[p['col']]}` | {p['code']} {p['label']} | L{p['L']} x I{p['I']}, "
    f"scale {p['zero_at']:g} to {p['one_at']:g} |" for p in M.PARAMS)))

md('5.1', r"""
### 5.1 `topped_up_per_decl_24m_rate`: declarations topped up (PAR_045T, the officers' rule)

**Inputs:** `topped_up` (0 or 1 per declaration, Part 4). **Logic:** topped-up declarations ÷ declarations.
**Why:** a taxpayer often found under-declaring is likely to be found again.
""")
py('5.1 topped_up_per_decl_24m_rate', r"""
parts['topped_up_per_decl_24m_rate'] = hist.groupBy('taxpayer_tin').agg(F.avg('topped_up').alias('topped_up_per_decl_24m_rate'))
peek(base.join(parts['topped_up_per_decl_24m_rate'], 'taxpayer_tin').select('taxpayer_tin', 'decl_24m_count', 'topped_up_per_decl_24m_rate'))
""")

md('5.2', r"""
### 5.2 `severe_top_up_per_decl_24m_rate`: severe top-ups (PAR_077)

**Inputs:** `severe` (0 or 1: a top-up of 30% or more of the final tax). **Logic:** severe top-ups ÷ declarations.
**Why:** a large correction says more about intent than a small one.
""")
py('5.2 severe_top_up_per_decl_24m_rate', r"""
parts['severe_top_up_per_decl_24m_rate'] = (hist.groupBy('taxpayer_tin')
                                         .agg(F.avg('severe').alias('severe_top_up_per_decl_24m_rate')))
peek(parts['severe_top_up_per_decl_24m_rate'])
""")

md('5.3', r"""
### 5.3 `amended_per_decl_24m_rate`: declarations amended (PAR_045, also in Track B)

**Inputs:** `amendment_flg` (`Y` or `N`). **Logic:** amended declarations ÷ declarations.
**Why:** declarations that are often wrong the first time.
""")
py('5.3 amended_per_decl_24m_rate', r"""
is_amended = F.when(F.col('amended') == 'Y', 1.0).otherwise(0.0)
parts['amended_per_decl_24m_rate'] = (hist.groupBy('taxpayer_tin')
                                         .agg(F.avg(is_amended).alias('amended_per_decl_24m_rate')))
peek(parts['amended_per_decl_24m_rate'])
""")

md('5.4', r"""
### 5.4 `top_up_per_final_tax_24m_rate`: top-ups as a share of the final tax (PAR_048)

**Inputs:** `top_up_24m_ugx`, `original_tax_24m_ugx` (UGX, Part 4.2). **Logic:** top-ups ÷ (original tax + top-ups),
measured over the final tax so it stays between 0 and 1. **Why:** how much of what the taxpayer finally paid had
to be found by customs.
""")
py('5.4 top_up_per_final_tax_24m_rate', r"""
final_tax = F.col('original_tax_24m_ugx') + F.col('top_up_24m_ugx')
parts['top_up_per_final_tax_24m_rate'] = base.select(
    'taxpayer_tin', F.when(final_tax > 0, F.col('top_up_24m_ugx') / final_tax).alias('top_up_per_final_tax_24m_rate'))
peek(parts['top_up_per_final_tax_24m_rate'])
""")

md('5.5', r"""
### 5.5 `tax_reduced_per_decl_24m_rate`: tax reduced after assessment (PAR_066)

**Inputs:** `negative_top_up` (0 or 1). **Logic:** declarations whose final tax fell below the original ÷
declarations. **Why:** frequent reductions can point to errors or to pressure on assessments.
""")
py('5.5 tax_reduced_per_decl_24m_rate', r"""
parts['tax_reduced_per_decl_24m_rate'] = (hist.groupBy('taxpayer_tin')
                                           .agg(F.avg('negative_top_up').alias('tax_reduced_per_decl_24m_rate')))
peek(parts['tax_reduced_per_decl_24m_rate'])
""")

md('5.6', r"""
### 5.6 `top_up_last_180d_flag`: a top-up in the last 180 days (PAR_105)

**Inputs:** `adate` of topped-up declarations. **Logic:** days from the last top-up to the snapshot. The feature is
1 if that is 180 days or fewer, else 0 (also 0 when there was no top-up). **Why:** recent non-compliance matters
more than old.
""")
py('5.6 top_up_last_180d_flag', r"""
last_top_up = F.max(F.when(F.col('topped_up') == 1, F.col('adate')))
days = hist.groupBy('taxpayer_tin').agg(F.datediff(snap_date, last_top_up).alias('days_since_last_top_up'))
parts['top_up_last_180d_flag'] = days.withColumn(
    'top_up_last_180d_flag', F.when(F.col('days_since_last_top_up') <= 180, 1.0).otherwise(0.0))
peek(parts['top_up_last_180d_flag'])
""")

md('5.7', r"""
### 5.7 `away_from_main_station_per_decl_24m_rate`: clearing away from the main station (PAR_023, also in Track B)

**Inputs:** `clearance_station_cd` per declaration. **Logic:** count declarations per station. The main station is
the busiest. The feature is 1 − the main station's share. **Why:** moving between stations can be a search for
easier checks.
""")
py('5.7 away_from_main_station_per_decl_24m_rate', r"""
per_station = hist.groupBy('taxpayer_tin', 'station').count()          # a blank station counts as one station
parts['away_from_main_station_per_decl_24m_rate'] = (per_station.groupBy('taxpayer_tin')
                                             .agg((F.max('count') / F.sum('count')).alias('main_station_per_decl_24m_rate'))
                                             .withColumn('away_from_main_station_per_decl_24m_rate', 1.0 - F.col('main_station_per_decl_24m_rate')))
peek(parts['away_from_main_station_per_decl_24m_rate'])
""")

md('5.8', r"""
### 5.8 `peer_price_shortfall_per_value_24m_rate`: value below other importers' price (PAR_076, also in Track B)

This one needs a **benchmark**: the middle (median) price that importers declare for the same goods.

**Inputs:** `customs_value`, `net_weight`, `supplementary_qnty`, `hsc_cd`, `gds_org_cty` (item rows).

**Logic, step by step:**
1. Price per kg = value ÷ weight. Price per unit = value ÷ units (where units are given).
2. Benchmark per HS code: the median price per kg and per unit of all items, if at least 5 different importers
   bring that code. Where 5 or more bring it **from the same origin**, that origin's median is used instead
   (goods of one code differ in price by origin).
3. Each item is then marked:
   * **keying error** if its price per kg is under 1% of the benchmark (most likely a weight in the wrong unit, so it is kept out);
   * **low price** if it is under half the benchmark per kg (and per unit where units exist);
   * **shortfall** = how much more it would be worth at the benchmark price (the smaller of the per-kg and per-unit
     figures).
4. Per taxpayer: shortfall on low-priced items ÷ the taxpayer's benchmarked value.

**Why:** undervaluation is the main revenue risk at import. The same item table gives four Track B features (6.3).
""")
py('5.8 peer_price_shortfall_per_value_24m_rate', r"""
priced = (hist_items.where((F.col('customs_value') > 0) & (F.col('net_weight') > 0))
                    .withColumn('price_kg', F.col('customs_value') / F.col('net_weight'))
                    .withColumn('price_unit', F.when(F.col('supplementary_qnty') > 0,
                                                     F.col('customs_value') / F.col('supplementary_qnty'))))

def benchmark(keys, suffix=''):
    # The median price per kg and per unit, where at least 5 importers bring the goods
    return (priced.groupBy(*keys)
                  .agg(median('price_kg').alias('med_kg' + suffix), median('price_unit').alias('med_unit' + suffix),
                       F.countDistinct('taxpayer_tin').alias('importers'))
                  .where('importers >= 5').drop('importers'))

on_origin = F.col('med_kg_o').isNotNull()
it = (priced.join(benchmark(['hsc_cd']), 'hsc_cd')                                   # an HS benchmark is needed
            .join(benchmark(['hsc_cd', 'gds_org_cty'], '_o'), ['hsc_cd', 'gds_org_cty'], 'left')
            .withColumn('bm_kg', F.when(on_origin, F.col('med_kg_o')).otherwise(F.col('med_kg')))
            .withColumn('bm_unit', F.when(on_origin, F.col('med_unit_o')).otherwise(F.col('med_unit')))
            .withColumn('on_origin_bench', on_origin.cast('int')))

price_kg, bm_kg, bm_unit, units = F.col('price_kg'), F.col('bm_kg'), F.col('bm_unit'), F.col('supplementary_qnty')
low_per_unit_too = bm_unit.isNull() | units.isNull() | (units <= 0) | (F.col('customs_value') / units < 0.5 * bm_unit)
gap_per_kg = bm_kg * F.col('net_weight') - F.col('customs_value')
gap_per_unit = F.when((units > 0) & bm_unit.isNotNull(), bm_unit * units - F.col('customs_value'))
it = (it.withColumn('implausible', F.when(price_kg < 0.01 * bm_kg, 1).otherwise(0))
        .withColumn('low_price', F.when((price_kg < 0.5 * bm_kg) & (price_kg >= 0.01 * bm_kg) & low_per_unit_too, 1)
                                  .otherwise(0))
        .withColumn('shortfall', F.least(gap_per_kg, gap_per_unit))                  # the smaller one
        .withColumn('price_deviation', F.abs(F.log(price_kg / bm_kg)))
        .cache())

counted_shortfall = F.when((F.col('low_price') == 1) & (F.col('shortfall') > 0), F.col('shortfall')).otherwise(0)
parts['peer_price_shortfall_per_value_24m_rate'] = it.groupBy('taxpayer_tin').agg(
    F.count('*').alias('priced_items_24m_count'),
    (F.sum(counted_shortfall) / F.sum('customs_value')).alias('peer_price_shortfall_per_value_24m_rate'))
peek(it.select('taxpayer_tin', 'hsc_cd', 'gds_org_cty', 'customs_value', 'net_weight', 'price_kg', 'bm_kg',
               'implausible', 'low_price', 'shortfall'))
""")
py('5.8 taxpayers with a shortfall', r"""
peek(parts['peer_price_shortfall_per_value_24m_rate'].where('peer_price_shortfall_per_value_24m_rate > 0'))
""")

# =========================================================================================
# 6. Track B
# =========================================================================================
md('6. Track B', r"""
## 6. Track B: how the taxpayer trades (17 features)

Track B looks for risk the current checks have not yet caught, so it uses **no** input that records what customs
did (no top-ups, no lanes). Three of its features were built above: `amended_per_decl_24m_rate` (5.3),
`peer_price_shortfall_per_value_24m_rate` (5.8) and `away_from_main_station_per_decl_24m_rate` (5.7).
""")

md('6.1', r"""
### 6.1 `unpaid_tax_per_decl_24m_rate`: tax left unpaid (stand-in for PAR_072)

**Inputs:** `pay_status`, `final_amt`. **Logic:** declarations with tax due and status `NOT_PAID` ÷ declarations.
**Why:** unpaid tax is non-compliance in itself.
""")
py('6.1 unpaid_tax_per_decl_24m_rate', r"""
unpaid = F.when((F.col('pay_status') == 'NOT_PAID') & (F.col('final_tax') > 0), 1.0).otherwise(0.0)
parts['unpaid_tax_per_decl_24m_rate'] = hist.groupBy('taxpayer_tin').agg(F.avg(unpaid).alias('unpaid_tax_per_decl_24m_rate'))
peek(parts['unpaid_tax_per_decl_24m_rate'])
""")

md('6.2', r"""
### 6.2 `pref_claimed_per_item_24m_rate`: preferential treatment claimed (PAR_050)

**Inputs:** `preferential_treatment_flag` (item rows). **Logic:** items claiming preference ÷ items.
**Why:** a false origin claim (EAC, COMESA) avoids duty.
""")
py('6.2 pref_claimed_per_item_24m_rate', r"""
claims = F.when(F.col('preferential_treatment_flag') == 'Y', 1.0).otherwise(0.0)
parts['pref_claimed_per_item_24m_rate'] = (hist_items.groupBy('taxpayer_tin')
                                                 .agg(F.avg(claims).alias('pref_claimed_per_item_24m_rate')))
peek(parts['pref_claimed_per_item_24m_rate'])
""")

md('6.3', r"""
### 6.3 The other price features (from the item table in 5.8)

| Feature | Logic | Why |
|---|---|---|
| `price_keying_error_per_item_24m_rate` | items under 1% of the benchmark ÷ items | repeated "keying errors" can hide value |
| `price_under_half_peer_per_item_24m_rate` | items under half the benchmark ÷ items | how often prices are low (5.8 gives how much) |
| `median_price_dev_from_peer_24m_log` | the taxpayer's median distance from the benchmark, either way, on a log scale (keying errors left out) | prices far from other importers, up or down (stand-in for PAR_090) |
| `priced_on_coo_peer_per_item_24m_rate` | share of items priced against their own origin's benchmark | context only, not scored |
""")
py('6.3 price features', r"""
parts['price_features'] = it.groupBy('taxpayer_tin').agg(
    F.avg('implausible').alias('price_keying_error_per_item_24m_rate'),
    F.avg('low_price').alias('price_under_half_peer_per_item_24m_rate'),
    median('CASE WHEN implausible = 0 THEN price_deviation END').alias('median_price_dev_from_peer_24m_log'),
    F.avg('on_origin_bench').alias('priced_on_coo_peer_per_item_24m_rate'))
peek(parts['price_features'])
""")

md('6.4', r"""
### 6.4 `own_price_drop_per_recent_value_6m_rate`: price dropped against the taxpayer's own history (stand-in for PAR_067)

**Inputs:** `customs_value`, `net_weight`, `supplementary_qnty`, `hsc_cd`, `adate`.

**Logic:** for each tariff code the taxpayer imported both in the **last 6 months** and in the **18 months before**
(at least 2 earlier items and 1 recent), compare its own median price recently with before. A code counts as a drop
when the recent price is under 70% of the earlier one (per kg, and per unit where given). The feature is the share
of recent value on such codes. **Why:** a trader who suddenly declares the same goods cheaper may have started
undervaluing.
""")
py('6.4 own_price_drop_per_recent_value_6m_rate', r"""
six_months_back = F.add_months(snap_date, -6)
late, early = F.col('adate') > six_months_back, F.col('adate') <= six_months_back
own = (priced.withColumn('early_kg', F.when(early, F.col('price_kg')))
             .withColumn('late_kg', F.when(late, F.col('price_kg')))
             .withColumn('early_u', F.when(early, F.col('price_unit')))
             .withColumn('late_u', F.when(late, F.col('price_unit')))
             .groupBy('taxpayer_tin', 'hsc_cd')
             .agg(median('early_kg').alias('early_kg'), median('late_kg').alias('late_kg'),
                  median('early_u').alias('early_u'), median('late_u').alias('late_u'),
                  F.sum(F.when(late, F.col('customs_value')).otherwise(0)).alias('late_value'),
                  F.sum(early.cast('int')).alias('n_early'), F.sum(late.cast('int')).alias('n_late')))
own = own.where((F.col('n_early') >= 2) & (F.col('n_late') >= 1) & (F.col('early_kg') > 0))

dropped = ((F.col('late_kg') < 0.7 * F.col('early_kg'))
           & (F.col('early_u').isNull() | F.col('late_u').isNull() | (F.col('late_u') < 0.7 * F.col('early_u'))))
parts['own_price_drop_per_recent_value_6m_rate'] = own.groupBy('taxpayer_tin').agg(
    F.count('*').alias('hs_codes_compared_count'),
    (F.sum(F.when(dropped, F.col('late_value')).otherwise(0)) / F.sum('late_value')).alias('own_price_drop_per_recent_value_6m_rate'))
peek(own)
""")

md('6.5', r"""
### 6.5 `duty_under_half_peer_per_value_24m_rate` and `duty_gap_vs_peer_per_value_24m_rate`: duty below other importers (stand-ins for PAR_096, PAR_016)

**Inputs:** `tax_assessed`, `customs_value`, `hsc_cd`, `cpc_cd`.

**Logic:** for each tariff code, the median tax rate (tax ÷ value) that importers pay **with no exemption claimed**
(APC `000`), if at least 5 importers. Then, among the taxpayer's own APC `000` items:
* `duty_under_half_peer_per_value_24m_rate` = value taxed at under half that rate ÷ value;
* `duty_gap_vs_peer_per_value_24m_rate` = the missing tax (median rate × value − tax paid) ÷ value.

Items under an exemption APC are left out on purpose: a lower rate is expected there. **Why:** paying much less than
others for the same goods points to a wrong tariff code or rate.
""")
py('6.5 duty features', r"""
taxed = (hist_items.where((F.col('customs_value') > 0) & (F.col('tax_assessed') >= 0))
                   .withColumn('rate', F.col('tax_assessed') / F.col('customs_value')))
duty_bench = (taxed.where(F.col('cpc_cd') == '000').groupBy('hsc_cd')
                   .agg(median('rate').alias('med_rate'), F.countDistinct('taxpayer_tin').alias('importers'))
                   .where('importers >= 5').drop('importers'))
taxed = taxed.join(duty_bench, 'hsc_cd', 'left')

compared = (F.col('cpc_cd') == '000') & (F.col('med_rate') > 0)          # no exemption, and a benchmark exists
value_compared = F.sum(F.when(compared, F.col('customs_value')).otherwise(0))
low_rate = compared & (F.col('rate') < 0.5 * F.col('med_rate'))
missing_tax = F.greatest(F.col('med_rate') * F.col('customs_value') - F.col('tax_assessed'), F.lit(0))
parts['duty_features'] = taxed.groupBy('taxpayer_tin').agg(
    (F.sum(F.when(low_rate, F.col('customs_value')).otherwise(0)) / value_compared).alias('duty_under_half_peer_per_value_24m_rate'),
    (F.sum(F.when(compared, missing_tax).otherwise(0)) / value_compared).alias('duty_gap_vs_peer_per_value_24m_rate'))
peek(parts['duty_features'])
""")

md('6.6', r"""
### 6.6 `exempt_apc_per_value_24m_rate` and `watchlist_apc_per_value_24m_rate` (PAR_052, PAR_053)

**Inputs:** `cpc_cd`, `customs_value`. **Logic:** value under any APC other than `000` ÷ value; and value under the
11 APCs the AC-Trade memo marks "look out for possible abuse" ÷ value. **Why:** exemptions are a known route for
revenue loss.
""")
py('6.6 APC features', r"""
WATCHLIST = __WATCHLIST__
valued = hist_items.where(F.col('customs_value') > 0)
value_under = lambda test: F.sum(F.when(test, F.col('customs_value')).otherwise(0)) / F.sum('customs_value')
parts['apc_features'] = valued.groupBy('taxpayer_tin').agg(
    value_under(F.col('cpc_cd') != '000').alias('exempt_apc_per_value_24m_rate'),
    value_under(F.col('cpc_cd').isin(WATCHLIST)).alias('watchlist_apc_per_value_24m_rate'))
peek(parts['apc_features'])
""")

md('6.7', r"""
### 6.7 `same_day_split_per_decl_vs_norm_24m_diff`: same-day splitting above the norm (raised by the officers)

**Inputs:** `hsc_cd`, `assessment_dt_wid`, `instance_id`, `extended_proc_cd`.

**Logic:**
1. Count each taxpayer's declarations per tariff code per day (`n`). Cement and salt (chapter 25), fuel (chapter 27)
   and fuel transit (EPC 4080, 7180) are left out: they arrive as many trucks a day for good reason.
2. The **norm** for each tariff code: across all importers, the share of declarations that came as same-day repeats
   (`n` of 2 or more).
3. The taxpayer's own share in same-day repeats, minus the norm for its own mix of goods.

**Why:** splitting one consignment can keep each declaration under a value or check threshold.
""")
py('6.7 same_day_split_per_decl_vs_norm_24m_diff', r"""
splittable = hist_items.where(~F.substring('hsc_cd', 1, 2).isin('25', '27')
                              & ~F.coalesce(F.col('extended_proc_cd'), F.lit('')).isin('4080', '7180'))
per_day = (splittable.groupBy('taxpayer_tin', 'assessment_dt_wid', 'hsc_cd')
                     .agg(F.countDistinct('instance_id').alias('n'))
                     .withColumn('n_repeat', F.when(F.col('n') >= 2, F.col('n')).otherwise(0)))
norm = per_day.groupBy('hsc_cd').agg((F.sum('n_repeat') / F.sum('n')).alias('norm_share'))
parts['same_day_split_per_decl_vs_norm_24m_diff'] = (per_day.join(norm, 'hsc_cd').groupBy('taxpayer_tin')
    .agg((F.sum('n_repeat') / F.sum('n')).alias('same_day_split_per_decl_24m_rate'),
         (F.sum(F.col('n') * F.col('norm_share')) / F.sum('n')).alias('same_day_norm_per_decl_24m_rate'))
    .withColumn('same_day_split_per_decl_vs_norm_24m_diff', F.col('same_day_split_per_decl_24m_rate') - F.col('same_day_norm_per_decl_24m_rate')))
peek(per_day.orderBy(F.desc('n')))
""")

md('6.8', r"""
### 6.8 `decl_90d_per_avg_qtr_24m_log`: sudden rise in declarations

**Inputs:** `adate` per declaration. **Logic:** declarations in the last 90 days against the average quarter over
the 24 months (24 months ÷ 8 quarters), on a log scale: `log((last 90 days + 1) / (average quarter + 1))`.
0 = a normal quarter, +1.1 = about 3 times normal. **Why:** a sharp jump can mean a borrowed TIN or a burst before
disappearing.
""")
py('6.8 decl_90d_per_avg_qtr_24m_log', r"""
recent = F.when(F.col('adate') > F.date_sub(snap_date, 90), 1).otherwise(0)
parts['decl_90d_per_avg_qtr_24m_log'] = (hist.groupBy('taxpayer_tin')
                      .agg(F.count('*').alias('_n'), F.sum(recent).alias('decl_90d_count'))
                      .withColumn('decl_90d_per_avg_qtr_24m_log', F.log((F.col('decl_90d_count') + 1) / (F.col('_n') / 8.0 + 1)))
                      .drop('_n'))
peek(parts['decl_90d_per_avg_qtr_24m_log'].orderBy(F.desc('decl_90d_per_avg_qtr_24m_log')))
""")

md('6.9', r"""
### 6.9 `hs4_per_decl_24m_ratio`: many kinds of goods per declaration

* `hs4_per_decl_24m_ratio` = different 4-digit HS headings ÷ declarations. **Why:** mixing many goods makes checks harder and
  can hide misdescribed items.
""")
py('6.9 hs4_per_decl_24m_ratio', r"""
heading = F.substring('hsc_cd', 1, 4)
headings = hist_items.groupBy('taxpayer_tin').agg(F.countDistinct(heading).alias('hs4_24m_count'))
per_declaration = F.col('hs4_24m_count') / F.greatest('decl_24m_count', F.lit(1))
parts['hs4_per_decl_24m_ratio'] = (base.select('taxpayer_tin', 'decl_24m_count').join(headings, 'taxpayer_tin', 'left')
                             .withColumn('hs4_per_decl_24m_ratio', per_declaration)
                             .drop('decl_24m_count'))
peek(parts['hs4_per_decl_24m_ratio'])
""")

md('6.10', r"""
### 6.10 `new_importer_24m_score`: recently started importing (PAR_019, PAR_101)

**Inputs:** `adate`, and the taxpayers who declared IM4 or IM7 in the 3 years **before** the 24-month window.
**Logic:** `new_trader` = not among them. `new_importer_24m_score` = −log(1 + days since the first declaration in the window), plus 1
for a new trader, so newer gives a higher value. **Why:** new traders have no track record, and new TINs are used for
one-off fraud.
""")
py('6.10 new_importer_24m_score', r"""
day = F.col('assessment_dt_wid').cast('string')
earlier_importers = (spark.table(VIEW)
    .where((day > PRIOR_START) & (day <= HIST_START)
           & F.col('regime_cd').isin('IM4', 'IM7') & (F.col('decl_status') != 'Cancelled')
           & F.col('taxpayer_tin').cast('string').rlike('^[0-9]{10}$'))
    .select(F.col('taxpayer_tin').cast('string').alias('taxpayer_tin')).distinct()
    .withColumn('imported_before', F.lit(1)))

days_since_first = F.datediff(snap_date, F.min('adate'))
first_seen = hist.groupBy('taxpayer_tin').agg(days_since_first.alias('days_since_first_decl_24m'))
parts['new_importer_24m_score'] = (first_seen.join(earlier_importers, 'taxpayer_tin', 'left')
    .withColumn('new_trader', F.when(F.col('imported_before').isNull(), 'Y').otherwise('N'))
    .withColumn('new_importer_24m_score', -F.log1p(F.greatest('days_since_first_decl_24m', F.lit(0)))
                           + F.when(F.col('new_trader') == 'Y', 1.0).otherwise(0.0))
    .drop('imported_before'))
peek(parts['new_importer_24m_score'])
""")

# =========================================================================================
# 7. After the features
# =========================================================================================
md('7. After the features', r"""
## 7. Steps after the features

Three steps turn the features into what the scorecard and the model read. They are the same as in production.

1. **Recency (Track A).** Recent years count more: over the last **3 years**, each declaration counts 1 in the latest
   year, 0.5 in the year before and 0.25 in the one before that. Tested on 18 dates since 2017: better than two equal
   years on all 18. Applies to the top-up, severe top-up, amendment and tax-reduction rates and the top-up share.
2. **Small numbers (both tracks).** A rate built on 2 declarations is mostly luck. Each rate is pulled towards the
   average of everyone by weight `n / (n + 10)`, where `n` is the taxpayer's declarations (items for the price
   features). It is only ever pulled **down**, so a clean small trader is never given other people's behaviour.
   Example: 1 amended declaration out of 2 (50%), average 15%: weight 2/12 = 0.17, so 0.17 × 50% + 0.83 × 15% ≈ 21%.
3. **Peer groups (Track B).** Each Track B feature becomes a **percentile within the peer group**: the HS section of
   the taxpayer's main goods × its size (small, medium, large by customs value within that section). "Higher than 97%
   of similar importers" is fair across goods and sizes, and reads directly as a reason. A blank sits at 50%.
""")

py('7.1 Recency', r"""
# Each declaration of the last 3 years gets a weight by how long ago it was; the rates become weighted averages
year_weight = (F.when(F.col('adate') > F.add_months(snap_date, -12), 1.0)
                .when(F.col('adate') > F.add_months(snap_date, -24), 0.5)
                .otherwise(0.25))
w = F.col('w')

def weighted_rate(column):
    # (1 x count in year 1 + 0.5 x count in year 2 + 0.25 x count in year 3) / (the same for declarations)
    return F.sum(w * column) / F.sum(w)

amended_01 = F.when(F.col('amended') == 'Y', 1).otherwise(0)
final_tax_w = F.col('_orig_tax') + F.col('_top_up')
recency = (decl.where(F.col('dt') <= SNAP).withColumn('w', year_weight)
               .groupBy('taxpayer_tin')
               .agg(weighted_rate(F.col('topped_up')).alias('topped_up_per_decl_3y_rate'),
                    weighted_rate(F.col('severe')).alias('severe_top_up_per_decl_3y_rate'),
                    weighted_rate(amended_01).alias('amended_per_decl_3y_rate'),
                    weighted_rate(F.col('negative_top_up')).alias('tax_reduced_per_decl_3y_rate'),
                    F.sum(w * F.col('top_up')).alias('_top_up'),
                    F.sum(w * F.col('orig_tax')).alias('_orig_tax'))
               .withColumn('top_up_per_final_tax_3y_rate', F.when(final_tax_w > 0, F.col('_top_up') / final_tax_w))
               .drop('_top_up', '_orig_tax'))
parts['recency'] = recency
peek(base.join(parts['topped_up_per_decl_24m_rate'], 'taxpayer_tin').join(recency, 'taxpayer_tin')
         .select('taxpayer_tin', 'decl_24m_count', 'topped_up_per_decl_24m_rate', 'topped_up_per_decl_3y_rate'))
""")

py('7.2 One table', r"""
# Every part side by side: one row per taxpayer (small enough to work on in pandas from here)
feature_inputs = reduce(lambda table, part: table.join(part, 'taxpayer_tin', 'left'), parts.values(), base)
save(feature_inputs, 'ctrp_feature_inputs')
tp = feature_inputs.orderBy('taxpayer_tin').toPandas()
print('{:,} taxpayers x {} columns'.format(*tp.shape))
peek(tp)
""")

py('7.3 Small numbers', r"""
def credibility(rate, n, k=10):
    # Pull a rate towards the average of everyone by weight n / (n + k), and only ever down
    rate, n = rate.astype(float), n.fillna(0).astype(float)
    has = rate.notna() & (n > 0)
    average = (rate[has] * n[has]).sum() / n[has].sum()          # weighted by declarations (or items)
    w = n / (n + k)
    return np.minimum(rate, w * rate + (1 - w) * average)

# Track A: the 8 scored features, each with the count it rests on.
# Five use the 3-year (recency) version from 7.1, three stay at 24 months.
TRACK_A = {'topped_up_per_decl_3y_rate': 'decl_24m_count',
           'severe_top_up_per_decl_3y_rate': 'decl_24m_count',
           'amended_per_decl_3y_rate': 'decl_24m_count',
           'top_up_per_final_tax_3y_rate': 'decl_24m_count',
           'peer_price_shortfall_per_value_24m_rate': 'priced_items_24m_count',
           'tax_reduced_per_decl_3y_rate': 'decl_24m_count',
           'top_up_last_180d_flag': 'decl_24m_count',
           'away_from_main_station_per_decl_24m_rate': 'decl_24m_count'}

final = tp[['taxpayer_tin', 'taxpayer_nm', 'decl_24m_count', 'customs_value_24m_ugx', 'top_up_24m_ugx']].copy()
final.insert(1, 'snapshot_date', SNAPSHOT)
for col, n in TRACK_A.items():
    final['raw_' + col] = tp[col]                        # before the small-numbers step (shown in reasons)
    final[col] = credibility(tp[col], tp[n])             # what the scorecard reads

# Track B: 17 features, all over 24 months. The five rates resting on a count get the same small-numbers step.
TRACK_B = {'amended_per_decl_24m_rate': 'decl_24m_count',
           'unpaid_tax_per_decl_24m_rate': 'decl_24m_count',
           'price_keying_error_per_item_24m_rate': 'priced_items_24m_count',
           'peer_price_shortfall_per_value_24m_rate': 'priced_items_24m_count',
           'price_under_half_peer_per_item_24m_rate': 'priced_items_24m_count',
           'median_price_dev_from_peer_24m_log': None,
           'own_price_drop_per_recent_value_6m_rate': None,
           'duty_under_half_peer_per_value_24m_rate': None,
           'duty_gap_vs_peer_per_value_24m_rate': None,
           'exempt_apc_per_value_24m_rate': None,
           'watchlist_apc_per_value_24m_rate': None,
           'pref_claimed_per_item_24m_rate': None,
           'decl_90d_per_avg_qtr_24m_log': None,
           'away_from_main_station_per_decl_24m_rate': None,
           'hs4_per_decl_24m_ratio': None,
           'same_day_split_per_decl_vs_norm_24m_diff': None,
           'new_importer_24m_score': None}
for col, n in TRACK_B.items():
    final['b_' + col] = credibility(tp[col], tp[n]) if n else tp[col].astype(float)

example = pd.DataFrame({'declarations': tp['decl_24m_count'],
                        'amended, raw': final['raw_amended_per_decl_3y_rate'],
                        'amended, after the small-numbers step': final['amended_per_decl_3y_rate']})
z.show(example.sort_values('declarations').head(10))
""")

py('7.4 Peer groups', r"""
SECTIONS = __SECTIONS__

def hs_section(chapter):
    # HS chapter (for example '61') -> its section (for example 'Textiles')
    try:
        c = int(float(chapter))
    except (TypeError, ValueError):
        return 'Unknown'
    return next((name for low, high, name in SECTIONS if low <= c <= high), 'Unknown')

def size_tier(log_value):
    # Small, medium, large: thirds by customs value within the section
    if len(log_value) < 3:
        return pd.Series('small', index=log_value.index)
    return pd.qcut(log_value.rank(method='first'), 3, labels=['small', 'medium', 'large']).astype(str)

# Main goods = the HS chapter with most of the taxpayer's customs value in the 24 months
chapter = F.substring('hsc_cd', 1, 2).alias('chapter')
by_chapter = hist_items.groupBy('taxpayer_tin', chapter).agg(F.sum('customs_value').alias('v'))
largest_first = Window.partitionBy('taxpayer_tin').orderBy(F.desc('v'))
main_chapter = (by_chapter.withColumn('rank', F.row_number().over(largest_first))
                          .where('rank = 1').select('taxpayer_tin', F.col('chapter').alias('dominant_hs_chapter')))
final = final.merge(main_chapter.toPandas(), on='taxpayer_tin', how='left')

section = final['dominant_hs_chapter'].map(hs_section).fillna('Unknown')
log_value = np.log1p(final['customs_value_24m_ugx'].clip(lower=0))
final['peer_group'] = section + ', ' + log_value.groupby(section).transform(size_tier)

def percentile_name(col):
    # the feature's name with its unit swapped for pct, for example b_amended_per_decl_24m_pct
    return 'b_' + col.rsplit('_', 1)[0] + '_pct'

for col in TRACK_B:
    final[percentile_name(col)] = final['b_' + col].groupby(final['peer_group']).rank(pct=True).fillna(0.5)

z.show(final['peer_group'].value_counts().rename_axis('peer group').reset_index(name='taxpayers'))
""")

# =========================================================================================
# 8. Final dataset
# =========================================================================================
md('8. Final dataset', r"""
## 8. The final dataset

One row per taxpayer. This is what the scorecard (Track A) and the model (Track B) read.

| Columns | What they are |
|---|---|
| `taxpayer_tin`, `taxpayer_nm`, `snapshot_date` | who, and the date of the profile |
| `decl_24m_count`, `customs_value_24m_ugx` | declarations and customs value (UGX) in the 24 months |
| `limited_history` | `Y` = fewer than 10 declarations: the score rests on little history |
| `no_top_up_history` | `Y` = no top-up in the 24 months: the group Track B is built for |
| 8 Track A columns (for example `topped_up_per_decl_3y_rate`) | the values the scorecard reads |
| the same starting `raw_` | before the small-numbers step (shown in the reasons) |
| 17 columns starting `b_` | the Track B features |
| the same ending `pct` (for example `b_amended_per_decl_24m_pct`) | the percentile within the peer group: what the model reads |
| `peer_group` | main goods (HS section) and size |
| `out_...` (past snapshots only) | what happened in the 6 months after: checks, checks that found a top-up, top-up amounts |
""")

py('8.1 Final dataset', r"""
final['limited_history'] = np.where(final['decl_24m_count'] < 10, 'Y', 'N')
final['no_top_up_history'] = np.where(final['top_up_24m_ugx'].fillna(0) <= 0, 'Y', 'N')

if WITH_OUTCOMES:
    after = decl.where(F.col('dt') > SNAP)
    checked = (F.col('red') == 1) | (F.col('yellow') == 1)
    outcomes = after.groupBy('taxpayer_tin').agg(
        F.count('*').alias('out_entries'),
        F.sum(F.when(checked, 1).otherwise(0)).alias('out_checked'),
        F.sum(F.when(checked & (F.col('topped_up') == 1), 1).otherwise(0)).alias('out_checked_hits'),
        F.sum('topped_up').alias('out_topped_up_entries'),
        F.sum('top_up').alias('out_top_up'),
        F.sum('orig_tax').alias('out_original_tax')).toPandas()
    final = final.merge(outcomes, on='taxpayer_tin', how='left')
    out_cols = [c for c in final if c.startswith('out_')]
    final[out_cols] = final[out_cols].fillna(0)

first = ['taxpayer_tin', 'taxpayer_nm', 'snapshot_date', 'decl_24m_count', 'customs_value_24m_ugx', 'limited_history',
         'no_top_up_history', 'peer_group']
track_a = list(TRACK_A) + ['raw_' + c for c in TRACK_A]
track_b = ['b_' + c for c in TRACK_B] + [percentile_name(c) for c in TRACK_B]
final_dataset = final[first + track_a + track_b + [c for c in final if c.startswith('out_')]]
save(final_dataset, 'ctrp_final_dataset')
print('{:,} taxpayers x {} columns, saved as ctrp_final_dataset'.format(*final_dataset.shape))
peek(final_dataset)
""")

py('8.2 Feature summary', r"""
# Each feature at a glance: how many taxpayers have it, its middle value and its top 5%
cols = list(TRACK_A) + ['b_' + c for c in TRACK_B]
z.show(pd.DataFrame({'feature': cols,
                     'taxpayers with a value': [int(final_dataset[c].notna().sum()) for c in cols],
                     'median': [final_dataset[c].median() for c in cols],
                     '95th percentile': [final_dataset[c].quantile(0.95) for c in cols]}))
""")

md('8.3 Check', r"""
### 8.3 Do these numbers match production?

Production builds the same columns with one query (`sql/live_<date>.sql`, or the "CTRP extracts" note). If that
extract is in this session (a table named like `live_2026_09_30` or `bt_2026_03_31`) or saved as a table
(`PRODUCTION_TABLE` in Settings), each column is compared, taxpayer by taxpayer. Every column should match,
because both use the same rules on the same data. Differences under 0.00001 count as a match: when Spark runs the
production query it rounds some rates to 5 decimal places. Larger differences can come from rows changed in the
view since the extract was pulled (a payment made, a top-up raised later).
""")

py('8.3 Check', r"""
name = PRODUCTION_TABLE or ('%s_%s' % ('bt' if WITH_OUTCOMES else 'live', SNAPSHOT.replace('-', '_')))
try:
    prod = spark.table(name)
except Exception:
    prod = None
    print('No production extract named %s in this session: check skipped.' % name)

if prod is not None:
    PRODUCTION_COLUMN = __PRODUCTION_COLUMN__
    COMPARE = [c for c in PRODUCTION_COLUMN if c in feature_inputs.columns and PRODUCTION_COLUMN[c] in prod.columns]
    mine = feature_inputs.select('taxpayer_tin', *[F.col(c).alias('a_' + c) for c in COMPARE])
    theirs = prod.select(F.col('taxpayer_tin').cast('string').alias('taxpayer_tin'),
                         *[F.col(PRODUCTION_COLUMN[c]).cast('double').alias('b_' + c) for c in COMPARE])
    both = mine.join(theirs, 'taxpayer_tin')
    def same(c):
        a, b = F.col('a_' + c), F.col('b_' + c)
        return (a.isNull() & b.isNull()) | (F.abs(a - b) <= 1e-5 + 1e-6 * F.abs(b))     # see the note above
    share_same = [F.avg(F.coalesce(same(c), F.lit(False)).cast('double')).alias(c) for c in COMPARE]
    result = both.select(F.count('*').alias('taxpayers in both'), *share_same).toPandas()
    print('Taxpayers here: {:,}, in production: {:,}, in both: {:,}'.format(
        feature_inputs.count(), prod.count(), int(result['taxpayers in both'][0])))
    by_column = result.drop(columns='taxpayers in both').T.reset_index()
    z.show(by_column.rename(columns={'index': 'column', 0: 'share matching'}))
""")

md('8.4 Getting the outputs', r"""
### 8.4 Getting the outputs into Excel

Every result is a table in this session:

| Table | What |
|---|---|
| `ctrp_eda_summary` | the data problems found, with counts |
| `ctrp_eda_e01`, `ctrp_eda_e02`, ... | the rows behind each data problem, one table per problem |
| `ctrp_cleaning_log` | rows removed by each cleaning rule |
| `ctrp_feature_inputs` | every feature before the steps of Part 7 |
| `ctrp_final_dataset` | the final dataset |

To get them out:
* **Small tables:** the download button above any `z.show` result.
* **With a folder you can write to:** set `SAVE_TO_FOLDER = True` and `OUT_DIR` in Settings and run again. Each table
  becomes a folder holding one CSV file.
* **With a Hive schema you can write to:** set `SAVE_TO_SCHEMA`. Each table can then be downloaded from Hue (as
  Excel), or read from VS Code.

Then put the CSV files in one folder of the project, each named after its table (for example
`data/zeppelin_eda/ctrp_final_dataset.csv`), and run `python main.py eda-excel data/zeppelin_eda`. It makes one
workbook per data problem (for the Risk Officers to give their verdict) and one workbook with the final dataset and
a list of the 22 features.
""")


# =========================================================================================
# Building the note
# =========================================================================================
# name in the notes -> production column, for the check against a production extract (one entry per name)
PRODUCTION_COLUMN = {new: old for old, new in FEATURE_NAMES.items() if old != 'station_spread'}


def _wrapped_list(items, indent):
    """A list written over several lines of about 110 characters, for the note's code."""
    lines, line = [], ''
    for piece in (repr(x) + ', ' for x in items):
        if line and len(indent) + len(line) + len(piece) > 110:
            lines.append(line.rstrip())
            line = ''
        line += piece
    lines.append(line.rstrip().rstrip(','))
    return '[' + ('\n' + ' ' * len(indent)).join(lines) + ']'


def _wrapped_dict(d, indent):
    """A dict written one key per line, for the note's code."""
    pad = ' ' * len(indent)
    return '{' + (',\n' + pad).join(f'{k!r}: {v!r}' for k, v in d.items()) + '}'


def _fill(text):
    """Put the project's own settings into the paragraphs, so the note always matches production."""
    issues_list = ('[\n' + ',\n'.join(f"    ('{c}', {t!r}, e{c[1:]}, {k})"
                                       for c, t, _, _, _, _, _, k in I.ISSUES if c in REVIEW_ISSUES) + ',\n]')
    values = {'__LIVE__': E.LIVE_SNAPSHOT, '__APC483__': str(E.EXCLUDE_APC_483),
              '__R14__': str(E.LATEST_DECLARATION_PER_ENTRY), '__R15__': str(E.EXCLUDE_MOTOR_VEHICLES),
              '__MV__': repr(E.MOTOR_VEHICLE_HEADINGS), '__DETAIL__': _wrapped_list(I.DETAIL, 'DETAIL = ['),
              '__ISSUES_LIST__': issues_list, '__WATCHLIST__': repr(WATCHLIST_APCS), '__BLANK_MEANS__': _wrapped_dict(BLANK_MEANS, 'BLANK_MEANS = {'),
              '__SECTIONS__': _wrapped_list(M.HS_SECTIONS, 'SECTIONS = ['),
              '__PRODUCTION_COLUMN__': _wrapped_dict(PRODUCTION_COLUMN, '    PRODUCTION_COLUMN = {')}
    for key, value in values.items():
        text = text.replace(key, value)
    left = re.findall(r'__[A-Z0-9_]+__', text)
    assert not left, f'placeholders not filled: {left}'
    return text


def paragraphs():
    """[(title, text)] with the settings filled in."""
    return [(title, _fill(text)) for title, text in PARAGRAPHS]


def _paragraph(title, text, i):
    pid = f'paragraph_ctrp_eda_{i:03d}'
    lang = 'markdown' if text.startswith('%md') else 'python'
    return {'title': title, 'text': text, 'user': 'anonymous', 'dateUpdated': '2026-10-20 00:00:00.000',
            'progress': 0, 'config': {'editorSetting': {'language': lang, 'editOnDblClick': lang == 'markdown',
                                                        'completionSupport': lang != 'markdown'},
                                      'editorMode': f'ace/mode/{lang}', 'colWidth': 12.0, 'fontSize': 9.0,
                                      'title': lang != 'markdown', 'editorHide': lang == 'markdown',
                                      'results': {}, 'enabled': True},
            'settings': {'params': {}, 'forms': {}}, 'apps': [], 'runtimeInfos': {},
            'progressUpdateIntervalMs': 500, 'jobName': pid, 'id': pid,
            'dateCreated': '2026-10-20 00:00:00.000', 'status': 'READY'}


def write_note(path=OUT_NOTE):
    note = {'paragraphs': [_paragraph(t, x, i) for i, (t, x) in enumerate(paragraphs())],
            'name': 'CTRP EDA and features', 'id': 'CTRPEDAFEAT01', 'defaultInterpreterGroup': 'spark',
            'version': '0.10.1', 'noteParams': {}, 'noteForms': {}, 'angularObjects': {},
            'config': {'isZeppelinNotebookCronEnable': False}, 'info': {}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(note, indent=2))
    print(f'written {path.relative_to(PROJECT_ROOT)} ({len(note["paragraphs"])} paragraphs)')
    return path


def write_paste_files(path=PASTE_DIR):
    """The code paragraphs as numbered text files, for pasting one at a time if import is not allowed."""
    path.mkdir(parents=True, exist_ok=True)
    for f in path.glob('*.txt'):
        f.unlink()
    code = [(t, x) for t, x in paragraphs() if x.startswith('%pyspark')]
    for i, (title, text) in enumerate(code, start=1):
        slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
        (path / f'{i:02d}_{slug}.txt').write_text(text + '\n')
    print(f'written {len(code)} paragraph files in {path.relative_to(PROJECT_ROOT)}')


def script():
    """All code paragraphs as one Python script (used by the tests to run the note locally)."""
    return '\n\n'.join(x.split('\n', 1)[1] for _, x in paragraphs() if x.startswith('%pyspark'))


# =========================================================================================
# The outputs as Excel workbooks
# =========================================================================================
# The 22 features: (name, track, parameter, what it measures, inputs, why)
FEATURE_LIST = [
    ('top_up_entry_rate', 'A', 'PAR_045T', 'Declarations topped up ÷ declarations', 'top_up_flg, original_tax_amt, final_amt',
     'A taxpayer often found under-declaring is likely to be found again'),
    ('par077_severe_top_up_rate', 'A', 'PAR_077', 'Top-ups of 30% or more of the final tax ÷ declarations',
     'top_up_flg, original_tax_amt, final_amt', 'A large correction says more about intent than a small one'),
    ('par045_amended_entry_rate', 'A and B', 'PAR_045', 'Declarations amended ÷ declarations', 'amendment_flg',
     'Declarations that are often wrong the first time'),
    ('par048_top_up_share_final', 'A', 'PAR_048', 'Top-ups ÷ final tax (original tax + top-ups)', 'original_tax_amt, final_amt, top_up_flg',
     'How much of what the taxpayer finally paid had to be found by customs'),
    ('par076_shortfall_share', 'A and B', 'PAR_076', 'Value missing on items priced under half the median price of other importers ÷ value',
     'customs_value, net_weight, supplementary_qnty, hsc_cd, gds_org_cty', 'Undervaluation is the main revenue risk at import'),
    ('par066_negative_top_up_rate', 'A', 'PAR_066', 'Declarations whose tax was reduced after assessment ÷ declarations',
     'original_tax_amt, final_amt', 'Frequent reductions can point to errors or to pressure on assessments'),
    ('par105_top_up_180d', 'A', 'PAR_105', '1 if the last top-up was within 180 days of the snapshot, else 0',
     'assessment_dt_wid, top_up_flg', 'Recent non-compliance matters more than old'),
    ('par023_station_spread', 'A and B (station_spread)', 'PAR_023', '1 − share of declarations at the main station',
     'clearance_station_cd', 'Moving between stations can be a search for easier checks'),
    ('ctx_unpaid_rate', 'B', 'PAR_072 (stand-in)', 'Declarations with tax due and status NOT_PAID ÷ declarations',
     'pay_status, final_amt', 'Unpaid tax is non-compliance in itself'),
    ('ctx_implausible_price_rate', 'B', '', 'Items priced under 1% of the median price ÷ items', 'customs_value, net_weight, hsc_cd',
     'Repeated "keying errors" can hide value'),
    ('par076_low_price_item_rate', 'B', 'PAR_076', 'Items priced under half the median price ÷ items',
     'customs_value, net_weight, supplementary_qnty, hsc_cd', 'How often prices are low'),
    ('price_deviation_median', 'B', 'PAR_090 (stand-in)', 'Median distance of the price from the median price, either way, log scale',
     'customs_value, net_weight, hsc_cd', 'Prices far from other importers, up or down'),
    ('own_price_drop_share', 'B', 'PAR_067 (stand-in)', 'Share of recent value on goods now declared under 70% of the taxpayer\'s own earlier price',
     'customs_value, net_weight, supplementary_qnty, hsc_cd, assessment_dt_wid', 'A sudden drop in declared price may be the start of undervaluation'),
    ('low_duty_value_share', 'B', 'PAR_096 (stand-in)', 'Value taxed at under half the median duty rate (no exemption claimed) ÷ value',
     'tax_assessed, customs_value, hsc_cd, cpc_cd', 'Paying much less than others for the same goods points to a wrong code or rate'),
    ('duty_gap_share', 'B', 'PAR_016 (stand-in)', 'Tax missing against the median duty rate ÷ value',
     'tax_assessed, customs_value, hsc_cd, cpc_cd', 'The same, measured in money'),
    ('exemption_apc_value_share', 'B', 'PAR_052', 'Value under an exemption APC (not 000) ÷ value', 'cpc_cd, customs_value',
     'Exemptions are a known route for revenue loss'),
    ('watchlist_apc_value_share', 'B', 'PAR_053', 'Value under the 11 APCs marked "look out for possible abuse" ÷ value',
     'cpc_cd, customs_value', 'The memo names these APCs as abused'),
    ('ctx_preferential_use_rate', 'B', 'PAR_050', 'Items claiming preferential treatment ÷ items', 'preferential_treatment_flag',
     'A false origin claim avoids duty'),
    ('surge', 'B', '', 'log((declarations in the last 90 days + 1) ÷ (average quarter + 1))', 'assessment_dt_wid',
     'A sharp jump can mean a borrowed TIN or a burst before disappearing'),
    ('goods_spread', 'B', '', 'Different 4-digit HS headings ÷ declarations', 'hsc_cd',
     'Mixing many goods makes checks harder and can hide misdescribed items'),
    ('same_day_split_excess', 'B', 'raised by the officers', 'Share of declarations in same-day repeats of one HS code, minus the norm for those goods',
     'hsc_cd, assessment_dt_wid, instance_id, extended_proc_cd', 'Splitting a consignment can keep each declaration under a threshold'),
    ('newness', 'B', 'PAR_019, PAR_101', '−log(1 + days since the first declaration in 24 months), plus 1 for a new trader',
     'assessment_dt_wid, taxpayer_tin (and the 3 years before)', 'New traders have no track record, and new TINs are used for one-off fraud'),
]
OUTPUT_TABLES = ['ctrp_eda_summary', 'ctrp_cleaning_log', 'ctrp_final_dataset'] + \
                ['ctrp_eda_' + code.lower() for code in REVIEW_ISSUES]


def final_dataset_from_extract(extract_file, folder='data/zeppelin_eda'):
    """What: the final dataset built from a production extract (a Hue download, for example
          data/live_2026-09-30.csv) instead of from the Zeppelin note: same columns, same names, same numbers.
    Why:  Zeppelin results cannot be saved until there is a folder or schema to write to. The production extract
          plus the production Python (core.derive for Track A, discovery for Track B) gives the same values as the
          note (checked in tests/test_eda_note.py). Taxpayer names are not in the extract, so that column is blank.
    Writes <folder>/ctrp_final_dataset.csv, which build_excel() then turns into the workbook."""
    import numpy as np
    from ctrp import discovery as B
    from ctrp.utils import load_extract

    raw = load_extract(PROJECT_ROOT / extract_file).reset_index(drop=True)
    track_a = M.derive(raw.copy())                          # recency, then the small-numbers step
    track_b = B.build_features(raw)                         # the 17 behaviour features
    groups = B.section_size_groups(raw)                     # 'Textiles | 2'
    percentiles = B.peer_percentiles(track_b, groups)

    size = {'0': 'small', '1': 'medium', '2': 'large'}
    section, tier = groups.str.split(' | ', regex=False).str[0], groups.str.split(' | ', regex=False).str[1]
    peer_group = section + ', ' + tier.str.split('.').str[0].map(size).fillna(tier)

    out = pd.DataFrame({
        'taxpayer_tin': raw['taxpayer_tin'],
        'taxpayer_nm': '',
        'snapshot_date': raw['snapshot_date'].astype(str).str[:10],
        'decl_24m_count': raw['entries_24m'],
        'customs_value_24m_ugx': raw['total_customs_value'],
        'limited_history': np.where(raw['entries_24m'] < 10, 'Y', 'N'),
        'no_top_up_history': np.where(raw['total_top_up'].fillna(0) <= 0, 'Y', 'N'),
        'peer_group': peer_group,
    })
    for col, name in TRACK_A_NAMES.items():
        out[name] = track_a[col]
    for col, name in TRACK_A_NAMES.items():
        out['raw_' + name] = track_a[col + '_raw']
    for col, name in TRACK_B_NAMES.items():
        out['b_' + name] = track_b[col]
    for col, name in TRACK_B_NAMES.items():
        out['b_' + name.rsplit('_', 1)[0] + '_pct'] = percentiles[col]
    if not Path(extract_file).name.startswith('live_'):     # a live extract has no outcomes yet
        for col in [c for c in raw if c.startswith('out_')]:
            out[col] = raw[col]

    path = PROJECT_ROOT / folder / 'ctrp_final_dataset.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    print(f'written {path.relative_to(PROJECT_ROOT)} ({len(out):,} taxpayers x {out.shape[1]} columns)')
    return path


def _find(folder, name):
    """A downloaded table: <folder>/<name>.csv, or the CSV inside the folder Spark wrote (<folder>/<name>/part-*.csv)."""
    folder = Path(folder)
    for p in [folder / f'{name}.csv', *sorted((folder / name).glob('part-*.csv'))]:
        if p.exists():
            return p
    return None


def feature_sheet():
    """The 22 features: their names in the notes (Track A and Track B), the production column, and what they are."""
    rows = []
    for production, track, parameter, what, inputs, why in FEATURE_LIST:
        names = []
        if production in TRACK_A_NAMES:
            names.append(TRACK_A_NAMES[production] + ' (Track A)')
        b_column = 'station_spread' if production == 'par023_station_spread' else production
        if b_column in TRACK_B_NAMES:
            names.append('b_' + TRACK_B_NAMES[b_column] + ' (Track B)')
        rows.append(['; '.join(names), production, parameter, what, inputs, why])
    return pd.DataFrame(rows, columns=['Name in the notes', 'Production column', 'Parameter', 'What it measures',
                                       'Columns of the view used', 'Why'])


def build_excel(folder, out_dir=None):
    """What: the note's results as Excel: one workbook per data problem (for the officers' verdict) and one
    workbook with the final dataset, the feature list, the cleaning log and the data problems found.
    Why:  Excel is how the results are reviewed and signed off."""
    out_dir = Path(out_dir or RESULTS_DIR)
    found = {n: _find(folder, n) for n in OUTPUT_TABLES}
    missing = [n for n, p in found.items() if p is None]
    if missing:
        print('not found in', folder, ':', ', '.join(missing))

    # 1. one workbook per data problem, in the same format as the Hue issue workbooks
    I.ISSUE_DATA.mkdir(parents=True, exist_ok=True)
    for code in REVIEW_ISSUES:
        p = found['ctrp_eda_' + code.lower()]
        if p is not None:
            shutil.copyfile(p, I.ISSUE_DATA / f'{code}.csv')
    written = I.build(out_dir / 'eda_issues', codes=REVIEW_ISSUES)

    # 2. the final dataset workbook
    if found['ctrp_final_dataset'] is None:
        return written
    final = pd.read_csv(found['ctrp_final_dataset'], dtype={'taxpayer_tin': str})
    snap = str(final['snapshot_date'].iloc[0])[:10] if len(final) else 'unknown'
    track_a = list(TRACK_A_NAMES.values())
    first = ['taxpayer_tin', 'taxpayer_nm', 'snapshot_date', 'decl_24m_count', 'customs_value_24m_ugx',
             'limited_history', 'no_top_up_history', 'peer_group']
    sheets = {
        'Read me': pd.DataFrame([
            ['What', f'The CTRP final dataset at {snap}: one row per taxpayer, built step by step '
                     'in the EDA notebook (Part 6) from the Hue extract of the view '
                     'dm_modeled_ura_datascience.vw_cstm_AEO_model, with the same numbers as the production code.'],
            ['Track A', 'The 8 values the compliance history scorecard reads (after recency and the small-numbers step). '
                        'Columns starting raw_ are before the small-numbers step.'],
            ['Track B', 'The 17 behaviour features (columns starting b_), and their percentile within the peer group '
                        '(ending pct): what the Risky Behaviour Flag model reads.'],
            ['Names', 'Each name says what is measured, per what, over which window, and ends with the unit. '
                      'The sheet "Names" explains every short form.'],
            ['Taxpayers', f'{len(final):,}'],
            ['Note', 'Contains TINs and names: internal use only. Prepared by Data Science (ITID).'],
        ]),
        'Features (22)': feature_sheet(),
        'Names': pd.DataFrame(ABBREVIATIONS, columns=['Short form', 'Meaning']),
        'Track A': final[first + [c for c in final if c in track_a or c.startswith('raw_')]],
        'Track B': final[first + [c for c in final if c.startswith('b_')]],
    }
    if any(c.startswith('out_') for c in final):
        sheets['Outcomes'] = final[['taxpayer_tin'] + [c for c in final if c.startswith('out_')]]
    for name, sheet in [('ctrp_cleaning_log', 'Cleaning log'), ('ctrp_eda_summary', 'Data problems')]:
        if found[name] is not None:
            sheets[sheet] = pd.read_csv(found[name])
    path = out_dir / f'CTRP_final_dataset_{snap}.xlsx'
    _write_book(path, sheets)
    print(f'written {path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path} '
          f'({len(final):,} taxpayers)')
    return written + [path]


def _write_book(path, sheets):
    from openpyxl.styles import Alignment, Font, PatternFill
    head = PatternFill('solid', start_color='102A83')
    with pd.ExcelWriter(path, engine='openpyxl') as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False, header=name != 'Read me')
            ws = w.book[name]
            if name == 'Read me':
                ws.column_dimensions['A'].width, ws.column_dimensions['B'].width = 14, 120
                for r in ws.iter_rows():
                    r[0].font = Font(bold=True)
                    r[1].alignment = Alignment(wrap_text=True, vertical='top')
                continue
            for c in ws[1]:
                c.font, c.fill = Font(bold=True, color='FFFFFF'), head
                c.alignment = Alignment(wrap_text=True, vertical='center')
            for col in ws.columns:
                h = str(col[0].value or '')
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60 if name in ('Features (22)', 'Names') else 30)
                fmt = '#,##0' if h.endswith(('_ugx', '_count')) or h.startswith('out_') else '0.000'
                if h in df and df[h].dtype.kind == 'f':
                    for c in col[1:]:
                        c.number_format = fmt
            if name in ('Features (22)', 'Names'):
                for r in ws.iter_rows(min_row=2):
                    for c in r:
                        c.alignment = Alignment(wrap_text=True, vertical='top')
            ws.freeze_panes = 'B2'
            ws.auto_filter.ref = ws.dimensions
