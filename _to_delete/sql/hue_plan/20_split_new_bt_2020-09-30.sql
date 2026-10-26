-- PART "split_new" of a split extract (same-day splitting and new traders).
-- Run in Hue as ONE statement, download as CSV and save it as
--   data/split/split_new_bt_2020-09-30.csv
-- then, when all four parts are saved:  python main.py merge
-- Cut by the code from the full query sql/bt_2020-09-30.sql: same cleaning rules,
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

-- ---------- (3) splitting: same HS code, same day, separate declarations ------------------
-- Bulk goods (cement, fuel, steel) legitimately arrive as many trucks a day, one declaration
-- each. Two protections:
--   * fixed exclusions: HS chapters 25 (cement, clinker, salt) and 27 (fuel), and fuel
--     transit EPCs 4080 and 7180. Edit the lists below to add more.
--   * peer norm: for every other HS code, how often ALL importers lodge same-day repeats.
--     A taxpayer is measured by how far they exceed the norm for their own mix of goods,
--     so a code where repeats are normal protects itself.
split_grp AS (
  SELECT taxpayer_tin AS tin, assessment_dt_wid, hsc_cd, COUNT(DISTINCT instance_id) AS n
  FROM hist_items
  WHERE substr(hsc_cd, 1, 2) NOT IN ('25', '27')
    AND COALESCE(extended_proc_cd, '') NOT IN ('4080', '7180')
  GROUP BY taxpayer_tin, assessment_dt_wid, hsc_cd
),

split_norm AS (
  SELECT hsc_cd, SUM(CASE WHEN n >= 2 THEN n ELSE 0 END) / SUM(n)     AS norm_share
  FROM split_grp
  GROUP BY hsc_cd
),

split_tp AS (
  SELECT g.tin,
         SUM(CASE WHEN g.n >= 2 THEN g.n ELSE 0 END) / SUM(g.n)         AS same_day_split_share,
         SUM(g.n * m.norm_share) / SUM(g.n)                              AS same_day_split_expected,
         SUM(CASE WHEN g.n >= 2 THEN g.n ELSE 0 END) / SUM(g.n)
           - SUM(g.n * m.norm_share) / SUM(g.n)                          AS same_day_split_excess,
         MAX(g.n)                                                        AS max_same_day_same_hs
  FROM split_grp g
  JOIN split_norm m ON g.hsc_cd = m.hsc_cd
  GROUP BY g.tin
),

-- ---------- (4) new traders: no IM4/IM7 declaration in the 3 years before the window -------
prior AS (
  SELECT DISTINCT taxpayer_tin AS tin
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
  WHERE assessment_dt_wid >  '20150930'
    AND assessment_dt_wid <= '20180930'
    AND regime_cd IN ('IM4', 'IM7')
    AND decl_status <> 'Cancelled'
    AND taxpayer_tin RLIKE '^[0-9]{10}$'
),

base AS (
  SELECT DISTINCT taxpayer_tin AS tin FROM hist_items
)

SELECT b.tin AS taxpayer_tin,
       sp.same_day_split_share,
       sp.same_day_split_expected,
       sp.same_day_split_excess,
       sp.max_same_day_same_hs,
       CASE WHEN pr.tin IS NULL THEN 'Y' ELSE 'N' END AS new_trader
FROM base b
LEFT JOIN split_tp sp ON sp.tin = b.tin
LEFT JOIN prior pr ON pr.tin = b.tin
