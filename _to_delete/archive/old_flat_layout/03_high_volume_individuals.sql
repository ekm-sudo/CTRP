-- =====================================================================================
-- Customs Taxpayer Risk Profiling Model
-- 03  High-volume individuals: analysis for the Risk team
--
-- Question: some TINs registered to private individuals clear more declarations than most
-- companies (e.g. 10,000 to 17,000 in two years at Busia). Is this a simplified small-trader
-- arrangement, or a TIN being used to clear other people's goods?
--
-- Window : 24 months to 30 September 2026, all regimes, cancelled declarations excluded.
-- "Looks like an individual" is a NAME TEST (titles such as MR./MRS., and no company words).
-- Names in this data are messy, so the list is a starting point for the Risk team to
-- confirm, not a finding.
--
-- Run one query at a time (Ctrl+Enter). Each query is self-contained.
-- =====================================================================================


-- I1  The shortlist: individuals with 1,000+ declarations, and how they trade
-- What each column tells the Risk team:
--   decl_per_active_day   : 20+ a day is beyond one person importing for themselves
--   avg_value_per_decl    : small values suggest small-trader consignments
--   distinct_consignees   : many different consignees = goods going to many other people
--   share_consignee_is_tin: low share = the TIN is rarely the receiver of the goods
--   main_regime / station : a simplified regime at one border post points to small traders
--   amended / top-up / red: whether customs already finds problems on these declarations
WITH items AS (
  SELECT * FROM (
    SELECT v.*, ROW_NUMBER() OVER (PARTITION BY instance_id, key_itm_nbr ORDER BY assessment_dt_wid) AS rn
    FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
    WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930'
      AND decl_status <> 'Cancelled'
      AND taxpayer_tin RLIKE '^[0-9]{10}$'
  ) x WHERE rn = 1
),
decl AS (
  SELECT instance_id,
         MAX(taxpayer_tin) AS tin, MAX(taxpayer_nm) AS nm, MAX(assessment_dt_wid) AS dt,
         MAX(regime_cd) AS regime, MAX(clearance_station_cd) AS station,
         MAX(TRIM(consignee_tin)) AS cons_tin, MAX(consignee_nm) AS cons_nm,
         MAX(amendment_flg) AS amended, MAX(top_up_flg) AS topped_up, MAX(is_red_flg) AS red,
         SUM(customs_value) AS value, MAX(original_tax_amt) AS orig_tax
  FROM items GROUP BY instance_id
),
names AS (
  SELECT tin, MAX(UPPER(nm)) AS nm FROM decl GROUP BY tin
),
indiv AS (
  SELECT tin, nm FROM names
  WHERE nm RLIKE '^(MR|MRS|MS|MISS|DR)[. ]'
     OR NOT nm RLIKE '(LIMITED|LTD|COMPANY| CO[. ]|SMC|INDUSTR|ENTERPRISE|GROUP|INTERNATIONAL|MOTORS|TRADING|AGENC|CORPORATION|HOLDINGS|SUPPLIES|STORES|HARDWARE|PHARM|BANK|MINISTRY|AUTHORITY|UNIVERSITY|SCHOOL|CHURCH|HOSPITAL|ASSOCIATION|SOCIETY|COOPERATIVE| PLC| INC| LLC|UGANDA)'
),
reg AS (
  SELECT tin, regime AS main_regime, share AS main_regime_share FROM (
    SELECT tin, regime, COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY tin) AS share,
           ROW_NUMBER() OVER (PARTITION BY tin ORDER BY COUNT(*) DESC) AS r
    FROM decl GROUP BY tin, regime) z WHERE r = 1
),
stn AS (
  SELECT tin, station AS main_station, share AS main_station_share FROM (
    SELECT tin, station, COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY tin) AS share,
           ROW_NUMBER() OVER (PARTITION BY tin ORDER BY COUNT(*) DESC) AS r
    FROM decl GROUP BY tin, station) z WHERE r = 1
)
SELECT d.tin, i.nm AS name,
       COUNT(*)                                                         AS declarations,
       COUNT(DISTINCT d.dt)                                             AS active_days,
       ROUND(COUNT(*) / COUNT(DISTINCT d.dt), 1)                        AS decl_per_active_day,
       ROUND(SUM(d.value))                                              AS total_customs_value,
       ROUND(AVG(d.value))                                              AS avg_value_per_decl,
       ROUND(SUM(d.orig_tax))                                           AS total_original_tax,
       COUNT(DISTINCT d.regime)                                         AS regimes_used,
       MAX(r.main_regime) AS main_regime, ROUND(MAX(r.main_regime_share), 3) AS main_regime_share,
       COUNT(DISTINCT d.station)                                        AS stations_used,
       MAX(s.main_station) AS main_station, ROUND(MAX(s.main_station_share), 3) AS main_station_share,
       COUNT(DISTINCT d.cons_tin)                                       AS distinct_consignee_tins,
       COUNT(DISTINCT UPPER(d.cons_nm))                                 AS distinct_consignee_names,
       ROUND(AVG(CASE WHEN d.cons_tin = d.tin THEN 1.0 ELSE 0.0 END), 3) AS share_consignee_is_tin,
       ROUND(AVG(CASE WHEN d.amended = 'Y' THEN 1.0 ELSE 0.0 END), 3)   AS amended_rate,
       ROUND(AVG(CASE WHEN d.topped_up = 'Y' THEN 1.0 ELSE 0.0 END), 3) AS top_up_rate,
       ROUND(AVG(CASE WHEN d.red = 1 THEN 1.0 ELSE 0.0 END), 3)         AS red_lane_rate
