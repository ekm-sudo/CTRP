-- PART "core" of a split extract (declaration features and outcomes).
-- Run in Hue as ONE statement, download as CSV and save it as
--   data/split/core_bt_2020-03-31.csv
-- then, when all four parts are saved:  python main.py merge
-- Cut by the code from the full query sql/bt_2020-03-31.sql: same cleaning rules,
-- same dates, so the merged file matches what the full query gives.

WITH p AS (
  SELECT DATE '2020-03-31' AS snap
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
  WHERE v.assessment_dt_wid >  '20180331'
    AND v.assessment_dt_wid <= '20200930'
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

hist AS (SELECT * FROM decl WHERE dt > '20180331' AND dt <= '20200331'),

fut  AS (SELECT * FROM decl WHERE dt >  '20200331'),

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
       '2020-03-31' AS snapshot_date,
       CASE WHEN tp.entries_24m < 10 THEN 'Y' ELSE 'N' END AS limited_history,
       tp.entries_24m,
       tp.active_months,
       tp.avg_items_per_entry,
       tp.total_customs_value,
       tp.total_original_tax,
       tp.total_top_up,
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
       tp.days_since_first_in_window,
       tp.ctx_unpaid_rate,
       tp.ctx_red_lane_rate,
       tp.ctx_yellow_lane_rate,
       COALESCE(o.out_entries, 0) AS out_entries,
       COALESCE(o.out_checked, 0) AS out_checked,
       COALESCE(o.out_checked_hits, 0) AS out_checked_hits,
       COALESCE(o.out_topped_up_entries, 0) AS out_topped_up_entries,
       COALESCE(o.out_top_up, 0) AS out_top_up,
       COALESCE(o.out_original_tax, 0) AS out_original_tax
FROM tp
LEFT JOIN st          ON st.tin = tp.tin
LEFT JOIN outc o      ON o.tin  = tp.tin
