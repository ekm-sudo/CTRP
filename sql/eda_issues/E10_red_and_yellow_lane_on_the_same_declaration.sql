-- CTRP EDA issue E10: Red and yellow lane on the same declaration
-- What we saw: A declaration can carry both the red and the yellow flag.
-- What the model does: R12: a declaration counts as checked if either flag is 1.
-- Every item row of the entries affected, 2024-09-30 (exclusive) to 2026-09-30, IM4 and IM7, a random 1 in 5 of the entries. Contains TINs: internal use only.
-- Run as ONE statement, download as CSV, save as data/eda_issues/E10.csv
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
WHERE b.instance_id IN (SELECT instance_id FROM d WHERE red = 1 AND yellow = 1)
  AND pmod(hash(b.entry_key), 5) = 0
