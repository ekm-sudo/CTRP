-- CTRP EDA report Q8: Lane flags per declaration, blanks included
-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/Q8.csv
SELECT red, yellow, green, blue, COUNT(*) AS declarations
FROM (SELECT instance_id, MAX(is_red_flg) AS red, MAX(is_yellow_flg) AS yellow,
             MAX(is_green_flg) AS green, MAX(is_blue_flg) AS blue
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930' AND regime_cd IN ('IM4', 'IM7') GROUP BY instance_id) d
GROUP BY red, yellow, green, blue
ORDER BY declarations DESC
