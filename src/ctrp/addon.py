"""
Long-run add-on: the candidate parameters from the NTC and eHub lists that the view supports but the
long run does not yet carry. One row per taxpayer per half-year, counts that add up, like the long run,
so every candidate can be tested on the same 18 dates.

What it adds (all from columns already in the view):
  - Sensitive goods (NTC "Nature of imports"; PAR_026 to PAR_028): value and declarations with an item on
    the EAC CET 2022 Sensitive Items list (50 tariff lines: milk, rice, maize, sugar, wheat flour,
    certain fabrics and garments).
  - Depth of exemption (NTC "Nature of APCs": all taxes or one tax head; PAR_052, PAR_053): value under an
    exemption APC with no tax at all, value with some tax, and the tax relief = what the item would pay at
    the normal rate for its tariff line (tax over value of items with no exemption, APC 000) minus what it
    paid.
  - Origin and goods risk (NTC "Origin of goods"; PAR_062, PAR_083, PAR_089): for each item, the share of
    checks that found a top-up among OTHER taxpayers' checks of the same origin and HS chapter in the same
    half-year (smoothed towards the overall rate when there were few checks). Added up as value x rate,
    so the snapshot gets a value-weighted average. Measured from the record, not from a
    fixed list of countries; NTC's list is carried too (value from their 10-point and 5-point origins).
  - Top-ups split by regime (lane targeting "IM4 ratio" and "IM7 ratio"; PAR_048 at IM4 and IM7):
    original tax, top-ups, checks and hits for IM4 and IM7 separately.
Why:  these need item-level work the long run skips. Counting them per half-year keeps one query per year
      and lets Python build any snapshot by adding half-years, as for the long run (DECISIONS 87).
Speed: each piece reads one year (Oct to Sep), like a long-run piece, with no window functions and no
      percentiles. The first version read three years per piece and sorted them for rolling windows: it
      ran over 30 minutes in Hue.
Leakage: every half-year used for a snapshot ends on or before the snapshot date, so no snapshot sees its
      own outcome window. The origin rate leaves out the taxpayer's own checks, so its own top-ups (already
      in Track A) are not counted twice.

    python main.py sql --addon        -> sql/long_run_addon/addon_<year>.sql (one per year, 2016 to 2026)
    save results as data/long_run_addon/addon_<year>.csv, then: python main.py candidates
"""
import pandas as pd

from ctrp import extract as E
from ctrp import longrun as LR
from ctrp.utils import DATA_DIR, SQL_DIR, TEMPLATE_SQL

ADDON_SQL = SQL_DIR / 'long_run_addon'
ADDON_DATA = DATA_DIR / 'long_run_addon'
YEARS = range(2016, 2027)          # pieces Oct (y-1) to Sep y; 2016 onwards covers the Sep 2017 snapshot

# EAC CET 2022 (June 2025 update), lines marked SI (Sensitive Items), first 8 digits
SENSITIVE_HS8 = ('04011000,04012000,04014000,04015000,04021000,04022100,04022900,04029100,04029900,04032000,'
                 '04039000,04061000,04062000,04063000,04064000,04069000,10059000,10061000,10062000,10063000,'
                 '10064000,11010000,11022000,11029010,17011210,17011290,17011310,17011390,17011410,17011490,'
                 '17019100,17019910,17019920,17019990,52085110,52085210,52095110,52105110,52115110,52121510,'
                 '52122510,55134110,55144110,62114210,62114310,62114910,63022100,63023100,63025100,63029100').split(',')

# NTC Business Risk scorecard, "Origin of goods": Egypt, Asia, UAE, North Korea, India, UK = 10;
# EAC, COMESA and other trading blocs = 5; others = 0 (ISO 2-letter codes, as in the view)
NTC_ORIGIN_10 = ('EG,GB,AE,KP,IN,AF,AM,AZ,BH,BD,BT,BN,KH,CN,CY,GE,HK,ID,IR,IQ,IL,JP,JO,KZ,KW,KG,LA,LB,MO,MY,MV,'
                 'MN,MM,NP,OM,PK,PS,PH,QA,SA,SG,KR,LK,SY,TW,TJ,TH,TL,TR,TM,UZ,VN,YE').split(',')
NTC_ORIGIN_5 = ('KE,TZ,RW,BI,SS,CD,SO,UG,KM,DJ,ER,SZ,ET,LY,MG,MW,MU,SC,SD,TN,ZM,ZW,AO,BW,LS,MZ,NA,ZA').split(',')
SMOOTH_CHECKS = 30                 # an origin x chapter with few other checks leans on the overall rate


def _q(codes):
    """A list of codes as SQL text: 'a', 'b', 'c'."""
    return ', '.join(f"'{c}'" for c in codes)


