-- PART "items" of a split extract (goods, origins and PAR_076 prices).
-- Run in Hue as ONE statement, download as CSV and save it as
--   data/split/items_bt_2019-03-31.csv
-- then, when all four parts are saved:  python main.py merge
-- Cut by the code from the full query sql/bt_2019-03-31.sql: same cleaning rules,
-- same dates, so the merged file matches what the full query gives.

WITH -- What: item rows in the window, cleaned (rules R1 to R13), each item numbered once.
-- Why:  the view repeats some items many times, so duplicates must go before any count.
raw AS (
  -- only the 24 columns the model uses, so Spark moves far less data in every step
  SELECT v.instance_id, v.key_itm_nbr, v.assessment_dt_wid, v.taxpayer_tin,
         v.regime_cd, v.decl_status, v.cpc_cd, v.extended_proc_cd,
         v.hsc_cd, v.gds_org_cty, v.customs_value, v.net_weight,
         v.supplementary_qnty, v.tax_assessed, v.original_tax_amt, v.final_amt,
         v.top_up_flg, v.amendment_flg, v.clearance_station_cd, v.is_red_flg,
         v.is_yellow_flg, v.pay_status, v.consignee_tin, v.preferential_treatment_flag,
         v.entry_num, v.dec_ref_yer,
         ROW_NUMBER() OVER (PARTITION BY v.instance_id, v.key_itm_nbr ORDER BY v.assessment_dt_wid) AS rn,
         -- R14 entry key = entry number + station + year (e.g. C12345UGKLA2026). One entry can sit under
         --     more than one declaration ID, and only its latest declaration ID (the highest) is kept.
         MAX(lpad(v.instance_id, 20, '0')) OVER (PARTITION BY COALESCE(concat(v.entry_num, v.clearance_station_cd,
             v.dec_ref_yer), v.instance_id))                                              AS latest_instance,
         -- R15 motor vehicles: a declaration with any motor vehicle item is left out (separate MV model)
         MAX(CASE WHEN substr(v.hsc_cd, 1, 4) IN ('8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711') THEN 1 ELSE 0 END)
             OVER (PARTITION BY v.instance_id)                                            AS has_vehicle
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid >  '20170331'
    AND v.assessment_dt_wid <= '20190331'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND v.decl_status <> 'Cancelled'
    AND v.taxpayer_tin RLIKE '^[0-9]{10}$'
    AND COALESCE(v.cpc_cd, '') <> '483'   -- destroyed or abandoned declarations and dummy
                                          -- reconciliation entries (CPC memo), not trade
),

-- What: one row per declaration item (duplicates dropped).
items AS (
  SELECT r.*, to_date(r.assessment_dt_wid, 'yyyyMMdd') AS adate
  FROM raw r
  WHERE r.rn = 1
    AND lpad(r.instance_id, 20, '0') = r.latest_instance   -- R14 latest declaration ID per entry
    AND r.has_vehicle = 0                                   -- R15 no motor vehicle declarations
),

-- What: items in the 24-month history only (features are built from history, never the future).
hist_items AS (
  SELECT * FROM items WHERE assessment_dt_wid > '20170331' AND assessment_dt_wid <= '20190331'
),

-- ---------- structure, for peer segmentation -------------------------------------------
-- What: how each taxpayer trades (goods, origins, CPCs, stations, items per declaration).
-- Why:  used to put taxpayers in peer groups and in the pattern check.
struct AS (
  SELECT taxpayer_tin                                                     AS tin,
         COUNT(DISTINCT substr(hsc_cd, 1, 4))                             AS hs_headings_used,
         COUNT(DISTINCT gds_org_cty)                                      AS origins_used,
         COUNT(DISTINCT cpc_cd)                                           AS cpcs_used,
         AVG(CASE WHEN preferential_treatment_flag = 'Y' THEN 1.0 ELSE 0.0 END)
                                                                          AS ctx_preferential_use_rate
  FROM hist_items
  GROUP BY taxpayer_tin
),

-- What: each taxpayer's main HS chapter (most customs value) and its share of their value.
dom AS (
  SELECT tin, hs_chapter AS dominant_hs_chapter, chapter_value_share
  FROM (
    SELECT taxpayer_tin AS tin,
           substr(hsc_cd, 1, 2) AS hs_chapter,
           SUM(customs_value) / NULLIF(SUM(SUM(customs_value)) OVER (PARTITION BY taxpayer_tin), 0)
                                AS chapter_value_share,
           ROW_NUMBER() OVER (PARTITION BY taxpayer_tin ORDER BY SUM(customs_value) DESC) AS rn
    FROM hist_items
    GROUP BY taxpayer_tin, substr(hsc_cd, 1, 2)
  ) z
  WHERE rn = 1
),

