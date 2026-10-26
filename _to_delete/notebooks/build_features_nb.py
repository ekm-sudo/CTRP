"""
Build the notebook CTRP_features_in_python.ipynb: EDA and feature engineering in Python, from raw rows.

What: one notebook, code shown, in the usual order of a data science project:
        load the raw declaration rows -> look at them (EDA) -> clean them -> declarations -> every
        Track A and Track B feature, one cell each -> the final feature table -> a check against the
        production extract.
      Every feature is computed with pandas from the raw columns, so nothing is hidden in a Hue query.
Why:  in production the same logic runs as one Hue (Spark SQL) query, because the full view is millions of
      rows. That is hard to follow for a reader used to notebooks. This notebook does the same steps in
      Python on a 5% random sample of taxpayers, and the last part shows that it gives the same numbers.

Data (plain SELECTs, no feature logic in them; sql/python_features/):
    raw_items_1.sql ... raw_items_6.sql   -> data/python_features/raw_items_1.csv ... raw_items_6.csv
    prior_tins.sql                        -> data/python_features/prior_tins.csv

    python notebooks/build_features_nb.py         (writes notebooks/CTRP_features_in_python.ipynb)
"""
from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []


def md(s):
    C.append(nbf.v4.new_markdown_cell(s.strip()))


def code(s):
    C.append(nbf.v4.new_code_cell(s.strip()))


# =================================================================================== title
md(r"""
# CTRP: exploring the data and building the features in Python

**Customs Taxpayer Risk Profiling Model.** Data Science Section, ITID.

This notebook starts from the raw rows of the customs view and builds every feature the model uses, step by
step, in Python (pandas). Each step shows the code, the logic in plain words, and the first 10 rows of the
result.

| Part | What happens |
|---|---|
| 1 | Load the raw rows |
| 2 | Explore them (EDA) |
| 3 | Clean them |
| 4 | From item rows to declarations |
| 5 | Track A features (the compliance history scorecard) |
| 6 | Track B features (trading behaviour) |
| 7 | Steps after the features: recency, small numbers, peer groups |
| 8 | The final feature table, and a check against production |

**About the data.** The view holds millions of rows, too many to load on a laptop. This notebook uses every
row for a **5% random sample of taxpayers** over the 3 years before the snapshot. In production the same
steps run as one query on the full view (Spark SQL in Hue), because only the cluster can hold all the rows.
The logic is the same; Part 8 checks that the numbers agree.

**One difference to keep in mind.** Some features compare a taxpayer with **other importers** of the same
goods (price and duty benchmarks, the same-day norm). Here "other importers" means the other taxpayers in
the sample, while production uses every importer. Those features will be close to production but not equal.
All other features should match exactly.
""")

# =================================================================================== setup
md(r"""
## 0. Setup

The settings below are the only things to change: the snapshot date (the day the risk profile is made) and
where the data files are.
""")

code(r"""
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

pd.set_option('display.max_columns', 40)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', lambda v: f'{v:,.4f}')

# ---- settings ------------------------------------------------------------------------------------
SNAPSHOT = pd.Timestamp('2026-09-30')          # the date the risk profile is made
ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
DATA = Path(os.environ.get('CTRP_PY_DATA', ROOT / 'data' / 'python_features'))
EXCLUDE_APC_483 = True                         # APC 483: destroyed or abandoned goods, dummy entries
LATEST_DECLARATION_PER_ENTRY = True            # one declaration per entry (entry no. + station + year)
EXCLUDE_MOTOR_VEHICLES = True                  # motor vehicles have their own model
MOTOR_VEHICLE_HEADINGS = ['8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711']   # chapter 87 vehicles: tractors, buses, cars, goods and special vehicles, chassis, bodies, parts, motorcycles

# ---- the windows, all counted back from the snapshot ----------------------------------------------
HIST_START = SNAPSHOT - pd.offsets.MonthEnd(24)     # features use the 24 months before the snapshot
HIST3_START = SNAPSHOT - pd.offsets.MonthEnd(36)    # recency weighting uses 3 years
ymd = lambda d: d.strftime('%Y%m%d')                # dates in the view are text like '20260930'

print('Snapshot:          ', SNAPSHOT.date())
print('Features (24 months):', HIST_START.date(), 'to', SNAPSHOT.date())
print('Recency (36 months): ', HIST3_START.date(), 'to', SNAPSHOT.date())
print('Data folder:       ', DATA)
""")

# =================================================================================== 1 load
md(r"""
## 1. Load the raw rows

Each row of the view is **one item on one declaration** (a declaration with 5 kinds of goods has 5 rows).
The files were downloaded from Hue with a plain `SELECT` of the columns below, for the sampled taxpayers
(`sql/python_features/raw_items_*.sql`). No calculation was done in the query.

Everything is read as text first, then each column is given its proper type, so nothing is changed silently
(for example a TIN or a tariff code losing its leading zeros).
""")

code(r"""
files = sorted(DATA.glob('raw_items_*.csv'))
assert files, f'No raw_items_*.csv files in {DATA}. Run the queries in sql/python_features/ first.'
parts = []
for f in files:
    part = pd.read_csv(f, dtype=str)
    # Hue stops a download at 100,000 rows: a file with exactly that many rows is cut off
    assert len(part) % 100_000 != 0, f'{f.name} has exactly {len(part):,} rows: the download was cut off'
    parts.append(part)
raw = pd.concat(parts, ignore_index=True)
raw.columns = [c.split('.')[-1].lower() for c in raw.columns]     # Hue may add a 'v.' prefix

print(f'{len(files)} files, {len(raw):,} item rows, {raw["taxpayer_tin"].nunique():,} taxpayers')
raw.head(10)
""")

md(r"""
### 1.1 Give each column its type

| Type | Columns |
|---|---|
| Text (codes and IDs) | `instance_id` (declaration), `taxpayer_tin`, `hsc_cd` (tariff code), `gds_org_cty` (origin), `cpc_cd` (APC), `extended_proc_cd` (EPC), `regime_cd`, `decl_status`, `clearance_station_cd`, `pay_status` |
| Yes / no flags (`Y` or `N`) | `top_up_flg`, `amendment_flg`, `preferential_treatment_flag` |
| Lane flags (1 = selected) | `is_red_flg`, `is_yellow_flg` |
| Numbers (UGX, kg, units) | `customs_value`, `net_weight`, `supplementary_qnty`, `tax_assessed`, `original_tax_amt`, `final_amt` |
| Date | `assessment_dt_wid` (text `yyyymmdd`), turned into a real date `adate` |
""")

