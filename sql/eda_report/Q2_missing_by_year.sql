-- CTRP EDA report Q2: Missing data per year, for the columns the model leans on
-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/Q2.csv
SELECT substr(assessment_dt_wid, 1, 4) AS year, COUNT(*) AS item_rows,
       AVG(CASE WHEN original_tax_amt IS NULL THEN 1D ELSE 0D END) AS blank_original_tax_amt,
       AVG(CASE WHEN hsc_cd IS NULL THEN 1D ELSE 0D END) AS blank_hsc_cd,
       AVG(CASE WHEN gds_org_cty IS NULL THEN 1D ELSE 0D END) AS blank_gds_org_cty,
       AVG(CASE WHEN supplementary_qnty IS NULL THEN 1D ELSE 0D END) AS blank_supplementary_qnty,
       AVG(CASE WHEN net_weight IS NULL THEN 1D ELSE 0D END) AS blank_net_weight,
       AVG(CASE WHEN tax_assessed IS NULL THEN 1D ELSE 0D END) AS blank_tax_assessed,
       AVG(CASE WHEN cpc_cd IS NULL THEN 1D ELSE 0D END) AS blank_cpc_cd,
       AVG(CASE WHEN entry_num IS NULL THEN 1D ELSE 0D END) AS blank_entry_num,
       AVG(CASE WHEN decl_status IS NULL THEN 1D ELSE 0D END) AS blank_decl_status,
       AVG(CASE WHEN clearance_station_cd IS NULL THEN 1D ELSE 0D END) AS blank_clearance_station_cd
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930' AND regime_cd IN ('IM4', 'IM7')
GROUP BY substr(assessment_dt_wid, 1, 4)
ORDER BY year
