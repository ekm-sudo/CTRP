-- PART "core" of a split extract (version 1 features, PAR_076 and outcomes).
-- Run in Hue as ONE statement, download as CSV and save it as
--   data/split/core_bt_2025-03-31.csv
-- then, when all three parts are saved:  python main.py merge
-- Cut by the code from the full query sql/bt_2025-03-31.sql: same cleaning rules,
-- same dates, so the merged file matches what the full query gives.

WITH p AS (
  SELECT DATE '2025-03-31' AS snap
),

-- What: item rows in the window, cleaned (rules R1 to R13), each item numbered once.
-- Why:  the view repeats some items many times, so duplicates must go before any count.
raw AS (
  SELECT v.*,
         ROW_NUMBER() OVER (PARTITION BY v.instance_id, v.key_itm_nbr ORDER BY v.assessment_dt_wid) AS rn
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid >  '20230331'
    AND v.assessment_dt_wid <= '20250930'
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
),

-- What: items in the 24-month history only (features are built from history, never the future).
hist_items AS (
  SELECT * FROM items WHERE assessment_dt_wid <= '20250331'
),

-- ---------- one row per declaration ---------------------------------------------------
-- What: one row per declaration with its tax, top-up and lane.
-- Why:  tax amounts repeat on every item row, so they are taken once per declaration.
decl_all AS (
  SELECT instance_id,
         MAX(taxpayer_tin)                                   AS tin,
         MAX(adate)                                          AS adate,
         MAX(assessment_dt_wid)                              AS dt,
         MAX(regime_cd)                                      AS regime,
         COALESCE(MAX(original_tax_amt), MAX(final_amt))     AS orig_tax,
         MAX(final_amt)                                      AS final_tax,
         MAX(top_up_flg)                                     AS top_up_flg,
         MAX(amendment_flg)                                  AS amended,
         MAX(clearance_station_cd)                           AS station,
         MAX(is_red_flg)                                     AS red,
         MAX(is_yellow_flg)                                  AS yellow,
         MAX(pay_status)                                     AS pay_status,
         MAX(TRIM(consignee_tin))                            AS cons_tin,
         SUM(customs_value)                                  AS value,
         COUNT(*)                                            AS n_items
  FROM items
  GROUP BY instance_id
),

decl AS (
  SELECT d.*,
         CASE WHEN d.top_up_flg = 'Y' AND d.final_tax > d.orig_tax THEN 1 ELSE 0 END             AS topped_up,
         CASE WHEN d.top_up_flg = 'Y' AND d.final_tax > d.orig_tax
              THEN d.final_tax - d.orig_tax ELSE 0 END                                          AS top_up,
         CASE WHEN d.final_tax < d.orig_tax THEN 1 ELSE 0 END                                   AS negative_top_up
  FROM decl_all d
),

hist AS (SELECT * FROM decl WHERE dt <= '20250331'),

fut  AS (SELECT * FROM decl WHERE dt >  '20250331'),

-- ---------- scored parameters and pattern features from declarations ------------------
-- What: one row per taxpayer with every rate the scorecard uses.
tp AS (
  SELECT h.tin,
         COUNT(*)                                                         AS entries_24m,
         COUNT(DISTINCT date_format(h.adate, 'yyyyMM'))                   AS active_months,
         AVG(h.n_items)                                                   AS avg_items_per_entry,
         SUM(h.value)                                                     AS total_customs_value,
         SUM(h.orig_tax)                                                  AS total_original_tax,
         SUM(h.top_up)                                                    AS total_top_up,

         AVG(CASE WHEN h.amended = 'Y' THEN 1.0 ELSE 0.0 END)             AS par045_amended_entry_rate,
         SUM(h.top_up) / NULLIF(SUM(h.orig_tax), 0)                       AS par048_top_up_ratio,
         AVG(CAST(h.negative_top_up AS DOUBLE))                           AS par066_negative_top_up_rate,
         AVG(CASE WHEN h.topped_up = 1 AND h.top_up >= 0.30 * h.final_tax
                  THEN 1.0 ELSE 0.0 END)                                  AS par077_severe_top_up_rate,
         DATEDIFF(MAX(p.snap), MAX(CASE WHEN h.topped_up = 1 THEN h.adate END))
                                                                          AS par105_days_since_last_top_up,
         AVG(CAST(h.topped_up AS DOUBLE))                                 AS top_up_entry_rate,
         DATEDIFF(MAX(p.snap), MIN(h.adate))                              AS days_since_first_in_window,

         COUNT(DISTINCT h.station)                                        AS stations_used_24m,
         COUNT(DISTINCT CASE WHEN h.adate > date_sub(p.snap, 90) THEN h.station END)
                                                                          AS stations_used_90d,
         SUM(CASE WHEN h.adate > date_sub(p.snap, 90) THEN 1 ELSE 0 END)  AS entries_last_90d,
         SUM(CASE WHEN h.adate >  date_sub(p.snap, 180)
                   AND h.adate <= date_sub(p.snap, 90) THEN 1 ELSE 0 END) AS entries_prev_90d,
         AVG(CASE WHEN h.regime = 'IM7' THEN 1.0 ELSE 0.0 END)            AS im7_share,
         COUNT(DISTINCT h.cons_tin)                                       AS distinct_consignees,
         AVG(CASE WHEN h.cons_tin = h.tin THEN 1.0 ELSE 0.0 END)          AS consignee_is_self_share,

         AVG(CASE WHEN h.pay_status = 'NOT_PAID' AND h.final_tax > 0
                  THEN 1.0 ELSE 0.0 END)                                  AS ctx_unpaid_rate,
         AVG(CASE WHEN h.red = 1 THEN 1.0 ELSE 0.0 END)                   AS ctx_red_lane_rate,
         AVG(CASE WHEN h.yellow = 1 THEN 1.0 ELSE 0.0 END)                AS ctx_yellow_lane_rate
  FROM hist h
  CROSS JOIN p
  GROUP BY h.tin
),