code(r"""
NUMBERS = ['customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt', 'final_amt']
for c in NUMBERS:
    raw[c] = pd.to_numeric(raw[c], errors='coerce')
raw['key_itm_nbr'] = pd.to_numeric(raw['key_itm_nbr'], errors='coerce')

def lane_flag(s):
    # the lane flags may arrive as 1/0 or true/false: 1 means the lane was given
    return s.astype(str).str.strip().str.lower().isin(['1', '1.0', 'true', 'y']).astype(int)

raw['is_red_flg'] = lane_flag(raw['is_red_flg'])
raw['is_yellow_flg'] = lane_flag(raw['is_yellow_flg'])
raw['adate'] = pd.to_datetime(raw['assessment_dt_wid'], format='%Y%m%d', errors='coerce')

overview = pd.DataFrame({
    'type': raw.dtypes.astype(str),
    'example': [raw[c].dropna().iloc[0] if raw[c].notna().any() else None for c in raw.columns],
    'missing %': (raw.isna().mean() * 100).round(1),
    'distinct values': raw.nunique(),
})
overview
""")

# =================================================================================== 2 EDA
md(r"""
## 2. Explore the raw rows (EDA)

Before building anything, look at what the data holds: repeated rows, statuses, regimes, values, goods,
origins, lanes and top-ups. Each finding below leads to a cleaning rule in Part 3 or a choice in Part 5 and 6.
""")

code(r"""
# 2.1 Repeated rows: the same item (declaration + item number) appearing more than once
dup = raw.duplicated(['instance_id', 'key_itm_nbr'], keep='first')
print(f'Item rows that repeat an earlier row: {dup.sum():,} of {len(raw):,} ({dup.mean():.1%})')
# are the copies identical? (if yes, keeping one copy loses nothing)
cols = [c for c in raw.columns if c not in ('adate',)]
same = raw[raw.duplicated(['instance_id', 'key_itm_nbr'], keep=False)].groupby(['instance_id', 'key_itm_nbr'])[cols].nunique().max(axis=1)
print(f'Repeated items whose copies are identical: {(same <= 1).mean():.1%}' if len(same) else 'No repeated items')
""")

code(r"""
# 2.2 Statuses, regimes, TINs and APC 483
print('Declaration status (items):'); display(raw['decl_status'].value_counts(dropna=False).head(10).to_frame('items'))
print('Regime (items):'); display(raw['regime_cd'].value_counts(dropna=False).to_frame('items'))
bad_tin = ~raw['taxpayer_tin'].str.fullmatch(r'\d{10}', na=False)
print(f'Items with a TIN that is not 10 digits: {bad_tin.sum():,}')
print(f"Items under APC 483 (destroyed or abandoned goods, dummy entries): {(raw['cpc_cd'] == '483').sum():,}")

# 2.2b The entry key: entry number + station + year (for example C12345UGKLA2026)
raw['entry_key'] = (raw['entry_num'] + raw['clearance_station_cd'] + raw['dec_ref_yer']).fillna(raw['instance_id'])
ids_per_entry = raw.groupby('entry_key')['instance_id'].nunique()
print(f"Entries: {len(ids_per_entry):,};  entries under more than one declaration ID: {(ids_per_entry > 1).sum():,}")
print('The full list, with every row, is in the EDA issue workbook for the Risk Officers (issue E01).')
raw[raw['entry_key'].isin(ids_per_entry[ids_per_entry > 1].index)].sort_values('entry_key')[
    ['entry_key', 'instance_id', 'key_itm_nbr', 'assessment_dt_wid', 'taxpayer_tin', 'hsc_cd', 'customs_value', 'final_amt']].head(10)
""")

code(r"""
# 2.3 Values: customs value per item is very skewed, so it is shown on a log scale
v = raw['customs_value']
print(v.describe(percentiles=[.25, .5, .75, .95, .99]).to_frame('customs value, UGX'))
fig, ax = plt.subplots(1, 2, figsize=(12, 3.5))
ax[0].hist(np.log10(v[v > 0]), bins=60, color='#1F4FD8'); ax[0].set_title('Customs value per item (log10 UGX)')
w = raw['net_weight']
ax[1].hist(np.log10(w[w > 0]), bins=60, color='#B88A00'); ax[1].set_title('Net weight per item (log10 kg)')
plt.tight_layout(); plt.show()
print(f'Items with value 0 or missing: {(v.fillna(0) <= 0).mean():.1%};  weight 0 or missing: {(w.fillna(0) <= 0).mean():.1%};  '
      f'units given: {(raw["supplementary_qnty"].fillna(0) > 0).mean():.1%}')
""")

code(r"""
# 2.4 What is imported, from where, and under which APC (share of customs value)
val = raw['customs_value'].fillna(0)
by = lambda key: (val.groupby(key).sum() / val.sum()).sort_values(ascending=False).head(10)
fig, ax = plt.subplots(1, 3, figsize=(15, 3.8))
by(raw['hsc_cd'].str[:2]).plot.barh(ax=ax[0], color='#1F4FD8', title='Top HS chapters (share of value)')
by(raw['gds_org_cty']).plot.barh(ax=ax[1], color='#1F4FD8', title='Top origins (share of value)')
by(raw['cpc_cd']).plot.barh(ax=ax[2], color='#1F4FD8', title='Top APCs (share of value; 000 = no exemption)')
for a in ax: a.invert_yaxis()
plt.tight_layout(); plt.show()
""")

code(r"""
# 2.5 Lanes and top-ups, per declaration (one row per declaration for this count)
d0 = raw.drop_duplicates('instance_id')
print(f"Declarations: {len(d0):,}")
print(f"Red lane: {d0['is_red_flg'].mean():.1%}   Yellow lane: {d0['is_yellow_flg'].mean():.1%}")
print(f"Top-up flag Y: {(d0['top_up_flg'] == 'Y').mean():.1%}")
print(f"Original tax missing: {d0['original_tax_amt'].isna().mean():.1%}  (missing means unchanged: filled with the final tax in Part 4)")
""")