def _h(col):
    """Half-year number: Oct (y-1) to Mar y -> 2y; Apr to Sep y -> 2y + 1."""
    month, year = f"CAST(substr({col}, 5, 2) AS INT)", f"CAST(substr({col}, 1, 4) AS INT)"
    return (f"CASE WHEN {month} BETWEEN 4 AND 9 THEN {year} * 2 + 1 "
            f"WHEN {month} >= 10 THEN ({year} + 1) * 2 "
            f"ELSE {year} * 2 END")


# The add-on itself, after the template's cleaned items and declarations (raw, items, decl_all, decl).
# Kept exactly as run in Hue: the long SQL lines are left as they are.
BODY = """
-- ---------- items with their declaration's lane and outcome (this piece's year only) -----
half_items AS (
  SELECT i.instance_id, i.taxpayer_tin AS tin, i.cpc_cd, substr(i.hsc_cd, 1, 8) AS hs8,
         substr(i.hsc_cd, 1, 2) AS ch, COALESCE(i.gds_org_cty, '??') AS org,
         i.customs_value AS value, i.tax_assessed AS tax,
         @@H_ITEM@@ AS h,
         CASE WHEN d.red = 1 OR d.yellow = 1 THEN 1 ELSE 0 END                         AS chk,
         CASE WHEN (d.red = 1 OR d.yellow = 1) AND d.topped_up = 1 THEN 1 ELSE 0 END   AS hit,
         CASE WHEN substr(i.hsc_cd, 1, 8) IN (@@SENSITIVE@@) THEN 1 ELSE 0 END          AS sens,
         CASE WHEN COALESCE(i.gds_org_cty, '') IN (@@NTC10@@) THEN 10
              WHEN COALESCE(i.gds_org_cty, '') IN (@@NTC5@@) THEN 5 ELSE 0 END          AS ntc_org
  FROM items i
  JOIN decl d ON i.instance_id = d.instance_id
  WHERE i.customs_value > 0
),

-- normal tax rate per tariff line: tax over value of items with no exemption (APC 000)
hs_rate AS (
  SELECT hs8, SUM(tax) / SUM(value) AS normal_rate
  FROM half_items
  WHERE cpc_cd = '000' AND tax >= 0
  GROUP BY hs8
  HAVING COUNT(*) >= 20
),

-- origin x HS chapter record in the same half-year, OTHER taxpayers only (the taxpayer's own
-- checks are taken out, so its own top-ups never feed this measure)
own AS (
  SELECT tin, org, ch, h, SUM(chk) AS own_checked, SUM(hit) AS own_hits, SUM(value) AS v
  FROM half_items GROUP BY tin, org, ch, h
),
og AS (
  SELECT org, ch, h, SUM(chk) AS checked, SUM(hit) AS hits FROM half_items GROUP BY org, ch, h
),
gl AS (
  SELECT h, SUM(hit) / SUM(chk) AS g_rate FROM half_items GROUP BY h
),
orig AS (
  SELECT o.tin, o.h,
         SUM(o.v * (g.hits - o.own_hits + @@SMOOTH@@ * l.g_rate)
                 / (g.checked - o.own_checked + @@SMOOTH@@))                           AS value_x_origin_rate,
         SUM(o.v)                                                                      AS value_with_origin_rate
  FROM own o
  JOIN og g ON o.org = g.org AND o.ch = g.ch AND o.h = g.h
  JOIN gl l ON o.h = l.h
  GROUP BY o.tin, o.h
),

itm AS (
  SELECT x.tin, x.h,
         SUM(x.value)                                                                    AS item_value_ugx,
         SUM(CASE WHEN x.sens = 1 THEN x.value ELSE 0 END)                               AS sensitive_value_ugx,
         COUNT(DISTINCT CASE WHEN x.sens = 1 THEN x.instance_id END)                      AS sensitive_entries,
         SUM(CASE WHEN x.cpc_cd <> '000' THEN x.value ELSE 0 END)                        AS exempt_apc_value_ugx,
         SUM(CASE WHEN x.cpc_cd <> '000' AND x.tax <= 0.005 * x.value THEN x.value ELSE 0 END) AS full_exempt_value_ugx,
         SUM(CASE WHEN x.cpc_cd <> '000' AND x.tax >  0.005 * x.value THEN x.value ELSE 0 END) AS partial_exempt_value_ugx,
         SUM(CASE WHEN x.cpc_cd <> '000' AND r.normal_rate IS NOT NULL
                  THEN GREATEST(r.normal_rate * x.value - x.tax, 0) ELSE 0 END)          AS tax_relief_ugx,
         SUM(CASE WHEN r.normal_rate IS NOT NULL THEN r.normal_rate * x.value ELSE 0 END) AS normal_tax_ugx,
         SUM(CASE WHEN x.ntc_org = 10 THEN x.value ELSE 0 END)                           AS ntc_origin10_value_ugx,
         SUM(CASE WHEN x.ntc_org = 5 THEN x.value ELSE 0 END)                            AS ntc_origin5_value_ugx
  FROM half_items x
  LEFT JOIN hs_rate r ON x.hs8 = r.hs8
  GROUP BY x.tin, x.h
),

-- ---------- top-ups by regime, per declaration -------------------------------------------
reg AS (
  SELECT tin, @@H_DECL@@ AS h,
         SUM(CASE WHEN regime = 'IM4' THEN orig_tax ELSE 0 END)                                AS im4_original_tax_ugx,
         SUM(CASE WHEN regime = 'IM4' THEN top_up ELSE 0 END)                                  AS im4_top_up_ugx,
         SUM(CASE WHEN regime = 'IM4' AND (red = 1 OR yellow = 1) THEN 1 ELSE 0 END)            AS im4_checked,
         SUM(CASE WHEN regime = 'IM4' AND (red = 1 OR yellow = 1) AND topped_up = 1 THEN 1 ELSE 0 END) AS im4_hits,
         SUM(CASE WHEN regime = 'IM7' THEN orig_tax ELSE 0 END)                                AS im7_original_tax_ugx,
         SUM(CASE WHEN regime = 'IM7' THEN top_up ELSE 0 END)                                  AS im7_top_up_ugx,
         SUM(CASE WHEN regime = 'IM7' AND (red = 1 OR yellow = 1) THEN 1 ELSE 0 END)            AS im7_checked,
         SUM(CASE WHEN regime = 'IM7' AND (red = 1 OR yellow = 1) AND topped_up = 1 THEN 1 ELSE 0 END) AS im7_hits
  FROM decl
  GROUP BY tin, @@H_DECL@@
)

SELECT r.tin AS taxpayer_tin,
       CASE WHEN r.h % 2 = 1 THEN concat(CAST(CAST((r.h - 1) / 2 AS INT) AS STRING), '-09-30')
            ELSE concat(CAST(CAST(r.h / 2 AS INT) AS STRING), '-03-31') END AS period_end,
       r.im4_original_tax_ugx, r.im4_top_up_ugx, r.im4_checked, r.im4_hits,
       r.im7_original_tax_ugx, r.im7_top_up_ugx, r.im7_checked, r.im7_hits,
       m.item_value_ugx, m.sensitive_value_ugx, m.sensitive_entries,
       m.exempt_apc_value_ugx, m.full_exempt_value_ugx, m.partial_exempt_value_ugx,
       m.tax_relief_ugx, m.normal_tax_ugx, o.value_x_origin_rate, o.value_with_origin_rate,
       m.ntc_origin10_value_ugx, m.ntc_origin5_value_ugx
FROM reg r
LEFT JOIN itm m  ON r.tin = m.tin AND r.h = m.h
LEFT JOIN orig o ON r.tin = o.tin AND r.h = o.h
"""