st AS (
  SELECT tin, MAX(n) / SUM(n) AS main_station_share
  FROM (SELECT tin, station, COUNT(*) AS n FROM hist GROUP BY tin, station) x
  GROUP BY tin
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

-- ---------- outcomes in the 6 months after the snapshot --------------------------------
-- What: what happened next: declarations checked (red or yellow) and how many ended in a top-up.
-- Why:  the back-test judges the score against these, so they come only from AFTER the snapshot.
outc AS (
  SELECT tin,
         COUNT(*)                                                         AS out_entries,
         SUM(CASE WHEN red = 1 OR yellow = 1 THEN 1 ELSE 0 END)           AS out_checked,
         SUM(CASE WHEN (red = 1 OR yellow = 1) AND topped_up = 1 THEN 1 ELSE 0 END)
                                                                          AS out_checked_hits,
         SUM(topped_up)                                                   AS out_topped_up_entries,
         SUM(top_up)                                                      AS out_top_up,
         SUM(orig_tax)                                                    AS out_original_tax
  FROM fut
  GROUP BY tin
)

SELECT tp.tin AS taxpayer_tin,
       '2025-03-31' AS snapshot_date,
       CASE WHEN tp.entries_24m < 10 THEN 'Y' ELSE 'N' END AS limited_history,
       tp.entries_24m,
       tp.active_months,
       tp.avg_items_per_entry,
       tp.total_customs_value,
       tp.total_original_tax,
       tp.total_top_up,
       s.hs_headings_used,
       s.origins_used,
       s.cpcs_used,
       dm.dominant_hs_chapter,
       dm.chapter_value_share,
       tp.stations_used_24m,
       tp.stations_used_90d,
       st.main_station_share,
       tp.entries_last_90d,
       tp.entries_prev_90d,
       tp.im7_share,
       tp.distinct_consignees,
       tp.consignee_is_self_share,
       tp.par045_amended_entry_rate,
       tp.par048_top_up_ratio,
       tp.par066_negative_top_up_rate,
       tp.par077_severe_top_up_rate,
       tp.par105_days_since_last_top_up,
       tp.top_up_entry_rate,
       v.items_benchmarked,
       v.par076_low_price_item_rate,
       v.par076_shortfall_share,
       v.ctx_implausible_price_rate,
       v.origin_benchmark_share,
       v.price_deviation_median,
       tp.days_since_first_in_window,
       tp.ctx_unpaid_rate,
       tp.ctx_red_lane_rate,
       tp.ctx_yellow_lane_rate,
       s.ctx_preferential_use_rate,
       COALESCE(o.out_entries, 0) AS out_entries,
       COALESCE(o.out_checked, 0) AS out_checked,
       COALESCE(o.out_checked_hits, 0) AS out_checked_hits,
       COALESCE(o.out_topped_up_entries, 0) AS out_topped_up_entries,
       COALESCE(o.out_top_up, 0) AS out_top_up,
       COALESCE(o.out_original_tax, 0) AS out_original_tax
FROM tp
LEFT JOIN st          ON st.tin = tp.tin
LEFT JOIN struct s    ON s.tin  = tp.tin
LEFT JOIN dom dm      ON dm.tin = tp.tin
LEFT JOIN v76 v       ON v.tin  = tp.tin
LEFT JOIN outc o      ON o.tin  = tp.tin