md(r"""
**What the EDA tells us**

* Items repeat (the view joins several tables), so each item must be kept **once** before anything is counted.
* Cancelled declarations, invalid TINs and APC 483 (destroyed or abandoned goods, dummy entries) are not trade
  and must go.
* Values and weights span many orders of magnitude: comparisons must be **ratios** (price per kg against other
  importers), not raw amounts.
* Tax amounts sit on every item row of a declaration, so taxes must be taken **once per declaration**.
* Original tax is often blank when nothing changed, so blank means "same as the final tax".
""")

# =================================================================================== 3 clean
md(r"""
## 3. Clean the rows

Each rule keeps only the rows that pass it. The table at the end shows how many rows each rule removed.
""")

code(r"""
log = []
def keep(df, mask, rule):
    mask = mask.fillna(False)
    log.append({'rule': rule, 'rows before': len(df), 'rows removed': int((~mask).sum())})
    return df[mask]

items = raw.copy()
items = keep(items, items['taxpayer_tin'].str.fullmatch(r'\d{10}', na=False), 'R1 TIN must be 10 digits')
items = keep(items, items['decl_status'].notna() & (items['decl_status'] != 'Cancelled'), 'R3 drop cancelled declarations')
items = keep(items, items['regime_cd'].isin(['IM4', 'IM7']), 'R4 imports only: IM4 (home use) and IM7 (bond)')
if EXCLUDE_APC_483:
    items = keep(items, items['cpc_cd'].fillna('') != '483', 'R13 drop APC 483')
in_window = (items['assessment_dt_wid'] > ymd(HIST3_START)) & (items['assessment_dt_wid'] <= ymd(SNAPSHOT))
items = keep(items, in_window, 'Window: the 3 years before the snapshot')
# R14: one declaration per entry. If an entry has several declaration IDs, keep the latest (highest) one.
if LATEST_DECLARATION_PER_ENTRY:
    order_id = items['instance_id'].str.zfill(20)
    items = keep(items, order_id == order_id.groupby(items['entry_key']).transform('max'), 'R14 latest declaration ID per entry')
# R15: drop every declaration with a motor vehicle item (tax and top-ups are per declaration, so the whole
# declaration goes, not only the vehicle item)
if EXCLUDE_MOTOR_VEHICLES:
    has_vehicle = items['hsc_cd'].str[:4].isin(MOTOR_VEHICLE_HEADINGS).groupby(items['instance_id']).transform('max')
    items = keep(items, ~has_vehicle, 'R15 drop motor vehicle declarations (separate model)')
# R5: keep each item once (the copies are identical, so the earliest is kept)
before = len(items)
items = items.sort_values('assessment_dt_wid', kind='stable').drop_duplicates(['instance_id', 'key_itm_nbr'])
log.append({'rule': 'R5 keep each item once', 'rows before': before, 'rows removed': before - len(items)})

display(pd.DataFrame(log))
print(f'Clean item rows: {len(items):,}   declarations: {items["instance_id"].nunique():,}   taxpayers: {items["taxpayer_tin"].nunique():,}')
""")

# =================================================================================== 4 declarations
md(r"""
## 4. From item rows to declarations

Many features count **declarations** (for example "share of declarations amended"). Tax, top-up, lane and
status are the same on every item of a declaration, so the items are grouped into one row per declaration:

* **Value** = the sum of the items' customs values; **items** = how many items.
* **Original tax**: blank means unchanged, so it is filled with the final tax.
* **Topped up** = the top-up flag is `Y` **and** the final tax is above the original tax (the flag alone is
  not enough: it is also set when tax did not rise). **Top-up amount** = final tax minus original tax.
* **Tax reduced** (negative top-up) = the final tax is below the original tax.
* **Severe top-up** = a top-up of 30% or more of the final tax.
""")

code(r"""
decl = (items.groupby('instance_id')
        .agg(tin=('taxpayer_tin', 'max'), adate=('adate', 'max'), dt=('assessment_dt_wid', 'max'),
             regime=('regime_cd', 'max'), original_tax_raw=('original_tax_amt', 'max'), final_tax=('final_amt', 'max'),
             top_up_flg=('top_up_flg', 'max'), amended=('amendment_flg', 'max'), station=('clearance_station_cd', 'max'),
             red=('is_red_flg', 'max'), yellow=('is_yellow_flg', 'max'), pay_status=('pay_status', 'max'),
             value=('customs_value', 'sum'), n_items=('key_itm_nbr', 'size'))
        .reset_index())
decl['orig_tax'] = decl['original_tax_raw'].fillna(decl['final_tax'])                      # blank = unchanged
decl['topped_up'] = ((decl['top_up_flg'] == 'Y') & (decl['final_tax'] > decl['orig_tax'])).astype(int)
decl['top_up'] = np.where(decl['topped_up'] == 1, decl['final_tax'] - decl['orig_tax'], 0.0)
decl['negative_top_up'] = (decl['final_tax'] < decl['orig_tax']).astype(int)
decl['severe'] = ((decl['topped_up'] == 1) & (decl['top_up'] >= 0.30 * decl['final_tax'])).astype(int)

# the 24-month history window used by the features
hist = decl[(decl['dt'] > ymd(HIST_START)) & (decl['dt'] <= ymd(SNAPSHOT))].copy()
hist_items = items[(items['assessment_dt_wid'] > ymd(HIST_START)) & (items['assessment_dt_wid'] <= ymd(SNAPSHOT))].copy()
print(f'Declarations in 3 years: {len(decl):,};  in the 24-month window: {len(hist):,};  items in the window: {len(hist_items):,}')
hist[['instance_id', 'tin', 'dt', 'regime', 'n_items', 'value', 'orig_tax', 'final_tax', 'top_up_flg',
      'topped_up', 'top_up', 'severe', 'negative_top_up', 'amended', 'red', 'yellow', 'station']].head(10)
""")

md(r"""
### 4.1 One row per taxpayer: the starting table

Every feature below is added to this table, one row per taxpayer who declared in the 24 months.
""")

