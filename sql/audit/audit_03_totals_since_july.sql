-- Context for the estimate: every IM4/IM7 declaration since 1 Jul 2026, checked or not, with tax and top-ups.
-- Small result (2 rows). Run in Hue, save as data/audit/totals_since_july.csv
WITH items AS (
  SELECT v.*, ROW_NUMBER() OVER (PARTITION BY v.instance_id, v.key_itm_nbr ORDER BY v.assessment_dt_wid) AS rn,
         MAX(lpad(v.instance_id, 20, '0')) OVER (PARTITION BY COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id)) AS latest_instance,   -- R14
         MAX(CASE WHEN substr(v.hsc_cd, 1, 4) IN ('8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711') THEN 1 ELSE 0 END) OVER (PARTITION BY v.instance_id) AS has_vehicle   -- R15
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20260701'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND v.decl_status <> 'Cancelled'
    AND COALESCE(v.cpc_cd, '') <> '483'
    AND v.taxpayer_tin RLIKE '^[0-9]{10}$'
),
decl AS (
  SELECT instance_id, MAX(assessment_dt_wid) AS dt, SUM(customs_value) AS value,
         COALESCE(MAX(original_tax_amt), MAX(final_amt)) AS original_tax, MAX(final_amt) AS final_tax,
         MAX(top_up_flg) AS top_up_flg,
         CASE WHEN COALESCE(CAST(MAX(is_red_flg) AS INT), 0) = 1 OR COALESCE(CAST(MAX(is_yellow_flg) AS INT), 0) = 1 THEN 'Y' ELSE 'N' END AS checked
  FROM items WHERE rn = 1
    AND lpad(instance_id, 20, '0') = latest_instance   -- R14 latest declaration ID per entry
    AND has_vehicle = 0                                 -- R15 no motor vehicle declarations
  GROUP BY instance_id
)
SELECT checked,
       COUNT(*)                                                   AS declarations,
       MIN(dt)                                                    AS first_day,
       MAX(dt)                                                    AS last_day,
       SUM(value)                                                 AS customs_value,
       SUM(final_tax)                                             AS final_tax,
       SUM(CASE WHEN top_up_flg = 'Y' AND final_tax > original_tax THEN 1 ELSE 0 END)                    AS topped_up,
       SUM(CASE WHEN top_up_flg = 'Y' AND final_tax > original_tax THEN final_tax - original_tax ELSE 0 END) AS top_up_amount
FROM decl
GROUP BY checked
