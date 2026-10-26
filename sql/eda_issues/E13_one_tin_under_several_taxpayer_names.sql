-- CTRP EDA issue E13: One TIN under several taxpayer names
-- What we saw: Taxpayer names are typed with variations, addresses mixed in, and in one case a backtick. Some TINs carry several names.
-- What the model does: Names are not used by the model, the TIN identifies the taxpayer. Please confirm none of these TINs is shared by different businesses.
-- One row per TIN and name. Run as ONE statement, save as data/eda_issues/E13.csv
WITH base AS (
  SELECT COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id) AS entry_key,
         v.entry_num, v.clearance_station_cd, v.dec_ref_yer, v.instance_id, v.key_itm_nbr, v.assessment_dt_wid, v.taxpayer_tin, v.taxpayer_nm, v.consignee_tin, v.consignee_nm, v.regime_cd, v.extended_proc_cd, v.cpc_cd, v.decl_status, v.hsc_cd, v.gds_org_cty, v.customs_value, v.net_weight, v.supplementary_qnty, v.tax_assessed, v.original_tax_amt, v.final_amt, v.top_up_amt, v.top_up_flg, v.amendment_flg, v.is_red_flg, v.is_yellow_flg, v.pay_status, v.preferential_treatment_flag
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20240930' AND v.assessment_dt_wid <= '20260930'
    AND v.regime_cd IN ('IM4', 'IM7')
),
multi AS (SELECT taxpayer_tin FROM base GROUP BY taxpayer_tin HAVING COUNT(DISTINCT taxpayer_nm) >= 3)
SELECT b.taxpayer_tin, b.taxpayer_nm, COUNT(DISTINCT b.instance_id) AS declarations,
       MIN(b.assessment_dt_wid) AS first_seen, MAX(b.assessment_dt_wid) AS last_seen,
       COUNT(DISTINCT b.clearance_station_cd) AS stations, MAX(b.entry_key) AS an_entry_key
FROM base b
WHERE b.taxpayer_tin IN (SELECT taxpayer_tin FROM multi)
GROUP BY b.taxpayer_tin, b.taxpayer_nm