code(r"""
g = hist.groupby('tin')
F = pd.DataFrame({
    'entries_24m': g.size(),                                      # declarations in 24 months
    'total_customs_value': g['value'].sum(),
    'total_original_tax': g['orig_tax'].sum(),
    'total_top_up': g['top_up'].sum(),
})
F.index.name = 'taxpayer_tin'
print(f'{len(F):,} taxpayers')
F.head(10)
""")

# =================================================================================== 5 Track A
md(r"""
## 5. Track A features: the compliance history

These are the eight scored parameters agreed with the Risk Officers. Each is a **rate**, so a large and a small
importer can be compared fairly.
""")

md(r"""
### 5.1 `top_up_entry_rate`: declarations topped up (PAR_045T, the officers' rule)

**Inputs:** `topped_up` (0/1 per declaration, from Part 4). **Logic:** topped-up declarations ÷ all
declarations. **Why:** a taxpayer often found under-declaring is likely to be found again.
""")
code(r"""
F['top_up_entry_rate'] = g['topped_up'].mean()
F[['entries_24m', 'top_up_entry_rate']].head(10)
""")

md(r"""
### 5.2 `par077_severe_top_up_rate`: severe top-ups (PAR_077)

**Inputs:** `severe` (0/1: top-up of 30% or more of the final tax). **Logic:** severe top-ups ÷ declarations.
**Why:** a large correction says more about intent than a small one.
""")
code(r"""
F['par077_severe_top_up_rate'] = g['severe'].mean()
F[['entries_24m', 'par077_severe_top_up_rate']].head(10)
""")

md(r"""
### 5.3 `par045_amended_entry_rate`: declarations amended (PAR_045, also in Track B)

**Inputs:** `amendment_flg` (`Y`/`N`). **Logic:** amended declarations ÷ declarations. **Why:** declarations
that are often wrong the first time.
""")
code(r"""
F['par045_amended_entry_rate'] = (hist['amended'] == 'Y').groupby(hist['tin']).mean()
F[['entries_24m', 'par045_amended_entry_rate']].head(10)
""")

md(r"""
### 5.4 `par048_top_up_share_final`: top-ups as a share of the final tax (PAR_048)

**Inputs:** `total_top_up`, `total_original_tax` (UGX). **Logic:** top-ups ÷ (original tax + top-ups). Measured
over the final tax so it stays between 0 and 1. **Why:** how much of what the taxpayer finally paid had to be
found by customs.
""")
code(r"""
F['par048_top_up_ratio'] = F['total_top_up'] / F['total_original_tax'].replace(0, np.nan)   # as in the extract
final_tax = F['total_original_tax'] + F['total_top_up']
F['par048_top_up_share_final'] = (F['total_top_up'] / final_tax).where(final_tax > 0)
F[['total_original_tax', 'total_top_up', 'par048_top_up_share_final']].head(10)
""")

md(r"""
### 5.5 `par066_negative_top_up_rate`: tax reduced after assessment (PAR_066)

**Inputs:** `negative_top_up` (0/1). **Logic:** declarations whose final tax fell below the original ÷
declarations. **Why:** frequent reductions can point to errors or to pressure on assessments.
""")
code(r"""
F['par066_negative_top_up_rate'] = g['negative_top_up'].mean()
F[['entries_24m', 'par066_negative_top_up_rate']].head(10)
""")

md(r"""
### 5.6 `par105_top_up_180d`: a top-up in the last 180 days (PAR_105)

**Inputs:** `adate` of topped-up declarations. **Logic:** days from the last top-up to the snapshot; the feature
is 1 if that is 180 days or fewer. **Why:** recent non-compliance matters more than old.
""")
code(r"""
last_top_up = hist[hist['topped_up'] == 1].groupby('tin')['adate'].max()
F['par105_days_since_last_top_up'] = (SNAPSHOT - last_top_up).dt.days          # blank if never topped up
F['par105_top_up_180d'] = (F['par105_days_since_last_top_up'] <= 180).astype(float)
F[['par105_days_since_last_top_up', 'par105_top_up_180d']].head(10)
""")

md(r"""
### 5.7 `par023_station_spread`: clearing away from the main station (PAR_023, also in Track B)

**Inputs:** `clearance_station_cd` per declaration. **Logic:** count declarations per station; the main
station is the busiest; the feature is 1 − the main station's share. **Why:** moving between stations can be a
search for easier checks.
""")
code(r"""
per_station = hist.groupby(['tin', 'station'], dropna=False).size()          # a blank station counts as one
F['main_station_share'] = per_station.groupby('tin').max() / per_station.groupby('tin').sum()
F['par023_station_spread'] = 1.0 - F['main_station_share']
F[['main_station_share', 'par023_station_spread']].head(10)
""")

