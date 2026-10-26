-- Story notebook, sample 2 of 3: one declaration item that the view stores many times (step B2).
-- Run in Hue as one statement, download as CSV, save as data/samples/story_repeated_item.csv
-- Looks only at March 2026 to keep it fast. Returns up to 15 copies of one item.
WITH rep AS (
  SELECT instance_id, key_itm_nbr, COUNT(*) AS copies
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
  WHERE assessment_dt_wid > '20260301' AND assessment_dt_wid <= '20260331'
    AND regime_cd IN ('IM4', 'IM7')
  GROUP BY instance_id, key_itm_nbr
  HAVING COUNT(*) >= 5
  ORDER BY copies DESC
  LIMIT 1
)
SELECT r.copies, v.instance_id, v.key_itm_nbr, v.assessment_dt_wid, v.taxpayer_tin, v.regime_cd, v.decl_status,
       v.cpc_cd, v.extended_proc_cd, v.hsc_cd, v.gds_org_cty, v.customs_value, v.net_weight,
       v.supplementary_qnty, v.tax_assessed, v.original_tax_amt, v.final_amt, v.top_up_amt,
       v.top_up_flg, v.amendment_flg, v.clearance_station_cd, v.is_red_flg, v.is_yellow_flg,
       v.pay_status, v.preferential_treatment_flag
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
JOIN rep r ON v.instance_id = r.instance_id AND v.key_itm_nbr = r.key_itm_nbr
WHERE v.assessment_dt_wid > '20260301' AND v.assessment_dt_wid <= '20260331'
LIMIT 15
