-- CTRP EDA issue E07: Tax rose, but no top-up flag
-- What we saw: About 3,000 amended declarations have a higher final tax but no top-up flag.
-- What the model does: Decision 18: not counted as top-ups (the flag is customs' own marking). Please confirm whether these are top-ups.
-- Every item row of the entries affected, 2024-09-30 (exclusive) to 2026-09-30, IM4 and IM7. Contains TINs: internal use only.
-- Run as ONE statement, download as CSV, save as data/eda_issues/E07.csv
WITH base AS (
  SELECT COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id) AS entry_key,
         v.entry_num, v.clearance_station_cd, v.dec_ref_yer, v.instance_id, v.key_itm_nbr, v.assessment_dt_wid, v.taxpayer_tin, v.taxpayer_nm, v.consignee_tin, v.consignee_nm, v.regime_cd, v.extended_proc_cd, v.cpc_cd, v.decl_status, v.hsc_cd, v.gds_org_cty, v.customs_value, v.net_weight, v.supplementary_qnty, v.tax_assessed, v.original_tax_amt, v.final_amt, v.top_up_amt, v.top_up_flg, v.amendment_flg, v.is_red_flg, v.is_yellow_flg, v.pay_status, v.preferential_treatment_flag
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20240930' AND v.assessment_dt_wid <= '20260930'
    AND v.regime_cd IN ('IM4', 'IM7')
),
d AS (
  SELECT entry_key, instance_id, MAX(top_up_flg) AS flag, MAX(original_tax_amt) AS orig_raw,
         COALESCE(MAX(original_tax_amt), MAX(final_amt)) AS orig, MAX(final_amt) AS fin,
         MAX(top_up_amt) AS top_up_amt_max, MAX(is_red_flg) AS red, MAX(is_yellow_flg) AS yellow
  FROM base GROUP BY entry_key, instance_id
)
SELECT b.*
FROM base b
WHERE b.instance_id IN (SELECT instance_id FROM d WHERE COALESCE(flag, 'N') <> 'Y' AND orig_raw IS NOT NULL AND fin > orig_raw)