FROM decl d
JOIN indiv i ON i.tin = d.tin
LEFT JOIN reg r ON r.tin = d.tin
LEFT JOIN stn s ON s.tin = d.tin
GROUP BY d.tin, i.nm
HAVING COUNT(*) >= 1000
ORDER BY declarations DESC;


-- I2  For comparison: the same measures for ALL taxpayers, by size
-- Why: the Risk team will ask "compared to what?". This gives the normal values for
-- decl_per_active_day, consignees and avg value at each activity level.
WITH items AS (
  SELECT * FROM (
    SELECT v.*, ROW_NUMBER() OVER (PARTITION BY instance_id, key_itm_nbr ORDER BY assessment_dt_wid) AS rn
    FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
    WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930'
      AND decl_status <> 'Cancelled'
      AND taxpayer_tin RLIKE '^[0-9]{10}$'
  ) x WHERE rn = 1
),
decl AS (
  SELECT instance_id, MAX(taxpayer_tin) AS tin, MAX(assessment_dt_wid) AS dt,
         MAX(TRIM(consignee_tin)) AS cons_tin, SUM(customs_value) AS value
  FROM items GROUP BY instance_id
),
tp AS (
  SELECT tin, COUNT(*) AS n, COUNT(*) / COUNT(DISTINCT dt) AS per_day,
         COUNT(DISTINCT cons_tin) AS consignees, AVG(value) AS avg_value,
         AVG(CASE WHEN cons_tin = tin THEN 1.0 ELSE 0.0 END) AS cons_is_tin
  FROM decl GROUP BY tin
)
SELECT CASE WHEN n < 100 THEN '1-99' WHEN n < 1000 THEN '100-999'
            WHEN n < 5000 THEN '1000-4999' ELSE '5000+' END     AS declarations_24m,
       COUNT(*)                                                 AS taxpayers,
       percentile_approx(per_day, 0.5)                          AS median_decl_per_active_day,
       percentile_approx(consignees, 0.5)                       AS median_distinct_consignees,
       percentile_approx(avg_value, 0.5)                        AS median_avg_value_per_decl,
       percentile_approx(cons_is_tin, 0.5)                      AS median_share_consignee_is_tin
FROM tp
GROUP BY CASE WHEN n < 100 THEN '1-99' WHEN n < 1000 THEN '100-999'
              WHEN n < 5000 THEN '1000-4999' ELSE '5000+' END
ORDER BY declarations_24m;


-- I3  Who receives the goods? Top 10 consignees for each shortlisted individual
-- Why: if one person's TIN clears goods for dozens of named consignees, the goods are not
-- theirs. That is the central question for the Risk team.
WITH items AS (
  SELECT * FROM (
    SELECT v.*, ROW_NUMBER() OVER (PARTITION BY instance_id, key_itm_nbr ORDER BY assessment_dt_wid) AS rn
    FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
    WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930'
      AND decl_status <> 'Cancelled'
      AND taxpayer_tin IN ('1037067854', '1056716381', '1039235645', '1010754474')  -- >>> paste shortlist from I1
  ) x WHERE rn = 1
),
decl AS (
  SELECT instance_id, MAX(taxpayer_tin) AS tin, MAX(TRIM(consignee_tin)) AS cons_tin,
         MAX(UPPER(consignee_nm)) AS cons_nm, SUM(customs_value) AS value
  FROM items GROUP BY instance_id
)
SELECT tin, cons_tin, cons_nm, declarations, ROUND(value) AS customs_value FROM (
  SELECT tin, cons_tin, cons_nm, COUNT(*) AS declarations, SUM(value) AS value,
         ROW_NUMBER() OVER (PARTITION BY tin ORDER BY COUNT(*) DESC) AS r
  FROM decl GROUP BY tin, cons_tin, cons_nm) z
WHERE r <= 10
ORDER BY tin, declarations DESC;


-- I4  What do they import? Top 5 HS chapters by value, and month-by-month activity
-- Why: one commodity cleared steadily every month looks like a trade; a spread of unrelated
-- goods, or sudden bursts, looks like clearing for others.
WITH items AS (
  SELECT * FROM (
    SELECT v.*, ROW_NUMBER() OVER (PARTITION BY instance_id, key_itm_nbr ORDER BY assessment_dt_wid) AS rn
    FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
    WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930'
      AND decl_status <> 'Cancelled'
      AND taxpayer_tin IN ('1037067854', '1056716381', '1039235645', '1010754474')  -- >>> paste shortlist from I1
  ) x WHERE rn = 1
)
SELECT taxpayer_tin AS tin, substr(hsc_cd, 1, 2) AS hs_chapter,
       COUNT(DISTINCT instance_id) AS declarations, ROUND(SUM(customs_value)) AS customs_value,
       COUNT(DISTINCT substr(assessment_dt_wid, 1, 6)) AS months_active
FROM items
GROUP BY taxpayer_tin, substr(hsc_cd, 1, 2)
ORDER BY tin, customs_value DESC;
