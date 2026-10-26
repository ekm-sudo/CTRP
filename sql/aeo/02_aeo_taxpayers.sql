-- STEP 2 of 2. Which taxpayers carry the AEO flag, and since when? (one row per AEO taxpayer)
-- Run in Hue as ONE statement, download as CSV and save it as data/aeo_taxpayers.csv
-- If step 1 shows the AEO value is not 'Y', change the value in the WHERE line below.
-- Used as a CHECK on the model (where do AEO members land in the bands?), never as a score input:
-- AEO status is a customs decision and AEO members are checked less, so scoring on it would be circular.
SELECT taxpayer_tin,
       MIN(assessment_dt_wid)        AS first_day_flagged,
       MAX(assessment_dt_wid)        AS last_day_flagged,
       COUNT(DISTINCT instance_id)   AS declarations_flagged
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE regime_cd IN ('IM4', 'IM7')
  AND assessment_dt_wid > '20230930'
  AND UPPER(TRIM(taxpayer_aeo_flg)) IN ('Y', 'YES', '1')
GROUP BY taxpayer_tin
