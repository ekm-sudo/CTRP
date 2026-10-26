-- CTRP EDA issue E01: Same entry under more than one declaration ID
-- What we saw: Entry number + station + year identifies an entry. Some entries appear under two or more declaration IDs (instance_id).
-- What the model does: R14: the entry key is used and only the latest (highest) declaration ID of each entry is kept. Please confirm which version is the real one.
-- Every item row of the entries affected, 2024-09-30 (exclusive) to 2026-09-30, IM4 and IM7. Contains TINs: internal use only.
-- Run as ONE statement, download as CSV, save as data/eda_issues/E01.csv
WITH base AS (
  SELECT COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id) AS entry_key,
         v.entry_num, v.clearance_station_cd, v.dec_ref_yer, v.instance_id, v.key_itm_nbr, v.assessment_dt_wid, v.taxpayer_tin, v.taxpayer_nm, v.consignee_tin, v.consignee_nm, v.regime_cd, v.extended_proc_cd, v.cpc_cd, v.decl_status, v.hsc_cd, v.gds_org_cty, v.customs_value, v.net_weight, v.supplementary_qnty, v.tax_assessed, v.original_tax_amt, v.final_amt, v.top_up_amt, v.top_up_flg, v.amendment_flg, v.is_red_flg, v.is_yellow_flg, v.pay_status, v.preferential_treatment_flag
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20240930' AND v.assessment_dt_wid <= '20260930'
    AND v.regime_cd IN ('IM4', 'IM7')
),
k AS (SELECT entry_key, COUNT(DISTINCT instance_id) AS declaration_ids_on_entry FROM base
       GROUP BY entry_key HAVING COUNT(DISTINCT instance_id) > 1)
SELECT k.declaration_ids_on_entry,
       b.*
FROM base b
JOIN k ON b.entry_key = k.entry_key
WHERE TRUE
