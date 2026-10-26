-- PART "years" of a split extract (counts per year over 3 years, for recency weighting).
-- Run in Hue as ONE statement, download as CSV and save it as
--   data/split/years_bt_2018-09-30.csv
-- then, when all four parts are saved:  python main.py merge
-- Cut by the code from the full query sql/bt_2018-09-30.sql: same cleaning rules,
-- same dates, so the merged file matches what the full query gives.

WITH p AS (
  SELECT DATE '2018-09-30' AS snap
),

-- What: item rows in the window, cleaned (rules R1 to R13), each item numbered once.
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
  WHERE v.assessment_dt_wid >  '20150930'
    AND v.assessment_dt_wid <= '20180930'
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
  SELECT * FROM items WHERE assessment_dt_wid > '20160930' AND assessment_dt_wid <= '20180930'
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

-- ---------- the same counts per year, over 3 years (for recency weighting) ---------------
-- What: for each of the 3 years before the snapshot (y1 = most recent 12 months, y2 = the 12
--       before, y3 = the 12 before that): declarations, and how many were topped up, severely
--       topped up, amended or had tax reduced, with the top-up and original tax amounts.
-- Why:  a recency-weighted rate is (w1 x count1 + w2 x count2 + w3 x count3) / (the same for
--       declarations), so these counts let any weights be tried in Python without another pull.
--       Check: y1 + y2 declarations always equal entries_24m.
yr AS (
  SELECT h.tin,
         SUM(CASE WHEN h.yb = 1 THEN 1 ELSE 0 END)                         AS y1_entries,
         SUM(CASE WHEN h.yb = 1 THEN h.topped_up ELSE 0 END)               AS y1_topped_up,
         SUM(CASE WHEN h.yb = 1 THEN h.severe ELSE 0 END)                  AS y1_severe,
         SUM(CASE WHEN h.yb = 1 AND h.amended = 'Y' THEN 1 ELSE 0 END)     AS y1_amended,
         SUM(CASE WHEN h.yb = 1 THEN h.negative_top_up ELSE 0 END)         AS y1_tax_reduced,
         SUM(CASE WHEN h.yb = 1 THEN h.top_up ELSE 0 END)                  AS y1_top_up_ugx,
         SUM(CASE WHEN h.yb = 1 THEN h.orig_tax ELSE 0 END)                AS y1_original_tax_ugx,
         SUM(CASE WHEN h.yb = 2 THEN 1 ELSE 0 END)                         AS y2_entries,
         SUM(CASE WHEN h.yb = 2 THEN h.topped_up ELSE 0 END)               AS y2_topped_up,
         SUM(CASE WHEN h.yb = 2 THEN h.severe ELSE 0 END)                  AS y2_severe,
         SUM(CASE WHEN h.yb = 2 AND h.amended = 'Y' THEN 1 ELSE 0 END)     AS y2_amended,
         SUM(CASE WHEN h.yb = 2 THEN h.negative_top_up ELSE 0 END)         AS y2_tax_reduced,
         SUM(CASE WHEN h.yb = 2 THEN h.top_up ELSE 0 END)                  AS y2_top_up_ugx,
         SUM(CASE WHEN h.yb = 2 THEN h.orig_tax ELSE 0 END)                AS y2_original_tax_ugx,
         SUM(CASE WHEN h.yb = 3 THEN 1 ELSE 0 END)                         AS y3_entries,
         SUM(CASE WHEN h.yb = 3 THEN h.topped_up ELSE 0 END)               AS y3_topped_up,
         SUM(CASE WHEN h.yb = 3 THEN h.severe ELSE 0 END)                  AS y3_severe,
         SUM(CASE WHEN h.yb = 3 AND h.amended = 'Y' THEN 1 ELSE 0 END)     AS y3_amended,
         SUM(CASE WHEN h.yb = 3 THEN h.negative_top_up ELSE 0 END)         AS y3_tax_reduced,
         SUM(CASE WHEN h.yb = 3 THEN h.top_up ELSE 0 END)                  AS y3_top_up_ugx,
         SUM(CASE WHEN h.yb = 3 THEN h.orig_tax ELSE 0 END)                AS y3_original_tax_ugx,
         DATEDIFF(MAX(h.snap), MAX(CASE WHEN h.topped_up = 1 THEN h.adate END)) AS days_since_last_top_up_36m
  FROM (
    SELECT d.*, p.snap,
           CASE WHEN d.adate > add_months(p.snap, -12) THEN 1
                WHEN d.adate > add_months(p.snap, -24) THEN 2 ELSE 3 END   AS yb,
           CASE WHEN d.topped_up = 1 AND d.top_up >= 0.30 * d.final_tax THEN 1 ELSE 0 END AS severe
    FROM decl d
    CROSS JOIN p
    WHERE d.dt <= '20180930'
  ) h
  GROUP BY h.tin
),

base AS (
  SELECT DISTINCT taxpayer_tin AS tin FROM hist_items
)

SELECT b.tin AS taxpayer_tin,
       yr.y1_entries,
       yr.y1_topped_up,
       yr.y1_severe,
       yr.y1_amended,
       yr.y1_tax_reduced,
       yr.y1_top_up_ugx,
       yr.y1_original_tax_ugx,
       yr.y2_entries,
       yr.y2_topped_up,
       yr.y2_severe,
       yr.y2_amended,
       yr.y2_tax_reduced,
       yr.y2_top_up_ugx,
       yr.y2_original_tax_ugx,
       yr.y3_entries,
       yr.y3_topped_up,
       yr.y3_severe,
       yr.y3_amended,
       yr.y3_tax_reduced,
       yr.y3_top_up_ugx,
       yr.y3_original_tax_ugx,
       yr.days_since_last_top_up_36m
FROM base b
LEFT JOIN yr yr ON yr.tin = b.tin
