-- CTRP Python feature notebook: taxpayers in the sample who declared IM4 or IM7 in the 3 years BEFORE the
-- 24-month feature window (2021-09-30 to 2024-09-30). Used only to tell whether a taxpayer is new.
-- Run as ONE statement, download as CSV, save as data/python_features/prior_tins.csv
SELECT DISTINCT v.taxpayer_tin
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
WHERE v.assessment_dt_wid >  '20210930'
  AND v.assessment_dt_wid <= '20240930'
  AND v.regime_cd IN ('IM4', 'IM7')
  AND v.decl_status <> 'Cancelled'
  AND v.taxpayer_tin RLIKE '^[0-9]{10}$'
  AND pmod(hash(v.taxpayer_tin), 20) = 0
