-- STEP 1 of 2. What values does taxpayer_aeo_flg take? (a few rows only)
-- Run in Hue as ONE statement and send the result. It tells us which value means "AEO member".
SELECT taxpayer_aeo_flg,
       COUNT(DISTINCT instance_id)   AS declarations,
       COUNT(DISTINCT taxpayer_tin)  AS taxpayers,
       MIN(assessment_dt_wid)        AS first_day,
       MAX(assessment_dt_wid)        AS last_day
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE regime_cd IN ('IM4', 'IM7')
  AND assessment_dt_wid > '20230930'
GROUP BY taxpayer_aeo_flg
ORDER BY declarations DESC
