-- CTRP EDA report Q4: Duplicates at every level
-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/Q4.csv
WITH base AS (SELECT COALESCE(concat(entry_num, clearance_station_cd, dec_ref_yer), instance_id) AS entry_key, entry_num, clearance_station_cd, dec_ref_yer, instance_id, key_itm_nbr, assessment_dt_wid, taxpayer_tin, taxpayer_nm, consignee_tin, consignee_nm, regime_cd, extended_proc_cd, cpc_cd, decl_status, hsc_cd, gds_org_cty, customs_value, net_weight, supplementary_qnty, tax_assessed, original_tax_amt, final_amt, top_up_amt, top_up_flg, amendment_flg, is_red_flg, is_yellow_flg, pay_status, preferential_treatment_flag
              FROM dm_modeled_ura_datascience.vw_cstm_AEO_model WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930' AND regime_cd IN ('IM4', 'IM7')),
copies AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies FROM base GROUP BY instance_id, key_itm_nbr),
versions AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS versions
             FROM (SELECT DISTINCT * FROM base) d GROUP BY instance_id, key_itm_nbr),
per_entry AS (SELECT entry_key, COUNT(DISTINCT instance_id) AS ids FROM base GROUP BY entry_key),
per_id AS (SELECT instance_id, COUNT(DISTINCT taxpayer_tin) AS tins,
                  COUNT(DISTINCT assessment_dt_wid) AS dates FROM base GROUP BY instance_id)
SELECT (SELECT SUM(copies) FROM copies) AS item_rows,
       (SELECT SUM(versions) FROM versions) AS different_rows,
       (SELECT COUNT(*) FROM copies) AS items,
       (SELECT SUM(CASE WHEN versions > 1 THEN 1 ELSE 0 END) FROM versions) AS items_with_copies_not_identical,
       (SELECT MAX(copies) FROM copies) AS most_copies_of_one_item,
       (SELECT SUM(CASE WHEN ids > 1 THEN 1 ELSE 0 END) FROM per_entry) AS entries_under_several_ids,
       (SELECT SUM(CASE WHEN tins > 1 THEN 1 ELSE 0 END) FROM per_id) AS ids_with_several_tins,
       (SELECT SUM(CASE WHEN dates > 1 THEN 1 ELSE 0 END) FROM per_id) AS ids_with_several_dates
