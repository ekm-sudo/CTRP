"""
Post-clearance audit list: every import entry since 1 July 2026, in every lane, checked against what other importers
declare, with the taxpayer's risk profile beside it. For Post Clearance Audit and the National Targeting Centre.

What: (1) writes the Hue queries: one per month for the entries (one row per entry, every signal rolled up) and one
      for the items that carry a price or duty signal (the evidence, with the peer values);
      (2) reads the downloads and the live scores workbook and writes one Excel workbook, ranked by strength of
      evidence and then by tax at stake.
Why:  the taxpayer list says who to look at; this says which entries, and why, with the numbers an officer needs to
      check them in ASYCUDA.

    python main.py pca --sql     -> sql/pca/pca_entries_<month>.sql (4), sql/pca/pca_items.sql
                                    (+ sql/pca/if_too_big/pca_items_<month>.sql, if the items query is cut at 100,000)
    python main.py pca           -> results/CTRP_post_clearance_audit_<date>.xlsx

The rules are the model's (version 3): IM4 and IM7, not cancelled, 10-digit TIN, no APC 483, the latest declaration ID
per entry, no motor vehicle declarations, each item once. "Peers" are all importers of the same HS code (and origin,
where 5 or more importers bring it from there) in the 24 months before 1 July 2026; only comparisons with 5 or more
importers are used. The signals:
    price       price per kg (and per unit, where a quantity is given) as a share of the peer middle price.
                Under 50% = strong, 50-80% = some. Under 1% = a keying error (check the units), not undervaluation.
    duty        duty rate of an item with no exemption (APC 000) as a share of the peer middle rate. Under 50% = strong.
    exemption   value under an exemption APC (not 000), and any watchlist APC used.
    preference  items claiming preferential treatment.
    split       declarations of the same HS code by the same taxpayer on the same day (cement, salt, fuel and fuel
                transit left out), against how often other importers of those goods do it.
    amended     the declaration was amended.
    new         the taxpayer's first import in the last 5 years is within 12 months of 1 July 2026.
Tax at stake (per item, never counted twice): for a low-priced item, the value gap x the item's own tax rate (at most
100%); otherwise, for a low-duty item, the duty gap against the peer middle rate. A screening estimate, not a finding.
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

from ctrp import eda_note as N
from ctrp import extract as E
from ctrp.utils import DATA_DIR, RESULTS_DIR, SQL_DIR

VIEW = 'dm_modeled_ura_datascience.vw_cstm_AEO_model'
SQL_OUT = SQL_DIR / 'pca'
DATA = DATA_DIR / 'pca'
START = '20260630'                                     # entries assessed after this date, i.e. from 1 July 2026
PEER_START, PEER_END = '20240630', '20260630'          # the 24 months of peers before 1 July 2026
FIVE_YEARS_BACK = '20210630'
NEW_SINCE = '20250630'                                 # first import after this = new importer
MONTHS = [('2026-07', '20260630', '20260731'), ('2026-08', '20260731', '20260831'),
          ('2026-09', '20260831', '20260930'), ('2026-10', '20260930', '20261031')]
HUE_CAP = 100_000
MV = ', '.join(f"'{h}'" for h in E.MOTOR_VEHICLE_HEADINGS)
WATCH = ', '.join(f"'{a}'" for a in N.WATCHLIST_APCS)
KEY = 'COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id)'


# =========================================================================================
# 1. The queries
# =========================================================================================
def _ctes(start, end):
    """The cleaned entries in (start, end], the peer benchmarks and every item-level signal."""
    return f"""WITH recent_raw AS (
  SELECT {KEY} AS entry_key, v.instance_id, v.key_itm_nbr, v.taxpayer_tin, v.taxpayer_nm, v.consignee_tin,
         v.consignee_nm, v.clearance_station_cd, v.dec_ref_yer, v.entry_num, v.assessment_dt_wid, v.regime_cd,
         v.decl_status, v.pay_status, v.extended_proc_cd, v.cpc_cd, v.hsc_cd, v.gds_org_cty,
         CAST(v.customs_value AS DOUBLE) AS customs_value, CAST(v.net_weight AS DOUBLE) AS net_weight,
         CAST(v.supplementary_qnty AS DOUBLE) AS supplementary_qnty, CAST(v.tax_assessed AS DOUBLE) AS tax_assessed,
         CAST(v.original_tax_amt AS DOUBLE) AS original_tax_amt, CAST(v.final_amt AS DOUBLE) AS final_amt,
         v.top_up_flg, v.amendment_flg, v.preferential_treatment_flag,
         CAST(v.is_red_flg AS INT) AS red, CAST(v.is_yellow_flg AS INT) AS yellow,
         CAST(v.is_green_flg AS INT) AS green, CAST(v.is_blue_flg AS INT) AS blue,
         ROW_NUMBER() OVER (PARTITION BY v.instance_id, v.key_itm_nbr ORDER BY v.assessment_dt_wid) AS rn,
         MAX(lpad(v.instance_id, 20, '0')) OVER (PARTITION BY {KEY}) AS latest_instance,
         MAX(CASE WHEN substr(v.hsc_cd, 1, 4) IN ({MV}) THEN 1 ELSE 0 END) OVER (PARTITION BY v.instance_id) AS has_vehicle
  FROM {VIEW} v
  WHERE v.assessment_dt_wid > '{start}' AND v.assessment_dt_wid <= '{end}'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND COALESCE(v.decl_status, '') <> 'Cancelled'
    AND COALESCE(v.cpc_cd, '') <> '483'
    AND v.taxpayer_tin RLIKE '^[0-9]{{10}}$'
),
recent AS (SELECT * FROM recent_raw
           WHERE rn = 1 AND lpad(instance_id, 20, '0') = latest_instance AND has_vehicle = 0),