md(r"""
### 5.8 `par076_shortfall_share`: value below other importers' price (PAR_076, also in Track B)

This one needs a **benchmark**: the middle (median) price that **other importers** declare for the same goods.

**Inputs:** `customs_value`, `net_weight`, `supplementary_qnty`, `hsc_cd`, `gds_org_cty` (item rows).

**Logic, step by step:**
1. Price per kg = value ÷ weight; price per unit = value ÷ units (where units are given).
2. Benchmark per HS code: the median price per kg and per unit of all importers' items, if at least 5
   different importers bring that code. Where 5 or more bring it **from the same origin**, the origin's own
   median is used instead (goods of one code differ in price by origin).
3. Each item is then flagged:
   * **keying error** if its price per kg is under 1% of the benchmark (a weight in the wrong unit, kept out);
   * **low price** if it is under half the benchmark per kg (and per unit where units exist);
   * **shortfall** = how much more it would be worth at the benchmark price (the smaller of the per-kg and
     per-unit figures).
4. Per taxpayer: shortfall on low-priced items ÷ the taxpayer's benchmarked value.

**Why:** undervaluation is the main revenue risk at import. The same item table also gives four Track B
features (6.3 to 6.6).
""")
code(r"""
priced = hist_items[(hist_items['customs_value'] > 0) & (hist_items['net_weight'] > 0)].copy()
priced['price_kg'] = priced['customs_value'] / priced['net_weight']
priced['price_unit'] = (priced['customs_value'] / priced['supplementary_qnty']).where(priced['supplementary_qnty'] > 0)

def benchmark(keys):
    b = priced.groupby(keys).agg(med_per_kg=('price_kg', 'median'), med_per_unit=('price_unit', 'median'),
                                 importers=('taxpayer_tin', 'nunique'))
    return b[b['importers'] >= 5]                                   # at least 5 importers

bench_hs = benchmark(['hsc_cd'])
bench_origin = benchmark(['hsc_cd', 'gds_org_cty'])
print(f'Benchmarks: {len(bench_hs):,} HS codes, {len(bench_origin):,} HS code x origin pairs')

it = priced.merge(bench_hs[['med_per_kg', 'med_per_unit']], left_on='hsc_cd', right_index=True)              # HS benchmark needed
it = it.merge(bench_origin[['med_per_kg', 'med_per_unit']].add_suffix('_o'), how='left',
              left_on=['hsc_cd', 'gds_org_cty'], right_index=True)
on_origin = it['med_per_kg_o'].notna()
it['bm_kg'] = it['med_per_kg_o'].where(on_origin, it['med_per_kg'])
it['bm_unit'] = it['med_per_unit_o'].where(on_origin, it['med_per_unit'])
it['on_origin_bench'] = on_origin.astype(int)

unit_ok = it['bm_unit'].isna() | it['supplementary_qnty'].isna() | (it['supplementary_qnty'] <= 0) | \
          (it['customs_value'] / it['supplementary_qnty'] < 0.5 * it['bm_unit'])
it['implausible'] = (it['price_kg'] < 0.01 * it['bm_kg']).astype(int)
it['low_price'] = ((it['price_kg'] < 0.5 * it['bm_kg']) & (it['price_kg'] >= 0.01 * it['bm_kg']) & unit_ok).astype(int)
gap_kg = it['bm_kg'] * it['net_weight'] - it['customs_value']
gap_unit = (it['bm_unit'] * it['supplementary_qnty'] - it['customs_value']).where(it['supplementary_qnty'] > 0)
it['shortfall'] = np.fmin(gap_kg, gap_unit)                         # the smaller one; per kg where no units
it['price_deviation'] = np.abs(np.log(it['price_kg'] / it['bm_kg']))

gi = it.groupby('taxpayer_tin')
F['items_benchmarked'] = gi.size()
F['par076_shortfall_share'] = (it['shortfall'].where((it['low_price'] == 1) & (it['shortfall'] > 0), 0)
                               .groupby(it['taxpayer_tin']).sum() / gi['customs_value'].sum().replace(0, np.nan))
it[['taxpayer_tin', 'hsc_cd', 'gds_org_cty', 'customs_value', 'net_weight', 'price_kg', 'bm_kg',
    'implausible', 'low_price', 'shortfall']].head(10)
""")
code(r"""
F[['items_benchmarked', 'par076_shortfall_share']].dropna().head(10)
""")

# =================================================================================== 6 Track B
md(r"""
## 6. Track B features: how the taxpayer trades

Track B is for taxpayers with no top-up history, so it uses **no** input that records what customs did (no
top-ups, no lanes). Three of its features were already built above: `par045_amended_entry_rate` (5.3),
`par076_shortfall_share` (5.8) and the station measure (5.7, used here as `station_spread`).
""")

md(r"""
### 6.1 `ctx_unpaid_rate`: tax left unpaid (stand-in for PAR_072)

**Inputs:** `pay_status`, `final_amt`. **Logic:** declarations with tax due and status `NOT_PAID` ÷
declarations. **Why:** unpaid tax is non-compliance in itself.
""")
code(r"""
F['ctx_unpaid_rate'] = ((hist['pay_status'] == 'NOT_PAID') & (hist['final_tax'] > 0)).groupby(hist['tin']).mean()
F[['entries_24m', 'ctx_unpaid_rate']].head(10)
""")

md(r"""
### 6.2 `ctx_preferential_use_rate`: preferential treatment claimed (PAR_050)

**Inputs:** `preferential_treatment_flag` (item rows). **Logic:** items claiming preference ÷ items.
**Why:** a false origin claim (EAC, COMESA) avoids duty.
""")
code(r"""
F['ctx_preferential_use_rate'] = (hist_items['preferential_treatment_flag'] == 'Y').groupby(hist_items['taxpayer_tin']).mean()
F[['ctx_preferential_use_rate']].head(10)
""")

md(r"""
### 6.3 to 6.6 The other price features (from the item table in 5.8)

| Feature | Logic | Why |
|---|---|---|
| `ctx_implausible_price_rate` | items under 1% of the benchmark ÷ items | repeated "keying errors" can hide value |
| `par076_low_price_item_rate` | items under half the benchmark ÷ items | how often prices are low (5.8 gives how much) |
| `price_deviation_median` | the taxpayer's median distance from the benchmark, either way, on a log scale (keying errors left out) | prices far above peers can also signal risk (stand-in for PAR_090) |
| `origin_benchmark_share` | share of items priced against their own origin's benchmark | context only |
""")
code(r"""
F['ctx_implausible_price_rate'] = gi['implausible'].mean()
F['par076_low_price_item_rate'] = gi['low_price'].mean()
F['price_deviation_median'] = it[it['implausible'] == 0].groupby('taxpayer_tin')['price_deviation'].median()
F['origin_benchmark_share'] = gi['on_origin_bench'].mean()
F[['items_benchmarked', 'ctx_implausible_price_rate', 'par076_low_price_item_rate', 'price_deviation_median']].dropna().head(10)
""")

md(r"""
### 6.7 `own_price_drop_share`: price dropped against the taxpayer's own history (stand-in for PAR_067)

**Inputs:** `customs_value`, `net_weight`, `supplementary_qnty`, `hsc_cd`, `adate`.

**Logic:** for each tariff code the taxpayer imported both in the **last 6 months** and in the **18 months
before** (at least 2 earlier items and 1 recent), compare its own median price recently with before. A code
counts as a drop when the recent price is under 70% of the earlier one (per kg, and per unit where given).
The feature is the share of recent value on such codes. **Why:** a trader who suddenly declares the same
goods cheaper may have started undervaluing.
""")
code(r"""
cut = SNAPSHOT - pd.DateOffset(months=6)
p = priced.copy()
p['late'] = p['adate'] > cut
def own_history(d):
    e, l = d[~d['late']], d[d['late']]
    return pd.Series({'early_kg': e['price_kg'].median(), 'late_kg': l['price_kg'].median(),
                      'early_u': e['price_unit'].median(), 'late_u': l['price_unit'].median(),
                      'late_value': l['customs_value'].sum(), 'n_early': len(e), 'n_late': len(l)})
own = p.groupby(['taxpayer_tin', 'hsc_cd'], dropna=False).apply(own_history).reset_index()
own = own[(own['n_early'] >= 2) & (own['n_late'] >= 1) & (own['early_kg'] > 0)]
own['dropped'] = (own['late_kg'] < 0.7 * own['early_kg']) & \
                 (own['early_u'].isna() | own['late_u'].isna() | (own['late_u'] < 0.7 * own['early_u']))
go = own.groupby('taxpayer_tin')
F['hs_codes_compared'] = go.size()
F['own_price_drop_share'] = own['late_value'].where(own['dropped'], 0).groupby(own['taxpayer_tin']).sum() / go['late_value'].sum().replace(0, np.nan)
own.head(10)
""")

