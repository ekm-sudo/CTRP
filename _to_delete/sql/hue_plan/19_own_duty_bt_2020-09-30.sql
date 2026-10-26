-- PART "own_duty" of a split extract (own-price drop, duty below peers, exemption APC use).
-- Run in Hue as ONE statement, download as CSV and save it as
--   data/split/own_duty_bt_2020-09-30.csv
-- then, when all four parts are saved:  python main.py merge
-- Cut by the code from the full query sql/bt_2020-09-30.sql: same cleaning rules,
-- same dates, so the merged file matches what the full query gives.

WITH p AS (
  SELECT DATE '2020-09-30' AS snap
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
  WHERE v.assessment_dt_wid >  '20180930'
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

-- What: items in the 24-month history only (features are built from history, never the future).
hist_items AS (
  SELECT * FROM items WHERE assessment_dt_wid > '20180930' AND assessment_dt_wid <= '20200930'
),

-- ---------- (1) price against the taxpayer's own history (PAR_067 stand-in) -------------
-- For each HS code the taxpayer imported both in the last 6 months and in the 18 months
-- before: did the median price fall below 70% of their own earlier price, on both bases
-- (per kg, and per unit where recorded)? Measured as a share of recent value.
own AS (
  SELECT i.taxpayer_tin AS tin, i.hsc_cd,
         percentile_approx(CASE WHEN i.adate <= add_months(p.snap, -6) THEN i.customs_value / i.net_weight END, 0.5) AS early_kg,
         percentile_approx(CASE WHEN i.adate >  add_months(p.snap, -6) THEN i.customs_value / i.net_weight END, 0.5) AS late_kg,
         percentile_approx(CASE WHEN i.adate <= add_months(p.snap, -6) AND i.supplementary_qnty > 0
                                THEN i.customs_value / i.supplementary_qnty END, 0.5)                          AS early_u,
         percentile_approx(CASE WHEN i.adate >  add_months(p.snap, -6) AND i.supplementary_qnty > 0
                                THEN i.customs_value / i.supplementary_qnty END, 0.5)                          AS late_u,
         SUM(CASE WHEN i.adate > add_months(p.snap, -6) THEN i.customs_value ELSE 0 END)                       AS late_value,
         SUM(CASE WHEN i.adate <= add_months(p.snap, -6) THEN 1 ELSE 0 END)                                    AS n_early,
         SUM(CASE WHEN i.adate >  add_months(p.snap, -6) THEN 1 ELSE 0 END)                                    AS n_late
  FROM hist_items i
  CROSS JOIN p
  WHERE i.customs_value > 0 AND i.net_weight > 0
  GROUP BY i.taxpayer_tin, i.hsc_cd
),

own_tp AS (
  SELECT tin,
         COUNT(*)                                                         AS hs_codes_compared,
         SUM(CASE WHEN late_kg < 0.7 * early_kg
                   AND (early_u IS NULL OR late_u IS NULL OR late_u < 0.7 * early_u)
                  THEN late_value ELSE 0 END) / NULLIF(SUM(late_value), 0) AS own_price_drop_share
  FROM own
  WHERE n_early >= 2 AND n_late >= 1 AND early_kg > 0
  GROUP BY tin
),

-- ---------- (2) duty rate against HS peers, and exemption use -------------------------------
-- The CPC on a declaration = EPC (extended_proc_cd, 4 digits) + APC (cpc_cd, 3 digits), per the
-- AC-Trade memo CUS/T/9.5.5 of 19 Nov 2025. An APC other than 000 claims a rebate or
-- exemption, so a lower rate under such an APC is expected and is NOT counted as low duty.
-- (2a) Low duty: items under APC 000 (no exemption claimed) taxed at under half the median
--      rate other importers pay on the same HS code, also under APC 000.
-- (2b) Exemption use: share of value declared under any exemption APC.
-- (2c) Watch-list APCs: share of value under the APCs the memo marks "look out for possible
--      abuse" (404, 409, 417, 451, 455, 457, 476, 479, 481, 482, 484). Several of these are
--      marked "not in use", so any use at all is worth an officer's attention.
duty_bench AS (
  SELECT hsc_cd, percentile_approx(tax_assessed / customs_value, 0.5)   AS med_rate
  FROM hist_items
  WHERE customs_value > 0 AND tax_assessed >= 0 AND cpc_cd = '000'
  GROUP BY hsc_cd
  HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),

duty_tp AS (
  SELECT i.taxpayer_tin AS tin,
         SUM(CASE WHEN i.cpc_cd = '000' AND b.med_rate > 0 AND i.tax_assessed / i.customs_value < 0.5 * b.med_rate
                  THEN i.customs_value ELSE 0 END)
           / NULLIF(SUM(CASE WHEN i.cpc_cd = '000' AND b.med_rate > 0 THEN i.customs_value ELSE 0 END), 0)
                                                                          AS low_duty_value_share,
         SUM(CASE WHEN i.cpc_cd = '000' AND b.med_rate > 0
                  THEN GREATEST(b.med_rate * i.customs_value - i.tax_assessed, 0) ELSE 0 END)
           / NULLIF(SUM(CASE WHEN i.cpc_cd = '000' AND b.med_rate > 0 THEN i.customs_value ELSE 0 END), 0)
                                                                          AS duty_gap_share
  FROM hist_items i
  LEFT JOIN duty_bench b ON i.hsc_cd = b.hsc_cd
  WHERE i.customs_value > 0 AND i.tax_assessed >= 0
  GROUP BY i.taxpayer_tin
),

apc_tp AS (
  SELECT taxpayer_tin AS tin,
         SUM(CASE WHEN cpc_cd <> '000' THEN customs_value ELSE 0 END)
           / NULLIF(SUM(customs_value), 0)                                AS exemption_apc_value_share,
         SUM(CASE WHEN cpc_cd IN ('404','409','417','451','455','457','476','479','481','482','484')
                  THEN customs_value ELSE 0 END) / NULLIF(SUM(customs_value), 0)
                                                                          AS watchlist_apc_value_share,
         COUNT(DISTINCT CASE WHEN cpc_cd IN ('404','409','417','451','455','457','476','479','481','482','484')
                             THEN cpc_cd END)                             AS watchlist_apcs_used
  FROM hist_items
  WHERE customs_value > 0
  GROUP BY taxpayer_tin
),

base AS (
  SELECT DISTINCT taxpayer_tin AS tin FROM hist_items
)

SELECT b.tin AS taxpayer_tin,
       ow.hs_codes_compared,
       ow.own_price_drop_share,
       du.low_duty_value_share,
       du.duty_gap_share,
       ap.exemption_apc_value_share,
       ap.watchlist_apc_value_share,
       ap.watchlist_apcs_used
FROM base b
LEFT JOIN own_tp ow ON ow.tin = b.tin
LEFT JOIN duty_tp du ON du.tin = b.tin
LEFT JOIN apc_tp ap ON ap.tin = b.tin
