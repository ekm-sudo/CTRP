-- CTRP EDA issue E12: Price per kg under 1% of the middle price for the HS code
-- What we saw: Some items are priced at under 1% of what importers usually declare for the same HS code: most likely a weight or quantity in the wrong unit.
-- What the model does: R9: treated as keying errors and kept out of the undervaluation measure (counted separately).
-- Every item row of the entries affected, 2024-09-30 (exclusive) to 2026-09-30, IM4 and IM7. Contains TINs: internal use only.
-- Run as ONE statement, download as CSV, save as data/eda_issues/E12.csv
WITH base AS (
  SELECT COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id) AS entry_key,
         v.entry_num, v.clearance_station_cd, v.dec_ref_yer, v.instance_id, v.key_itm_nbr, v.assessment_dt_wid, v.taxpayer_tin, v.taxpayer_nm, v.consignee_tin, v.consignee_nm, v.regime_cd, v.extended_proc_cd, v.cpc_cd, v.decl_status, v.hsc_cd, v.gds_org_cty, v.customs_value, v.net_weight, v.supplementary_qnty, v.tax_assessed, v.original_tax_amt, v.final_amt, v.top_up_amt, v.top_up_flg, v.amendment_flg, v.is_red_flg, v.is_yellow_flg, v.pay_status, v.preferential_treatment_flag
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20240930' AND v.assessment_dt_wid <= '20260930'
    AND v.regime_cd IN ('IM4', 'IM7')
),
bench AS (SELECT hsc_cd, percentile_approx(customs_value / net_weight, 0.5) AS med_kg FROM base WHERE customs_value > 0 AND net_weight > 0 GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
low AS (SELECT DISTINCT x.instance_id FROM base x JOIN bench m ON x.hsc_cd = m.hsc_cd WHERE x.customs_value > 0 AND x.net_weight > 0 AND x.customs_value / x.net_weight < 0.01 * m.med_kg)
SELECT b.*
FROM base b
WHERE b.instance_id IN (SELECT instance_id FROM low)