md(r"""
### 6.8 and 6.9 `low_duty_value_share` and `duty_gap_share`: duty below other importers (stand-ins for PAR_096, PAR_016)

**Inputs:** `tax_assessed`, `customs_value`, `hsc_cd`, `cpc_cd`.

**Logic:** for each tariff code, the median tax rate (tax ÷ value) that importers pay **with no exemption
claimed** (APC `000`), if at least 5 importers. Then, among the taxpayer's own APC `000` items:
* `low_duty_value_share` = value taxed at under half that rate ÷ value;
* `duty_gap_share` = the missing tax (median rate × value − tax paid) ÷ value.

Items under an exemption APC are left out on purpose: a lower rate is expected there. **Why:** paying much
less than others for the same goods points to a wrong tariff code or rate.
""")
code(r"""
taxed = hist_items[(hist_items['customs_value'] > 0) & (hist_items['tax_assessed'] >= 0)].copy()
taxed['rate'] = taxed['tax_assessed'] / taxed['customs_value']
no_exempt = taxed[taxed['cpc_cd'] == '000']
duty_bench = no_exempt.groupby('hsc_cd').agg(med_rate=('rate', 'median'), importers=('taxpayer_tin', 'nunique'))
duty_bench = duty_bench[duty_bench['importers'] >= 5]

taxed = taxed.merge(duty_bench[['med_rate']], left_on='hsc_cd', right_index=True, how='left')
base = (taxed['cpc_cd'] == '000') & (taxed['med_rate'] > 0)
base_value = taxed['customs_value'].where(base, 0).groupby(taxed['taxpayer_tin']).sum().replace(0, np.nan)
low = base & (taxed['rate'] < 0.5 * taxed['med_rate'])
gap = (taxed['med_rate'] * taxed['customs_value'] - taxed['tax_assessed']).clip(lower=0).where(base, 0)
F['low_duty_value_share'] = taxed['customs_value'].where(low, 0).groupby(taxed['taxpayer_tin']).sum() / base_value
F['duty_gap_share'] = gap.groupby(taxed['taxpayer_tin']).sum() / base_value
taxed[['taxpayer_tin', 'hsc_cd', 'cpc_cd', 'customs_value', 'tax_assessed', 'rate', 'med_rate']].head(10)
""")

md(r"""
### 6.10 and 6.11 `exemption_apc_value_share` and `watchlist_apc_value_share` (PAR_052, PAR_053)

**Inputs:** `cpc_cd`, `customs_value`. **Logic:** value under any APC other than `000` ÷ value; and value
under the 11 APCs the AC-Trade memo marks "look out for possible abuse" ÷ value. **Why:** exemptions are a
known route for revenue loss.
""")
code(r"""
WATCHLIST = ['404', '409', '417', '451', '455', '457', '476', '479', '481', '482', '484']
ap = hist_items[hist_items['customs_value'] > 0]
total = ap.groupby('taxpayer_tin')['customs_value'].sum().replace(0, np.nan)
exempt = ap['cpc_cd'].notna() & (ap['cpc_cd'] != '000')
F['exemption_apc_value_share'] = ap['customs_value'].where(exempt, 0).groupby(ap['taxpayer_tin']).sum() / total
F['watchlist_apc_value_share'] = ap['customs_value'].where(ap['cpc_cd'].isin(WATCHLIST), 0).groupby(ap['taxpayer_tin']).sum() / total
F[['exemption_apc_value_share', 'watchlist_apc_value_share']].head(10)
""")

md(r"""
### 6.12 `same_day_split_excess`: same-day splitting above the norm (raised by the officers)

**Inputs:** `hsc_cd`, `assessment_dt_wid`, `instance_id`, `extended_proc_cd`.

**Logic:**
1. Count each taxpayer's declarations per tariff code per day (`n`). Cement and salt (chapter 25), fuel
   (chapter 27) and fuel transit (EPC 4080, 7180) are left out: they legitimately arrive as many trucks a day.
2. The **norm** for each tariff code: across all importers, the share of declarations that came in same-day
   repeats (`n` of 2 or more).
3. The taxpayer's own share in same-day repeats, minus the norm for its own mix of goods.

**Why:** splitting one consignment can keep each declaration under a value or check threshold.
""")
code(r"""
sp = hist_items[hist_items['hsc_cd'].notna() & ~hist_items['hsc_cd'].str[:2].isin(['25', '27'])
                & ~hist_items['extended_proc_cd'].fillna('').isin(['4080', '7180'])]
grp = sp.groupby(['taxpayer_tin', 'assessment_dt_wid', 'hsc_cd'])['instance_id'].nunique().rename('n').reset_index()
grp['n_repeat'] = grp['n'].where(grp['n'] >= 2, 0)
norm = grp.groupby('hsc_cd')['n_repeat'].sum() / grp.groupby('hsc_cd')['n'].sum()
grp['expected'] = grp['n'] * grp['hsc_cd'].map(norm)
gs = grp.groupby('taxpayer_tin')
F['same_day_split_share'] = gs['n_repeat'].sum() / gs['n'].sum()
F['same_day_split_expected'] = gs['expected'].sum() / gs['n'].sum()
F['same_day_split_excess'] = F['same_day_split_share'] - F['same_day_split_expected']
grp.sort_values('n', ascending=False).head(10)
""")

