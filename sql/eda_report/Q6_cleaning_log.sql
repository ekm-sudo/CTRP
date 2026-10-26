-- CTRP EDA report Q6: Rows removed by each cleaning rule (36 months, all regimes)
-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/Q6.csv
WITH v AS (SELECT instance_id, key_itm_nbr, assessment_dt_wid, taxpayer_tin, decl_status, regime_cd,
                  cpc_cd, hsc_cd, COALESCE(concat(entry_num, clearance_station_cd, dec_ref_yer), instance_id) AS entry_key
           FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
           WHERE assessment_dt_wid > '20230930' AND assessment_dt_wid <= '20260930'),
s1 AS (SELECT *, COALESCE(taxpayer_tin RLIKE '^[0-9]{10}$', false) AS r1,
              COALESCE(decl_status <> 'Cancelled', false) AS r3,
              COALESCE(regime_cd IN ('IM4', 'IM7'), false) AS r4,
              COALESCE(COALESCE(cpc_cd, '') <> '483', false) AS r13
       FROM v),
s2 AS (SELECT COALESCE(lpad(instance_id, 20, '0') =
                MAX(lpad(instance_id, 20, '0')) OVER (PARTITION BY entry_key), false) AS r14,
              MAX(CASE WHEN substr(hsc_cd, 1, 4) IN ('8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711') THEN 1 ELSE 0 END)
                OVER (PARTITION BY instance_id) = 0 AS r15,
              ROW_NUMBER() OVER (PARTITION BY instance_id, key_itm_nbr ORDER BY assessment_dt_wid) = 1 AS r5
       FROM s1 WHERE r1 AND r3 AND r4 AND r13)
SELECT stack(5, 'rows loaded', n, 'R1', a, 'R3', b, 'R4', c, 'R13', d) AS (step, rows_removed)
FROM (SELECT COUNT(*) AS n,
             SUM(CASE WHEN NOT r1 THEN 1 ELSE 0 END) AS a,
             SUM(CASE WHEN r1 AND NOT r3 THEN 1 ELSE 0 END) AS b,
             SUM(CASE WHEN r1 AND r3 AND NOT r4 THEN 1 ELSE 0 END) AS c,
             SUM(CASE WHEN r1 AND r3 AND r4 AND NOT r13 THEN 1 ELSE 0 END) AS d FROM s1) x
UNION ALL
SELECT stack(4, 'R14', e, 'R15', f, 'R5', g, 'rows left', h) AS (step, rows_removed)
FROM (SELECT SUM(CASE WHEN NOT r14 THEN 1 ELSE 0 END) AS e,
             SUM(CASE WHEN r14 AND NOT r15 THEN 1 ELSE 0 END) AS f,
             SUM(CASE WHEN r14 AND r15 AND NOT r5 THEN 1 ELSE 0 END) AS g,
             SUM(CASE WHEN r14 AND r15 AND r5 THEN 1 ELSE 0 END) AS h FROM s2) y
