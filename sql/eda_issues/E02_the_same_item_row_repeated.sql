-- CTRP EDA issue E02: The same item row repeated
-- What we saw: The same declaration and item number appear many times: 20% of rows repeat an item, up to 412 copies of one item (24 months to Sep 2026). Except for one item, every copy is identical in every column the model uses. The view joins three tables on the declaration ID only (header, item, inspection actions), so a repeat in any of them repeats the item. Q7 shows the item table is the source: for all 7,783 repeated items the item row repeats, while the header and inspection rows never do. 7,748 of them (99.6%) are on motor vehicle declarations. This sheet lists each different row once, with how many copies of the item the view holds.
-- What the model does: R5: each item is kept once. R15 also removes motor vehicle declarations, which hold almost all the copies.
-- Every item row of the entries affected, 2024-09-30 (exclusive) to 2026-09-30, IM4 and IM7. Contains TINs: internal use only.
-- Run as ONE statement, download as CSV, save as data/eda_issues/E02.csv
WITH base AS (
  SELECT COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id) AS entry_key,
         v.entry_num, v.clearance_station_cd, v.dec_ref_yer, v.instance_id, v.key_itm_nbr, v.assessment_dt_wid, v.taxpayer_tin, v.taxpayer_nm, v.consignee_tin, v.consignee_nm, v.regime_cd, v.extended_proc_cd, v.cpc_cd, v.decl_status, v.hsc_cd, v.gds_org_cty, v.customs_value, v.net_weight, v.supplementary_qnty, v.tax_assessed, v.original_tax_amt, v.final_amt, v.top_up_amt, v.top_up_flg, v.amendment_flg, v.is_red_flg, v.is_yellow_flg, v.pay_status, v.preferential_treatment_flag
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20240930' AND v.assessment_dt_wid <= '20260930'
    AND v.regime_cd IN ('IM4', 'IM7')
),
k AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies_of_item FROM base
       GROUP BY instance_id, key_itm_nbr HAVING COUNT(*) > 1)
SELECT DISTINCT k.copies_of_item,
       b.*
FROM base b
JOIN k ON b.instance_id = k.instance_id AND b.key_itm_nbr = k.key_itm_nbr
WHERE TRUE