md(r"""
### 6.13 `surge`: sudden rise in declarations (our own)

**Inputs:** `adate` per declaration. **Logic:** declarations in the last 90 days, against the average quarter
over 24 months (24 months ÷ 8 quarters), on a log scale: `log((last 90 days + 1) / (average quarter + 1))`.
0 = a normal quarter, +1.1 = about 3 times normal. **Why:** a sharp jump can mean a borrowed TIN or a burst
before disappearing.
""")
code(r"""
F['entries_last_90d'] = (hist['adate'] > SNAPSHOT - pd.Timedelta(days=90)).groupby(hist['tin']).sum()
F['surge'] = np.log((F['entries_last_90d'] + 1) / (F['entries_24m'] / 8.0 + 1))
F[['entries_24m', 'entries_last_90d', 'surge']].head(10)
""")

md(r"""
### 6.14 `station_spread` and 6.15 `goods_spread`

* `station_spread` = 1 − the main station's share (the same as `par023_station_spread` in 5.7).
* `goods_spread` = different 4-digit HS headings ÷ declarations. **Why:** mixing many goods makes checks
  harder and can hide misdescribed items.
""")
code(r"""
F['station_spread'] = 1.0 - F['main_station_share']
F['hs_headings_used'] = hist_items.groupby('taxpayer_tin')['hsc_cd'].apply(lambda s: s.str[:4].nunique())
F['goods_spread'] = F['hs_headings_used'] / F['entries_24m'].clip(lower=1)
F[['entries_24m', 'hs_headings_used', 'goods_spread', 'station_spread']].head(10)
""")

md(r"""
### 6.16 `newness`: recently started importing (PAR_019, PAR_101)

**Inputs:** `adate`; and the list of taxpayers who declared IM4 or IM7 in the 3 years **before** the 24-month
window (`prior_tins.csv`). **Logic:** `new_trader` = not on that list. `newness` = −log(1 + days since the
first declaration in the window), plus 1 for a new trader, so newer gives a higher value. **Why:** new traders
have no track record; new TINs are used for one-off fraud.
""")
code(r"""
F['days_since_first_in_window'] = (SNAPSHOT - g['adate'].min()).dt.days
prior_file = DATA / 'prior_tins.csv'
prior = set(pd.read_csv(prior_file, dtype=str).iloc[:, 0]) if prior_file.exists() else set()
F['new_trader'] = np.where(F.index.isin(prior), 'N', 'Y')
F['newness'] = -np.log1p(F['days_since_first_in_window'].clip(lower=0)) + (F['new_trader'] == 'Y') * 1.0
F[['days_since_first_in_window', 'new_trader', 'newness']].head(10)
""")

# =================================================================================== 7 after
md(r"""
## 7. Steps after the features

### 7.1 Recency: recent years count more (Track A)

The top-up, severe top-up, amendment and tax-reduction rates and the top-up share are rebuilt from the last
**3 years**, the latest year counting fully, the year before half, the one before a quarter.
""")
code(r"""
WEIGHTS = {1: 1.0, 2: 0.5, 3: 0.25}
d3 = decl[decl['dt'] <= ymd(SNAPSHOT)].copy()
d3['year_back'] = np.select([d3['adate'] > SNAPSHOT - pd.DateOffset(months=12),
                             d3['adate'] > SNAPSHOT - pd.DateOffset(months=24)], [1, 2], 3)
d3['w'] = d3['year_back'].map(WEIGHTS)
d3['is_amended'] = (d3['amended'] == 'Y').astype(int)
gw = d3.assign(**{c: d3[c] * d3['w'] for c in ['topped_up', 'severe', 'is_amended', 'negative_top_up', 'top_up', 'orig_tax']}).groupby('tin')
n_w = d3.groupby('tin')['w'].sum()
R = pd.DataFrame({'top_up_entry_rate': gw['topped_up'].sum() / n_w,
                  'par077_severe_top_up_rate': gw['severe'].sum() / n_w,
                  'par045_amended_entry_rate': gw['is_amended'].sum() / n_w,
                  'par066_negative_top_up_rate': gw['negative_top_up'].sum() / n_w})
tu, ot = gw['top_up'].sum(), gw['orig_tax'].sum()
R['par048_top_up_share_final'] = (tu / (ot + tu)).where(ot + tu > 0)
A = F.copy()                                         # A = the Track A inputs after recency
for c in R:
    A.loc[A.index.intersection(R.index), c] = R[c]
pd.concat([F[['top_up_entry_rate']].rename(columns={'top_up_entry_rate': '24 months, equal'}),
           A[['top_up_entry_rate']].rename(columns={'top_up_entry_rate': '3 years, weighted'})], axis=1).head(10)
""")

md(r"""
### 7.2 Small numbers: credibility weighting (Track A and Track B)

A rate built on 2 declarations is mostly luck. Each rate is pulled towards the average of everyone by weight
`n / (n + 10)`, where `n` is the taxpayer's declarations (items, for the price features). It is only ever
pulled **down**, so a clean small trader is never given other people's behaviour.

Example: 1 amended declaration out of 2 (50%), average 15%: weight 2/12 = 0.17, so 0.17 × 50% + 0.83 × 15% ≈ 21%.
""")
code(r"""
def credibility(rate, n, k=10):
    has = rate.notna() & (n > 0)
    average = (rate[has] * n[has]).sum() / n[has].sum()     # weighted by declarations
    w = n / (n + k)
    return np.minimum(rate, w * rate + (1 - w) * average)

example = pd.DataFrame({'declarations': F['entries_24m'], 'amended (raw)': F['par045_amended_entry_rate'],
                        'amended (weighted)': credibility(F['par045_amended_entry_rate'], F['entries_24m'])})
example.sort_values('declarations').head(10)
""")