def render(year):
    """Query for one piece: half-years ending Mar `year` and Sep `year`, reading that year only
    (Oct year-1 to Sep year), the same window as a long-run piece."""
    _, ctes, _, _ = E._parse_template(E.apply_apc_483(TEMPLATE_SQL.read_text()))
    w = ',\n\n'.join(ctes[n] for n in ['raw', 'items', 'decl_all', 'decl'])
    w = w.replace("'@@HIST3_START@@'", f"'{year - 1}0930'").replace("'@@OUT_END@@'", f"'{year}0930'")
    body = BODY
    for key, value in {'@@H_ITEM@@': _h('i.assessment_dt_wid'), '@@H_DECL@@': _h('dt'),
                       '@@SENSITIVE@@': _q(SENSITIVE_HS8), '@@NTC10@@': _q(NTC_ORIGIN_10),
                       '@@NTC5@@': _q(NTC_ORIGIN_5), '@@SMOOTH@@': str(SMOOTH_CHECKS)}.items():
        body = body.replace(key, value)
    if '@@' in w + body:
        raise ValueError('a placeholder was left unfilled')
    head = (f'-- =====================================================================================\n'
            f'-- CTRP LONG-RUN ADD-ON, piece {year}: half-years ending 31 Mar {year} and 30 Sep {year}.\n'
            f'-- Candidate parameters from the NTC and eHub lists (sensitive goods, depth of exemption,\n'
            f'-- origin and goods record, top-ups by regime). One row per taxpayer per half-year.\n'
            f'-- Run as ONE statement, download as CSV, save as data/long_run_addon/addon_{year}.csv\n'
            f'-- GENERATED by: python main.py sql --addon   (src/ctrp/addon.py explains every column)\n'
            f'-- =====================================================================================\n')
    sql = head + 'WITH ' + w + ',\n' + body
    if ';' in sql:
        raise ValueError("a semicolon would break Hue's statement split")
    return sql