-- peers: every importer of the same goods in the 24 months before 1 July 2026, each item once
codes AS (SELECT DISTINCT hsc_cd FROM recent),
peers AS (
  SELECT DISTINCT v.instance_id, v.key_itm_nbr, v.taxpayer_tin, v.hsc_cd, v.gds_org_cty, v.cpc_cd,
         v.extended_proc_cd, v.assessment_dt_wid,
         CAST(v.customs_value AS DOUBLE) AS customs_value, CAST(v.net_weight AS DOUBLE) AS net_weight,
         CAST(v.supplementary_qnty AS DOUBLE) AS supplementary_qnty, CAST(v.tax_assessed AS DOUBLE) AS tax_assessed
  FROM {VIEW} v
  JOIN codes c ON v.hsc_cd = c.hsc_cd
  WHERE v.assessment_dt_wid > '{PEER_START}' AND v.assessment_dt_wid <= '{PEER_END}'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND COALESCE(v.decl_status, '') <> 'Cancelled'
    AND v.customs_value > 0
),
bench_h AS (SELECT hsc_cd, percentile_approx(customs_value / net_weight, 0.5) AS med_kg,
                   COUNT(DISTINCT taxpayer_tin) AS importers
            FROM peers WHERE net_weight > 0 GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
bench_ho AS (SELECT hsc_cd, gds_org_cty, percentile_approx(customs_value / net_weight, 0.5) AS med_kg,
                    COUNT(DISTINCT taxpayer_tin) AS importers
             FROM peers WHERE net_weight > 0 GROUP BY hsc_cd, gds_org_cty HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
bench_u AS (SELECT hsc_cd, percentile_approx(customs_value / supplementary_qnty, 0.5) AS med_unit
            FROM peers WHERE supplementary_qnty > 0 GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
bench_duty AS (SELECT hsc_cd, percentile_approx(tax_assessed / customs_value, 0.5) AS med_rate
               FROM peers WHERE cpc_cd = '000' AND tax_assessed >= 0
               GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
peer_days AS (SELECT taxpayer_tin, assessment_dt_wid, hsc_cd, COUNT(DISTINCT instance_id) AS n FROM peers
              WHERE substr(hsc_cd, 1, 2) NOT IN ('25', '27') AND COALESCE(extended_proc_cd, '') NOT IN ('4080', '7180')
              GROUP BY taxpayer_tin, assessment_dt_wid, hsc_cd),
split_norm AS (SELECT hsc_cd, SUM(CASE WHEN n >= 2 THEN n ELSE 0 END) / SUM(n) AS norm_share
               FROM peer_days GROUP BY hsc_cd),

-- the same taxpayer, same goods, same day, in the recent entries
days AS (SELECT taxpayer_tin, assessment_dt_wid, hsc_cd, COUNT(DISTINCT instance_id) AS same_day_decl FROM recent
         WHERE substr(hsc_cd, 1, 2) NOT IN ('25', '27') AND COALESCE(extended_proc_cd, '') NOT IN ('4080', '7180')
         GROUP BY taxpayer_tin, assessment_dt_wid, hsc_cd),

-- the taxpayer's first import in the last 5 years
tins AS (SELECT DISTINCT taxpayer_tin FROM recent),
first_seen AS (SELECT v.taxpayer_tin, MIN(v.assessment_dt_wid) AS first_import
               FROM {VIEW} v JOIN tins t ON v.taxpayer_tin = t.taxpayer_tin
               WHERE v.assessment_dt_wid > '{FIVE_YEARS_BACK}' AND v.regime_cd IN ('IM4', 'IM7')
                 AND COALESCE(v.decl_status, '') <> 'Cancelled'
               GROUP BY v.taxpayer_tin),

-- every item with its prices, its peers and its signals
it AS (
  SELECT r.*,
         CASE WHEN r.customs_value > 0 AND r.net_weight > 0 THEN r.customs_value / r.net_weight END AS price_kg,
         CASE WHEN r.customs_value > 0 AND r.supplementary_qnty > 0 THEN r.customs_value / r.supplementary_qnty END AS price_unit,
         CASE WHEN substr(r.hsc_cd, 1, 2) <> '27' THEN COALESCE(o.med_kg, h.med_kg) END AS peer_kg,
         CASE WHEN substr(r.hsc_cd, 1, 2) <> '27' THEN u.med_unit END AS peer_unit,
         COALESCE(o.importers, h.importers) AS peer_importers,
         CASE WHEN o.med_kg IS NOT NULL THEN 'HS code and origin' WHEN h.med_kg IS NOT NULL THEN 'HS code' END AS peer_basis,
         CASE WHEN r.customs_value > 0 AND r.tax_assessed >= 0 THEN r.tax_assessed / r.customs_value END AS duty_rate,
         t.med_rate AS peer_duty_rate,
         d.same_day_decl, s.norm_share AS same_day_norm
  FROM recent r
  LEFT JOIN bench_h h ON r.hsc_cd = h.hsc_cd
  LEFT JOIN bench_ho o ON r.hsc_cd = o.hsc_cd AND r.gds_org_cty = o.gds_org_cty
  LEFT JOIN bench_u u ON r.hsc_cd = u.hsc_cd
  LEFT JOIN bench_duty t ON r.hsc_cd = t.hsc_cd
  LEFT JOIN days d ON r.taxpayer_tin = d.taxpayer_tin AND r.assessment_dt_wid = d.assessment_dt_wid AND r.hsc_cd = d.hsc_cd
  LEFT JOIN split_norm s ON r.hsc_cd = s.hsc_cd
),
ratios AS (
  SELECT it.*,
         CASE WHEN price_kg IS NOT NULL AND peer_kg > 0 THEN price_kg / peer_kg END AS price_vs_peers,
         CASE WHEN price_unit IS NOT NULL AND peer_unit > 0 THEN price_unit / peer_unit END AS unit_price_vs_peers,
         CASE WHEN cpc_cd = '000' AND peer_duty_rate > 0 AND duty_rate IS NOT NULL THEN duty_rate / peer_duty_rate END AS duty_vs_peers
  FROM it
),
items AS (
  SELECT ratios.*,
         CASE WHEN price_vs_peers < 0.01 THEN 1 ELSE 0 END AS keying_error,
         CASE WHEN price_vs_peers >= 0.01 AND price_vs_peers < 0.5
                   AND (unit_price_vs_peers IS NULL OR unit_price_vs_peers < 0.5) THEN 1 ELSE 0 END AS low_price,
         CASE WHEN price_vs_peers >= 0.5 AND price_vs_peers < 0.8
                   AND (unit_price_vs_peers IS NULL OR unit_price_vs_peers < 0.8) THEN 1 ELSE 0 END AS some_low_price,
         GREATEST(LEAST(peer_kg * net_weight - customs_value,
                        CASE WHEN supplementary_qnty > 0 AND peer_unit IS NOT NULL
                             THEN peer_unit * supplementary_qnty - customs_value END), 0) AS value_gap,
         CASE WHEN duty_vs_peers < 0.5 THEN 1 ELSE 0 END AS low_duty,
         CASE WHEN duty_vs_peers IS NOT NULL THEN GREATEST(peer_duty_rate * customs_value - tax_assessed, 0) ELSE 0 END AS duty_gap
  FROM ratios
),
scored AS (
  SELECT items.*,
         CASE WHEN low_price = 1 THEN COALESCE(value_gap, 0) * LEAST(COALESCE(duty_rate, 0), 1)
              WHEN low_duty = 1 THEN duty_gap ELSE 0 END AS tax_at_stake
  FROM items
)"""


def q_entries(start, end):
    """One row per entry assessed in (start, end], every lane, every signal rolled up."""
    return _ctes(start, end) + f"""
SELECT s.entry_key, s.instance_id,
       MAX(s.entry_num) AS entry_num, MAX(s.clearance_station_cd) AS station, MAX(s.dec_ref_yer) AS entry_year,
       to_date(MAX(s.assessment_dt_wid), 'yyyyMMdd') AS assessed_on,
       MAX(s.taxpayer_tin) AS taxpayer_tin, MAX(s.taxpayer_nm) AS taxpayer_nm,
       MAX(s.consignee_tin) AS consignee_tin, MAX(s.consignee_nm) AS consignee_nm,
       MAX(s.regime_cd) AS regime, MAX(s.decl_status) AS status, MAX(s.pay_status) AS pay_status,
       CASE WHEN COALESCE(MAX(s.red), 0) = 1 THEN 'Red' WHEN COALESCE(MAX(s.yellow), 0) = 1 THEN 'Yellow'
            WHEN COALESCE(MAX(s.green), 0) = 1 THEN 'Green' WHEN COALESCE(MAX(s.blue), 0) = 1 THEN 'Blue'
            ELSE 'No flag' END AS lane,
       COALESCE(MAX(s.original_tax_amt), MAX(s.final_amt)) AS original_tax, MAX(s.final_amt) AS final_tax,
       CASE WHEN MAX(s.top_up_flg) = 'Y' AND MAX(s.final_amt) > COALESCE(MAX(s.original_tax_amt), MAX(s.final_amt))
            THEN 'Y' ELSE 'N' END AS topped_up,
       GREATEST(MAX(s.final_amt) - COALESCE(MAX(s.original_tax_amt), MAX(s.final_amt)), 0) AS tax_raised,
       MAX(s.amendment_flg) AS amended,
       COUNT(*) AS items, SUM(s.customs_value) AS customs_value, SUM(s.tax_assessed) AS tax_assessed,
       concat_ws(', ', sort_array(collect_set(s.cpc_cd))) AS apcs,
       concat_ws(', ', sort_array(collect_set(s.extended_proc_cd))) AS epcs,
       COUNT(DISTINCT s.hsc_cd) AS hs_codes,
       -- price
       SUM(s.low_price) AS items_under_half_peer_price,
       SUM(s.some_low_price) AS items_50_80_pct_of_peer_price,
       SUM(s.keying_error) AS items_possible_unit_error,
       MIN(CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_vs_peers,
       min_by(s.hsc_cd, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_hs_code,
       min_by(s.gds_org_cty, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_origin,
       min_by(s.price_kg, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_per_kg,
       min_by(s.peer_kg, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_price_per_kg,
       min_by(s.price_unit, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_per_unit,
       min_by(s.peer_unit, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_price_per_unit,
       min_by(s.peer_basis, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_basis,
       min_by(s.peer_importers, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_importers,
       SUM(CASE WHEN s.low_price = 1 THEN s.value_gap ELSE 0 END) AS value_gap,
       -- duty
       SUM(s.low_duty) AS items_under_half_peer_duty,
       MIN(s.duty_vs_peers) AS lowest_duty_vs_peers,
       min_by(s.hsc_cd, s.duty_vs_peers) AS lowest_duty_hs_code,
       min_by(s.duty_rate, s.duty_vs_peers) AS lowest_duty_rate,
       min_by(s.peer_duty_rate, s.duty_vs_peers) AS peer_duty_rate,
       SUM(CASE WHEN s.low_duty = 1 THEN s.duty_gap ELSE 0 END) AS duty_gap,
       -- exemptions and preference
       SUM(CASE WHEN COALESCE(s.cpc_cd, '000') <> '000' THEN s.customs_value ELSE 0 END) AS value_under_exemption,
       concat_ws(', ', sort_array(collect_set(CASE WHEN s.cpc_cd IN ({WATCH}) THEN s.cpc_cd END))) AS watchlist_apcs,
       SUM(CASE WHEN s.preferential_treatment_flag = 'Y' THEN 1 ELSE 0 END) AS items_claiming_preference,
       -- same-day split
       MAX(s.same_day_decl) AS same_day_same_hs_declarations,
       max_by(s.same_day_norm, s.same_day_decl) AS same_day_norm_for_goods,
       -- new importer
       to_date(MAX(f.first_import), 'yyyyMMdd') AS first_import_in_5_years,
       CASE WHEN MAX(f.first_import) > '{NEW_SINCE}' THEN 'Y' ELSE 'N' END AS new_importer,
       SUM(s.tax_at_stake) AS tax_at_stake
FROM scored s
LEFT JOIN first_seen f ON s.taxpayer_tin = f.taxpayer_tin
GROUP BY s.entry_key, s.instance_id
"""


def q_items(start, end):
    """The items with a price or duty signal (the evidence), with the peer values."""
    return _ctes(start, end) + """
SELECT entry_key, instance_id, entry_num, clearance_station_cd AS station, dec_ref_yer AS entry_year,
       to_date(assessment_dt_wid, 'yyyyMMdd') AS assessed_on, taxpayer_tin, key_itm_nbr AS item, hsc_cd AS hs_code,
       gds_org_cty AS origin, cpc_cd AS apc, preferential_treatment_flag AS preference,
       customs_value, net_weight, supplementary_qnty AS quantity, tax_assessed,
       price_kg, peer_kg, price_vs_peers, price_unit, peer_unit, unit_price_vs_peers, peer_basis, peer_importers,
       value_gap, duty_rate, peer_duty_rate, duty_vs_peers, duty_gap, tax_at_stake,
       CASE WHEN keying_error = 1 THEN 'Possible unit error' WHEN low_price = 1 THEN 'Under half the peer price'
            WHEN some_low_price = 1 THEN '50-80% of the peer price' ELSE '' END AS price_signal,
       CASE WHEN low_duty = 1 THEN 'Under half the peer duty rate' ELSE '' END AS duty_signal
FROM scored
WHERE keying_error = 1 OR low_price = 1 OR some_low_price = 1 OR low_duty = 1
"""


def write_queries():
    SQL_OUT.mkdir(parents=True, exist_ok=True)
    (SQL_OUT / 'if_too_big').mkdir(exist_ok=True)
    head = ('-- CTRP post-clearance audit list ({what}), entries assessed {a} to {b}. Contains TINs: internal use only.\n'
            '-- Run in Hue as ONE statement, download as CSV, save as data/pca/{save}\n')
    jobs = []
    for month, a, b in MONTHS:
        jobs.append((SQL_OUT / f'pca_entries_{month}.sql', head.format(what='entries', a=a, b=b, save=f'entries_{month}.csv')
                     + q_entries(a, b)))
        jobs.append((SQL_OUT / 'if_too_big' / f'pca_items_{month}.sql',
                     head.format(what='items with a signal', a=a, b=b, save=f'items_{month}.csv') + q_items(a, b)))
    end = MONTHS[-1][2]
    jobs.append((SQL_OUT / 'pca_items.sql', head.format(what='items with a signal', a=START, b=end, save='items.csv')
                 + q_items(START, end)))
    for path, sql in jobs:
        assert ';' not in sql, path                     # Hue splits statements on semicolons
        path.write_text(sql)
    print(f'written {len(MONTHS)} entry queries and the items query in sql/pca/ (per-month item queries in '
          f'sql/pca/if_too_big/ if the items download stops at 100,000 rows)')


# =========================================================================================
# 2. The workbook
# =========================================================================================
TEXT = {'entry_key': str, 'instance_id': str, 'entry_num': str, 'station': str, 'entry_year': str,
        'taxpayer_tin': str, 'consignee_tin': str, 'apcs': str, 'epcs': str, 'watchlist_apcs': str,
        'lowest_price_hs_code': str, 'lowest_duty_hs_code': str, 'hs_code': str, 'apc': str, 'item': str}


def _read(pattern):
    files = sorted(glob.glob(str(DATA / pattern)))
    parts = []
    for f in files:
        d = pd.read_csv(f, dtype=TEXT, low_memory=False)
        d.columns = [c.split('.')[-1].lower() for c in d.columns]
        if len(d) and len(d) % HUE_CAP == 0:
            raise SystemExit(f'{Path(f).name} has exactly {len(d):,} rows: Hue cut the download. Use the per-month '
                             f'queries in sql/pca/if_too_big/ for this one.')
        parts.append(d)
    return pd.concat(parts, ignore_index=True) if parts else None


def load_entries():
    """Every entry since July, with its signals, strength and the taxpayer's profile; None if not downloaded."""
    print('reading the downloads in data/pca/ ...')
    e = _read('entries_*.csv')
    if e is None:
        return None
    e = e.drop_duplicates('entry_key', keep='last')
    for c in ['lowest_price_vs_peers', 'lowest_duty_vs_peers', 'tax_at_stake', 'value_gap', 'duty_gap',
              'items_under_half_peer_price', 'items_50_80_pct_of_peer_price', 'items_possible_unit_error',
              'items_under_half_peer_duty', 'items_claiming_preference', 'same_day_same_hs_declarations',
              'same_day_norm_for_goods', 'value_under_exemption', 'customs_value']:
        e[c] = pd.to_numeric(e[c], errors='coerce')
    raw = e['taxpayer_nm'].fillna('').astype(str)                       # the view's name field carries the address
    e['taxpayer_nm'] = raw.str.split('\n').str[0].str.strip()
    e['taxpayer_address'] = raw.map(_address)
    e = _unit_check(e, load_items())
    e['signals'] = _signals_all(e)
    e['signal_count'] = e['signals'].str.count('; ') + (e['signals'] != '').astype(int)
    e['strength'] = np.select(
        [(e['items_under_half_peer_price'] > 0) | (e['items_under_half_peer_duty'] > 0),
         (e['items_50_80_pct_of_peer_price'] > 0) | (e['signal_count'] >= 2),
         e['signal_count'] >= 1],
        ['Strong', 'Some', 'Weak'], 'None')
    order = {'Strong': 0, 'Some': 1, 'Weak': 2, 'None': 3}
    e['_o'] = e['strength'].map(order)
    e = e.sort_values(['_o', 'tax_at_stake'], ascending=[True, False]).drop(columns='_o')
    e.insert(0, 'rank', range(1, len(e) + 1))
    print('adding each taxpayer\'s risk profile from the scores workbook ...')
    return e.merge(_profile(), on='taxpayer_tin', how='left')


UNIT_CHECK = 0.10    # under 10% of the peer price: a unit or keying error is more likely than undervaluation


def _address(raw):
    """The address lines after the name, tidied: 'KAMPALA  KAMPALA CENTRAL DIVI  KAMPALA CENTRAL DIVISION' style
    repeats, cut-off words and lone numbers removed, the rest joined with commas."""
    import re
    parts = [p.strip() for line in str(raw).split('\n')[1:] for p in re.split(r'\s{2,}', line)]
    parts = [p for p in parts if p and not p.isdigit()]
    keep = []
    for p in parts:
        if any(p != q and q.startswith(p) or (p != q and p in q) for q in parts):
            continue                                  # contained in a fuller part
        if p not in keep:
            keep.append(p)
    return ', '.join(keep).title()


def _unit_check(e, items):
    """Items priced under 10% of peers are more likely a weight or quantity keyed in the wrong unit than undervaluation
    (as in the missed-revenue workbook). The queries mark only those under 1%; this moves the 1-10% items to "check
    units" too and takes their tax at stake out of the entry's total, using the item download."""
    if items is None or not len(items):
        return e
    i = items.copy()
    i['price_vs_peers'] = pd.to_numeric(i['price_vs_peers'], errors='coerce')
    i['tax_at_stake'] = pd.to_numeric(i['tax_at_stake'], errors='coerce').fillna(0)
    moved = i[(i['price_signal'] == 'Under half the peer price') & (i['price_vs_peers'] < UNIT_CHECK)]
    still_low = i[(i['price_signal'] == 'Under half the peer price') & (i['price_vs_peers'] >= UNIT_CHECK)]
    g = moved.groupby('entry_key')
    n_moved, tax_moved = g.size(), g['tax_at_stake'].sum()
    gap_moved = pd.to_numeric(moved['value_gap'], errors='coerce').groupby(moved['entry_key']).sum()
    k = e['entry_key']
    e['items_under_half_peer_price'] = (e['items_under_half_peer_price'] - k.map(n_moved).fillna(0)).clip(lower=0)
    e['items_possible_unit_error'] = e['items_possible_unit_error'].fillna(0) + k.map(n_moved).fillna(0)
    e['tax_at_stake'] = (e['tax_at_stake'] - k.map(tax_moved).fillna(0)).clip(lower=0)
    e['value_gap'] = (pd.to_numeric(e['value_gap'], errors='coerce') - k.map(gap_moved).fillna(0)).clip(lower=0)
    # the lowest price shown is the lowest one that still counts as undervaluation
    low = still_low.groupby('entry_key')['price_vs_peers'].min()
    has_moved = k.isin(n_moved.index)
    e.loc[has_moved, 'lowest_price_vs_peers'] = k[has_moved].map(low)
    return e


def _signals_all(e):
    """'What we saw' for every entry at once (row by row is far too slow on several hundred thousand entries)."""
    def pct(x):
        return (x * 100).round().astype('Int64').astype(str) + '%'

    def text(cond, words):
        return pd.Series(np.where(cond, words, ''), index=e.index)

    lp = e['lowest_price_vs_peers']
    watch = e['watchlist_apcs'].fillna('').astype(str).str.strip()
    n, norm = e['same_day_same_hs_declarations'], e['same_day_norm_for_goods']
    parts = [
        text(e['items_under_half_peer_price'] > 0, 'price ' + pct(lp) + ' of peers'),
        text((e['items_under_half_peer_price'].fillna(0) == 0) & (e['items_50_80_pct_of_peer_price'] > 0),
             'price ' + pct(lp) + ' of peers (some)'),
        text(e['items_possible_unit_error'] > 0, 'check units (price under 10% of peers)'),
        text(e['items_under_half_peer_duty'] > 0, 'duty ' + pct(e['lowest_duty_vs_peers']) + ' of the peer rate'),
        text(watch != '', 'watchlist APC ' + watch),
        text(e['items_claiming_preference'] > 0, 'preference claimed'),
        text((n >= 3) & (norm.isna() | (norm < 0.5)),
             n.fillna(0).astype(int).astype(str) + ' same-day declarations of the same goods'),
        text(e['amended'] == 'Y', 'amended'),
        text(e['new_importer'] == 'Y', 'new importer'),
    ]
    out = parts[0]
    for p in parts[1:]:
        out = out.where(p == '', np.where(out == '', p, out + '; ' + p))
    return out


def _signals(r):
    """The same for one entry (used by the tests)."""
    return _signals_all(pd.DataFrame([r])).iloc[0]


def _profile():
    """Each taxpayer's bands and reasons from the live scores workbook (blank if not scored)."""
    path = RESULTS_DIR / f'CTRP_scores_{E.LIVE_SNAPSHOT}.xlsx'
    cols = ['TIN', 'History Risk Score', 'History Risk Band', 'Overall Risk Band', 'Risky Behaviour Flag', 'Reason 1',
            'Behaviour reason 1', 'Limited history (under 10 declarations)']
    if not path.exists():
        return pd.DataFrame(columns=['taxpayer_tin'])
    s = pd.read_excel(path, sheet_name='Scores', dtype={'TIN': str})
    s = s[[c for c in cols if c in s]].rename(columns={'TIN': 'taxpayer_tin'})
    return s


def load_items():
    i = _read('items.csv')
    if i is None:
        i = _read('items_*.csv')
    return i


ENTRY_COLUMNS = {
    'rank': 'Rank', 'strength': 'Evidence strength', 'signals': 'What we saw', 'tax_at_stake': 'Tax at stake, UGX (estimate)',
    'entry_key': 'Entry key', 'entry_num': 'Entry number', 'station': 'Station', 'entry_year': 'Year',
    'instance_id': 'Declaration ID', 'assessed_on': 'Assessed on', 'taxpayer_tin': 'TIN', 'taxpayer_nm': 'Taxpayer',
    'consignee_tin': 'Consignee TIN', 'consignee_nm': 'Consignee', 'regime': 'Regime', 'lane': 'Lane',
    'status': 'Status', 'pay_status': 'Payment', 'topped_up': 'Topped up', 'tax_raised': 'Tax raised, UGX',
    'amended': 'Amended', 'items': 'Items', 'customs_value': 'Customs value, UGX', 'tax_assessed': 'Tax assessed, UGX',
    'apcs': 'APCs', 'epcs': 'EPCs',
    'lowest_price_vs_peers': 'Lowest price as % of peers', 'lowest_price_hs_code': 'HS code (lowest price)',
    'lowest_price_origin': 'Origin (lowest price)', 'lowest_price_per_kg': 'Price per kg, UGX',
    'peer_price_per_kg': 'Peer price per kg, UGX', 'lowest_price_per_unit': 'Price per unit, UGX',
    'peer_price_per_unit': 'Peer price per unit, UGX', 'peer_basis': 'Peers compared on',
    'peer_importers': 'Peer importers', 'items_under_half_peer_price': 'Items under half the peer price',
    'items_50_80_pct_of_peer_price': 'Items at 50-80% of the peer price', 'items_possible_unit_error': 'Items: check units',
    'value_gap': 'Value gap, UGX', 'lowest_duty_vs_peers': 'Lowest duty rate as % of peers',
    'lowest_duty_hs_code': 'HS code (lowest duty)', 'lowest_duty_rate': 'Duty rate', 'peer_duty_rate': 'Peer duty rate',
    'items_under_half_peer_duty': 'Items under half the peer duty rate', 'duty_gap': 'Duty gap, UGX',
    'value_under_exemption': 'Value under an exemption APC, UGX', 'watchlist_apcs': 'Watchlist APCs',
    'items_claiming_preference': 'Items claiming preference',
    'same_day_same_hs_declarations': 'Same-day declarations, same goods', 'same_day_norm_for_goods': 'Same-day norm for the goods',
    'first_import_in_5_years': 'First import (5 years)', 'new_importer': 'New importer',
}
ITEM_COLUMNS = {
    'entry_key': 'Entry key', 'entry_num': 'Entry number', 'station': 'Station', 'entry_year': 'Year',
    'instance_id': 'Declaration ID', 'assessed_on': 'Assessed on', 'taxpayer_tin': 'TIN', 'item': 'Item',
    'hs_code': 'HS code', 'origin': 'Origin', 'apc': 'APC', 'preference': 'Preference', 'price_signal': 'Price signal',
    'duty_signal': 'Duty signal', 'customs_value': 'Customs value, UGX', 'net_weight': 'Net weight, kg',
    'quantity': 'Quantity', 'tax_assessed': 'Tax assessed, UGX', 'price_kg': 'Price per kg, UGX',
    'peer_kg': 'Peer price per kg, UGX', 'price_vs_peers': 'Price as % of peers', 'price_unit': 'Price per unit, UGX',
    'peer_unit': 'Peer price per unit, UGX', 'unit_price_vs_peers': 'Unit price as % of peers',
    'peer_basis': 'Peers compared on', 'peer_importers': 'Peer importers', 'value_gap': 'Value gap, UGX',
    'duty_rate': 'Duty rate', 'peer_duty_rate': 'Peer duty rate', 'duty_vs_peers': 'Duty rate as % of peers',
    'duty_gap': 'Duty gap, UGX', 'tax_at_stake': 'Tax at stake, UGX (estimate)'}
PROFILE_COLUMNS = ['History Risk Score', 'History Risk Band', 'Overall Risk Band', 'Risky Behaviour Flag', 'Reason 1',
                   'Behaviour reason 1']
PCT = {'Lowest price as % of peers', 'Lowest duty rate as % of peers', 'Duty rate', 'Peer duty rate',
       'Same-day norm for the goods', 'Price as % of peers', 'Unit price as % of peers', 'Duty rate as % of peers'}

READ_ME = [
    ('What this is', 'Every IM4 and IM7 entry assessed since 1 July 2026, in every lane, checked against what other '
     'importers declare for the same goods. For Post Clearance Audit and the National Targeting Centre.'),
    ('Rules', 'As in the risk model: no cancelled declarations, 10-digit TINs, no APC 483, the latest declaration ID of '
     'each entry, no motor vehicle declarations (HS 8701 to 8708, 8711), each item once.'),
    ('Peers', 'All importers of the same HS code (and origin, where 5 or more importers bring it from there) in the 24 '
     'months before 1 July 2026. A comparison is only made when 5 or more importers bring the goods.'),
    ('Evidence strength', 'Strong: an item priced under half the peer price, or an item with no exemption paying under '
     'half the peer duty rate. Some: an item at 50-80% of the peer price, or two or more other signals. Weak: one other '
     'signal. Entries with no signal are counted on the Summary only.'),
    ('Order', 'Strongest evidence first, then the most tax at stake.'),
    ('Tax at stake', 'For a low-priced item: the value gap to the peer price x the item\'s own tax rate (at most 100%). '
     'Otherwise, for a low-duty item: the duty gap to the peer rate. Each item counted once. A screening estimate to be '
     'checked, not a finding: a low price can be legitimate.'),
    ('Check units', 'A price under 10% of peers is more likely a weight or quantity keyed in the wrong unit. Shown, but '
     'not counted as undervaluation or in the tax at stake (as in the missed-revenue workbook).'),
    ('Lane', 'Red and yellow entries were checked. A strong signal on a checked entry that was not topped up means the '
     'check accepted the price, or missed it: both are worth a look.'),
    ('Taxpayer profile', 'The taxpayer\'s History Risk Band, Overall Risk Band and Risky Behaviour Flag at 30 '
     'September 2026, from the live risk profile.'),
    ('Sheets', 'Summary, Entries (one row per entry with a signal), Items (the items behind the price and duty '
     'signals, with the peer values), Taxpayers, Column guide. Entries lists strong and some evidence; entries with one weak signal are counted on the Summary.'),
    ('Note', 'Contains TINs and names: internal use only. Prepared by Data Science (ITID).'),
]


def build(out=None):
    e = load_entries()
    if e is None:
        raise SystemExit('No downloads in data/pca/. Run python main.py pca --sql, then the queries in sql/pca/.')
    items = load_items()
    print(f'{len(e):,} entries read; summarising')
    e['_flag'] = (e['strength'] != 'None').astype(int)
    e['_strong'] = (e['strength'] == 'Strong').astype(int)
    e['_topped'] = (e['topped_up'] == 'Y').astype(int)
    flagged = e[e['_flag'] == 1]
    tp = flagged.groupby('taxpayer_tin').agg(taxpayer=('taxpayer_nm', 'first'), entries=('entry_key', 'size'),
                                            strong=('_strong', 'sum'), tax_at_stake=('tax_at_stake', 'sum'))
    for c in ['History Risk Band', 'Overall Risk Band', 'Risky Behaviour Flag']:
        tp[c] = flagged.groupby('taxpayer_tin')[c].first() if c in flagged else ''
    tp = tp.sort_values('tax_at_stake', ascending=False).reset_index()
    tp.columns = ['TIN', 'Taxpayer', 'Entries with a signal', 'Strong', 'Tax at stake, UGX (estimate)',
                  'History Risk Band', 'Overall Risk Band', 'Risky Behaviour Flag']

    by_lane = e.groupby('lane').agg(entries=('entry_key', 'size'), with_signal=('_flag', 'sum'),
                                    strong=('_strong', 'sum'), topped_up=('_topped', 'sum'),
                                    tax_at_stake=('tax_at_stake', 'sum')).reset_index()
    by_lane.columns = ['Lane', 'Entries', 'With a signal', 'Strong', 'Topped up', 'Tax at stake, UGX (estimate)']
    strong = e[e['_strong'] == 1]
    summary = pd.DataFrame([
        ['Entries since 1 July 2026', len(e)],
        ['Entries with a signal', len(flagged)],
        ['  of which strong', len(strong)],
        ['  of which some', int((flagged['strength'] == 'Some').sum())],
        ['  of which weak (one soft signal only, e.g. amended or new importer; not listed)', int((flagged['strength'] == 'Weak').sum())],
        ['  strong and not topped up', int((strong['topped_up'] == 'N').sum())],
        ['  strong, checked (red or yellow) and not topped up',
         int(((strong['topped_up'] == 'N') & strong['lane'].isin(['Red', 'Yellow'])).sum())],
        ['Taxpayers with a signal', flagged['taxpayer_tin'].nunique()],
        ['Tax at stake on strong entries not topped up, UGX (estimate)',
         float(strong.loc[strong['topped_up'] == 'N', 'tax_at_stake'].sum())],
    ], columns=['Measure', 'Value'])

    listed = flagged[flagged['strength'].isin(['Strong', 'Some'])]
    cols = list(ENTRY_COLUMNS) + [c for c in PROFILE_COLUMNS if c in listed]
    entries = listed[[c for c in cols if c in listed]].rename(columns=ENTRY_COLUMNS)
    sheets = {'Read me': pd.DataFrame(READ_ME, columns=['Item', 'Detail']),
              'Summary': summary, 'By lane': by_lane, 'Entries': entries}
    if items is not None:
        keep = items['entry_key'].isin(listed['entry_key'])
        sheets['Items'] = items[keep][[c for c in ITEM_COLUMNS if c in items]].rename(columns=ITEM_COLUMNS)
    sheets['Taxpayers'] = tp
    sheets['Column guide'] = pd.DataFrame(
        [[v, k] for k, v in {**ENTRY_COLUMNS, **ITEM_COLUMNS}.items()], columns=['Column', 'Field in the query'])
    out = Path(out or RESULTS_DIR / f'CTRP_post_clearance_audit_{pd.Timestamp.today():%Y-%m-%d}.xlsx')
    print(f'writing {out.name} ({len(entries):,} entries with a signal)...')
    _write(out, sheets)
    print(f'{len(e):,} entries since July, {len(flagged):,} with a signal ({len(strong):,} strong), '
          f'{flagged["taxpayer_tin"].nunique():,} taxpayers. Written {out}')
    return out


def _write(path, sheets):
    """xlsxwriter in constant-memory mode: each row goes to disk as it is written, so a workbook of several hundred
    thousand rows needs little memory (openpyxl keeps every cell in memory and can crash the machine)."""
    import xlsxwriter
    book = xlsxwriter.Workbook(str(path), {'constant_memory': True, 'nan_inf_to_errors': True})
    head = book.add_format({'bold': True, 'font_color': 'white', 'bg_color': '#102A83', 'text_wrap': True,
                            'valign': 'top'})
    money, pct = book.add_format({'num_format': '#,##0'}), book.add_format({'num_format': '0%'})
    wrap = book.add_format({'text_wrap': True, 'valign': 'top'})
    for name, df in sheets.items():
        ws = book.add_worksheet(name)
        ws.freeze_panes(1, 0)
        fmts = []
        for j, col in enumerate(df.columns):
            if name == 'Read me' and j == 1:
                ws.set_column(j, j, 110, wrap)
                fmts.append(wrap)
                continue
            fmt = pct if col in PCT else money if ('UGX' in str(col) or col == 'Value') else None
            ws.set_column(j, j, min(max(12, len(str(col)) + 2), 40), fmt)
            fmts.append(fmt)
        ws.write_row(0, 0, list(df.columns), head)
        for i, row in enumerate(df.itertuples(index=False, name=None), start=1):
            for j, v in enumerate(row):
                if v is None or (isinstance(v, float) and v != v):
                    continue                                   # blank cell
                if hasattr(v, 'item'):
                    v = v.item()
                ws.write(i, j, v, fmts[j]) if fmts[j] is not None else ws.write(i, j, v)
    book.close()