md(r"""
### 7.3 Peer groups and percentiles (Track B)

Each Track B feature becomes a **percentile within the taxpayer's peer group**: the HS section of its main goods
× its size (small, medium, large by customs value within that section). "Higher than 97% of similar importers"
is fair across goods and sizes, and reads directly as a reason. A missing value sits at 50%.
""")
code(r"""
# main HS chapter = the chapter with most of the taxpayer's value
ch = hist_items.assign(ch=hist_items['hsc_cd'].str[:2]).groupby(['taxpayer_tin', 'ch'])['customs_value'].sum()
F['dominant_hs_chapter'] = ch.groupby(level=0).idxmax().str[1]
SECTIONS = [(1, 5, 'Live animals'), (6, 14, 'Vegetable products'), (15, 15, 'Fats and oils'), (16, 24, 'Food, drink, tobacco'),
            (25, 27, 'Minerals and fuel'), (28, 38, 'Chemicals'), (39, 40, 'Plastics and rubber'), (41, 43, 'Hides and leather'),
            (44, 46, 'Wood'), (47, 49, 'Paper'), (50, 63, 'Textiles'), (64, 67, 'Footwear'), (68, 70, 'Stone, glass'),
            (71, 71, 'Precious metals'), (72, 83, 'Base metals'), (84, 85, 'Machinery, electrical'), (86, 89, 'Vehicles'),
            (90, 92, 'Instruments'), (93, 93, 'Arms'), (94, 96, 'Miscellaneous manufactures'), (97, 99, 'Art and other')]
def section(c):
    try:
        c = int(c)
    except (TypeError, ValueError):
        return 'Unknown'
    return next((name for lo, hi, name in SECTIONS if lo <= c <= hi), 'Unknown')
F['section'] = F['dominant_hs_chapter'].map(section)
logv = np.log1p(F['total_customs_value'].clip(lower=0))
F['size'] = logv.groupby(F['section']).transform(
    lambda v: pd.qcut(v.rank(method='first'), 3, labels=['small', 'medium', 'large']) if len(v) >= 3 else 'medium').astype(str)
F['peer_group'] = F['section'] + ', ' + F['size']

TRACK_B = ['par045_amended_entry_rate', 'ctx_unpaid_rate', 'ctx_implausible_price_rate', 'par076_shortfall_share',
           'par076_low_price_item_rate', 'price_deviation_median', 'own_price_drop_share', 'low_duty_value_share',
           'duty_gap_share', 'exemption_apc_value_share', 'watchlist_apc_value_share', 'ctx_preferential_use_rate',
           'surge', 'station_spread', 'goods_spread', 'same_day_split_excess', 'newness']
PCT = pd.DataFrame({c: F[c].groupby(F['peer_group']).rank(pct=True).fillna(0.5) for c in TRACK_B})
PCT.insert(0, 'peer_group', F['peer_group'])
PCT.head(10)
""")

# =================================================================================== 8 final
md(r"""
## 8. The final feature table, and a check against production

### 8.1 All features, one row per taxpayer
""")
code(r"""
TRACK_A = ['top_up_entry_rate', 'par077_severe_top_up_rate', 'par045_amended_entry_rate', 'par048_top_up_share_final',
           'par076_shortfall_share', 'par066_negative_top_up_rate', 'par105_top_up_180d', 'par023_station_spread']
features = F[['entries_24m', 'total_customs_value'] + TRACK_A + [c for c in TRACK_B if c not in TRACK_A]]
print(f'{features.shape[0]:,} taxpayers x {features.shape[1]} columns')
features.head(10)
""")

md(r"""
### 8.2 Do these numbers match production?

Production builds the same columns with one query on the full view. For the taxpayers in this sample, each
column is compared with the production extract for the same snapshot.

* **Exact match** expected for every feature that uses only the taxpayer's own declarations.
* **Close, not equal** for the features that compare with other importers (price and duty benchmarks, the
  same-day norm), because here "other importers" are only the sampled ones. The correlation shows how close.
* Small differences can also come from rows changed in the view since the production extract was pulled (a
  payment made, a top-up raised later).
""")
code(r"""
candidates = [Path(os.environ.get('CTRP_PROD_EXTRACT', '/nonexistent')),
              ROOT / 'data' / 'v2 extracts' / f'live_{SNAPSHOT.date()} (1).csv', ROOT / 'data_v2' / f'live_{SNAPSHOT.date()}.csv',
              ROOT / 'data' / f'live_{SNAPSHOT.date()}.csv']
prod_file = next((p for p in candidates if p.exists()), None)
if prod_file is None:
    print('No production extract found for this snapshot; skipping the check.')
else:
    prod = pd.read_csv(prod_file, dtype={'taxpayer_tin': str}).set_index('taxpayer_tin')
    common = F.index.intersection(prod.index)
    print(f'Production file: {prod_file.name};  taxpayers in both: {len(common):,} of {len(F):,}')
    OTHERS = {'par076_shortfall_share', 'par076_low_price_item_rate', 'ctx_implausible_price_rate', 'price_deviation_median',
              'items_benchmarked', 'low_duty_value_share', 'duty_gap_share', 'same_day_split_excess'}
    rows = []
    for c in ['entries_24m', 'total_customs_value', 'total_original_tax', 'total_top_up', 'top_up_entry_rate',
              'par077_severe_top_up_rate', 'par045_amended_entry_rate', 'par048_top_up_ratio', 'par066_negative_top_up_rate',
              'par105_days_since_last_top_up', 'main_station_share', 'ctx_unpaid_rate', 'ctx_preferential_use_rate',
              'hs_headings_used', 'entries_last_90d', 'days_since_first_in_window', 'exemption_apc_value_share',
              'watchlist_apc_value_share', 'own_price_drop_share'] + sorted(OTHERS):
        if c not in prod:
            continue
        a = pd.to_numeric(F.loc[common, c], errors='coerce'); b = pd.to_numeric(prod.loc[common, c], errors='coerce')
        both = a.notna() & b.notna()
        same = np.isclose(a[both], b[both], rtol=1e-6, atol=1e-9)
        rows.append({'column': c, 'compares with other importers': 'yes' if c in OTHERS else '',
                     'taxpayers compared': int(both.sum()), 'exact match': same.mean() if both.any() else np.nan,
                     'correlation': a[both].corr(b[both]) if both.sum() > 2 else np.nan})
    display(pd.DataFrame(rows))
""")

md(r"""
**Reading the check.** Columns built from the taxpayer's own declarations should show an exact match close
to 100%. Columns that compare with other importers will show a lower exact match but a high correlation; in
production they use every importer in the country.
""")

nb['cells'] = C
nb['metadata'] = {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                  'language_info': {'name': 'python'}}
out = Path(__file__).parent / 'CTRP_features_in_python.ipynb'
nbf.write(nb, out)
print(f'written {out}  ({len(C)} cells)')