def write_queries():
    """One query file per year in sql/long_run_addon/."""
    ADDON_SQL.mkdir(parents=True, exist_ok=True)
    for y in YEARS:
        (ADDON_SQL / f'addon_{y}.sql').write_text(render(y))
    print(f'written sql/long_run_addon/addon_{YEARS[0]}.sql ... addon_{YEARS[-1]}.sql ({len(YEARS)} pieces)')


# =========================================================================================
# Building the candidate columns for a snapshot
# =========================================================================================
SUMS = ['im4_original_tax_ugx', 'im4_top_up_ugx', 'im4_checked', 'im4_hits', 'im7_original_tax_ugx',
        'im7_top_up_ugx', 'im7_checked', 'im7_hits', 'item_value_ugx', 'sensitive_value_ugx', 'sensitive_entries',
        'exempt_apc_value_ugx', 'full_exempt_value_ugx', 'partial_exempt_value_ugx', 'tax_relief_ugx',
        'normal_tax_ugx', 'value_x_origin_rate', 'value_with_origin_rate', 'ntc_origin10_value_ugx',
        'ntc_origin5_value_ugx']


def load():
    """Every downloaded piece as one table (one row per taxpayer per half-year), or None if none yet."""
    files = sorted(ADDON_DATA.glob('addon_*.csv'))
    if not files:
        return None
    parts = []
    for f in files:
        p = pd.read_csv(f, dtype={'taxpayer_tin': str, 'period_end': str})
        if len(p) % LR.HUE_ROW_CAP == 0:
            raise SystemExit(f'{f.name} has exactly {len(p):,} rows: Hue cut the download.')
        parts.append(p)
    p = pd.concat(parts)
    p.columns = [c.split('.')[-1].lower() for c in p.columns]
    return p.drop_duplicates(['taxpayer_tin', 'period_end'])


def _ratio(numerator, denominator):
    """numerator / denominator, blank where the denominator is not above 0."""
    return numerator / denominator.where(denominator > 0)


def features(panel, snap):
    """Candidate columns for one snapshot (24 months of half-years), indexed by TIN."""
    g = panel[panel['period_end'].isin(LR._periods(snap, 24))].groupby('taxpayer_tin')[SUMS].sum()
    v = g['item_value_ugx'].where(g['item_value_ugx'] > 0)
    # value with no exemption, a partial one, or a full one: the largest decides the NTC "Nature of APCs" points
    shares = pd.DataFrame({'none': g['item_value_ugx'] - g['exempt_apc_value_ugx'],
                           'partial': g['partial_exempt_value_ugx'],
                           'full': g['full_exempt_value_ugx']}).fillna(0)
    # value by NTC origin group (10, 5 or 0 points): the largest decides the "Origin of goods" points
    origin = pd.DataFrame({'o0': g['item_value_ugx'] - g['ntc_origin10_value_ugx'] - g['ntc_origin5_value_ugx'],
                           'o10': g['ntc_origin10_value_ugx'],
                           'o5': g['ntc_origin5_value_ugx']}).fillna(0)
    return pd.DataFrame({
        'cand_sensitive_share': g['sensitive_value_ugx'] / v,
        'cand_full_exempt_share': g['full_exempt_value_ugx'] / v,
        'cand_partial_exempt_share': g['partial_exempt_value_ugx'] / v,
        'cand_relief_share': _ratio(g['tax_relief_ugx'], g['normal_tax_ugx']),
        'cand_origin_goods_rate': _ratio(g['value_x_origin_rate'], g['value_with_origin_rate']),
        'cand_ntc_origin_share': g['ntc_origin10_value_ugx'] / v,
        'cand_im4_top_up_ratio': _ratio(g['im4_top_up_ugx'], g['im4_original_tax_ugx']),
        'cand_im7_top_up_ratio': _ratio(g['im7_top_up_ugx'], g['im7_original_tax_ugx']),
        # NTC scorecard rows, on the taxpayer's main category by value
        'ntc_nature_points': (g['sensitive_value_ugx'] / v >= 0.5).astype(float) * 5,
        'ntc_apc_points': shares.idxmax(axis=1).map({'full': 10, 'partial': 5, 'none': 0}).astype(float),
        'ntc_origin_points': origin.idxmax(axis=1).map({'o10': 10, 'o5': 5, 'o0': 0}).astype(float),
    })
