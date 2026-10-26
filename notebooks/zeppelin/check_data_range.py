%pyspark
# =====================================================================================
# First paragraph: what the view holds (run once; it answers "how far back does the data go?")
# =====================================================================================
spark.sql("""
SELECT substr(assessment_dt_wid, 1, 4) AS year,
       MIN(assessment_dt_wid) AS first_day, MAX(assessment_dt_wid) AS last_day,
       COUNT(DISTINCT instance_id) AS declarations, COUNT(DISTINCT taxpayer_tin) AS taxpayers
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE regime_cd IN ('IM4', 'IM7')
GROUP BY substr(assessment_dt_wid, 1, 4)
ORDER BY year
""").show(20, False)