-- ---------- PAR_076 with the interim benchmark -----------------------------------------
-- Benchmark = median unit value for the HS code across all importers (5 or more).
-- Low = below half the median on BOTH bases (per kg alone where no supplementary quantity).
-- Items below 1% of the median are treated as entry errors (a weight or quantity in the
-- wrong unit), counted separately and kept out of the shortfall, so that one keying error
-- cannot make a taxpayer look like the worst undervaluer in the country.
bench AS (
  SELECT hsc_cd,
         percentile_approx(customs_value / net_weight, 0.5)                         AS med_per_kg,
         percentile_approx(CASE WHEN supplementary_qnty > 0
                                THEN customs_value / supplementary_qnty END, 0.5)    AS med_per_unit
  FROM hist_items
  WHERE customs_value > 0 AND net_weight > 0
  GROUP BY hsc_cd
  HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),

-- (5) Benchmark per HS code AND origin where 5+ importers bring that code from that origin,
-- otherwise the HS-wide benchmark above. Goods of one code differ in price by origin.
bench_o AS (
  SELECT hsc_cd, gds_org_cty,
         percentile_approx(customs_value / net_weight, 0.5)                         AS med_per_kg,
         percentile_approx(CASE WHEN supplementary_qnty > 0
                                THEN customs_value / supplementary_qnty END, 0.5)    AS med_per_unit
  FROM hist_items
  WHERE customs_value > 0 AND net_weight > 0
  GROUP BY hsc_cd, gds_org_cty
  HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),

items_b AS (
  SELECT i.*,
         COALESCE(o.med_per_kg, b.med_per_kg)                             AS bm_kg,
         CASE WHEN o.med_per_kg IS NOT NULL THEN o.med_per_unit ELSE b.med_per_unit END AS bm_unit,
         CASE WHEN o.med_per_kg IS NOT NULL THEN 1 ELSE 0 END             AS on_origin_bench
  FROM hist_items i
  JOIN bench b ON i.hsc_cd = b.hsc_cd
  LEFT JOIN bench_o o ON i.hsc_cd = o.hsc_cd AND i.gds_org_cty = o.gds_org_cty
  WHERE i.customs_value > 0 AND i.net_weight > 0
),

val AS (
  SELECT i.taxpayer_tin AS tin,
         i.customs_value,
         i.on_origin_bench,
         -- (6) how far the price per kg sits from peers, either way (log scale)
         ABS(LN((i.customs_value / i.net_weight) / i.bm_kg))              AS price_deviation,
         CASE WHEN i.customs_value / i.net_weight < 0.01 * i.bm_kg THEN 1 ELSE 0 END    AS implausible,
         CASE WHEN i.customs_value / i.net_weight <  0.5 * i.bm_kg
               AND i.customs_value / i.net_weight >= 0.01 * i.bm_kg
               AND (i.bm_unit IS NULL OR i.supplementary_qnty IS NULL OR i.supplementary_qnty <= 0
                    OR i.customs_value / i.supplementary_qnty < 0.5 * i.bm_unit)
              THEN 1 ELSE 0 END                                           AS low_price,
         LEAST(i.bm_kg * i.net_weight - i.customs_value,
               CASE WHEN i.supplementary_qnty > 0 AND i.bm_unit IS NOT NULL
                    THEN i.bm_unit * i.supplementary_qnty - i.customs_value END)
                                                                          AS shortfall
  FROM items_b i
),

v76 AS (
  SELECT tin,
         COUNT(*)                                                         AS items_benchmarked,
         AVG(CAST(implausible AS DOUBLE))                                 AS ctx_implausible_price_rate,
         AVG(CAST(low_price AS DOUBLE))                                   AS par076_low_price_item_rate,
         SUM(CASE WHEN low_price = 1 AND shortfall > 0 THEN shortfall ELSE 0 END)
           / NULLIF(SUM(customs_value), 0)                                AS par076_shortfall_share,
         AVG(CAST(on_origin_bench AS DOUBLE))                             AS origin_benchmark_share,
         percentile_approx(CASE WHEN implausible = 0 THEN price_deviation END, 0.5)
                                                                          AS price_deviation_median
  FROM val
  GROUP BY tin
),

base AS (
  SELECT DISTINCT taxpayer_tin AS tin FROM hist_items
)

SELECT b.tin AS taxpayer_tin,
       s.hs_headings_used,
       s.origins_used,
       s.cpcs_used,
       dm.dominant_hs_chapter,
       dm.chapter_value_share,
       v.items_benchmarked,
       v.par076_low_price_item_rate,
       v.par076_shortfall_share,
       v.ctx_implausible_price_rate,
       v.origin_benchmark_share,
       v.price_deviation_median,
       s.ctx_preferential_use_rate
FROM base b
LEFT JOIN struct s ON s.tin = b.tin
LEFT JOIN dom dm ON dm.tin = b.tin
LEFT JOIN v76 v ON v.tin = b.tin
