-- CTRP EDA report Q3: Test of "blank original tax means unchanged" (by top-up flag)
-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/Q3.csv
SELECT COALESCE(flag, 'blank') AS top_up_flag, COUNT(*) AS declarations,
       AVG(CASE WHEN original_tax IS NULL THEN 1D ELSE 0D END) AS original_tax_blank
FROM (SELECT instance_id, MAX(top_up_flg) AS flag, MAX(original_tax_amt) AS original_tax
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930' AND regime_cd IN ('IM4', 'IM7')
      GROUP BY instance_id) d
GROUP BY COALESCE(flag, 'blank')
