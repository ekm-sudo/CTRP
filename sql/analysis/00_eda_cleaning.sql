-- =====================================================================================
-- Customs Taxpayer Risk Profiling Model, release 1
-- 00  Exploratory data analysis and cleaning checks
--
-- Source : dm_modeled_ura_datascience.vw_cstm_AEO_model  (one row per declaration item)
--
-- HOW TO RUN: one query at a time. Put the cursor inside the query and press Ctrl+Enter.
-- Hue shows only the result of the last statement it runs, so do not run the file as a block.
-- Most queries look at the last 24 months (the scoring window) to keep them fast.
--
-- Each query says WHY it matters and WHAT TO LOOK FOR. Record the answers in the
-- cleaning log at the bottom, the feature query (01) applies the rules decided there.
-- =====================================================================================


-- ─────────────────────────────────────────────────────────────────────────────────────
-- A. SHAPE AND GRAIN
-- ─────────────────────────────────────────────────────────────────────────────────────

-- A1  How big is the view, and is it one row per item?
-- Look for: item_rows = distinct_items. If item_rows is larger, rows are duplicated (see B1).
SELECT COUNT(*)                                 AS item_rows,
       COUNT(DISTINCT instance_id)              AS declarations,
       COUNT(DISTINCT instance_id, key_itm_nbr) AS distinct_items,
       MIN(assessment_dt_wid)                   AS first_date,
       MAX(assessment_dt_wid)                   AS last_date
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model;

-- A2  How much history is there, month by month?
-- Look for: gaps or sudden drops (a missing load), and whether the last months are complete.
-- This decides the back-test dates: the outcome window must be months that are fully loaded.
SELECT substr(assessment_dt_wid, 1, 6)  AS yr_month,
       COUNT(DISTINCT instance_id)      AS declarations,
       COUNT(DISTINCT taxpayer_tin)     AS taxpayers
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20230930'
GROUP BY substr(assessment_dt_wid, 1, 6)
ORDER BY yr_month;


-- ─────────────────────────────────────────────────────────────────────────────────────
-- B. DUPLICATES AND CONSISTENCY
-- ─────────────────────────────────────────────────────────────────────────────────────

-- B1  Are some items in the view more than once?
-- Look for: duplicated_items = 0. If not, the feature query must de-duplicate first,
-- otherwise those declarations count twice.
SELECT COUNT(*) AS duplicated_items, SUM(n - 1) AS extra_rows
FROM (SELECT instance_id, key_itm_nbr, COUNT(*) AS n
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930'
      GROUP BY instance_id, key_itm_nbr
      HAVING COUNT(*) > 1) t;

-- B2  Do the declaration tax amounts repeat on every item, and do they add up?
-- Look for: amounts_differ_across_items = 0 means they repeat, so take them once per
-- declaration (what 01 assumes). final_not_orig_plus_topup and item_topups_dont_add_up
-- should be small, if large, ask which figure is the true top-up before building PAR_048.
SELECT COUNT(*) AS declarations,
       SUM(CASE WHEN n_orig > 1 OR n_topup > 1 OR n_final > 1 THEN 1 ELSE 0 END) AS amounts_differ_across_items,
       SUM(CASE WHEN ABS(final_amt - original_tax_amt - top_up_amt) > 1 THEN 1 ELSE 0 END) AS final_not_orig_plus_topup,
       SUM(CASE WHEN ABS(sum_item_topup - top_up_amt) > 1 THEN 1 ELSE 0 END)               AS item_topups_dont_add_up
FROM (SELECT instance_id,
             COUNT(DISTINCT original_tax_amt) AS n_orig,
             COUNT(DISTINCT top_up_amt)       AS n_topup,
             COUNT(DISTINCT final_amt)        AS n_final,
             MAX(original_tax_amt)            AS original_tax_amt,
             MAX(top_up_amt)                  AS top_up_amt,
             MAX(final_amt)                   AS final_amt,
             SUM(item_top_up)                 AS sum_item_topup
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930'
      GROUP BY instance_id) t;

-- B3  Does the top-up flag agree with the top-up amount?
-- Look for: the off-diagonal cells (flag Y with no amount, or an amount with flag N).
-- Tells us whether to trust the flag or the amount when they disagree.
SELECT top_up_flg,
       CASE WHEN top_up_amt > 0 THEN 'positive' WHEN top_up_amt < 0 THEN 'negative'
            WHEN top_up_amt = 0 THEN 'zero' ELSE 'null' END AS top_up_amount,
       COUNT(DISTINCT instance_id) AS declarations
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY top_up_flg,
         CASE WHEN top_up_amt > 0 THEN 'positive' WHEN top_up_amt < 0 THEN 'negative'
              WHEN top_up_amt = 0 THEN 'zero' ELSE 'null' END
ORDER BY declarations DESC;


-- ─────────────────────────────────────────────────────────────────────────────────────
-- C. IDENTITY
-- ─────────────────────────────────────────────────────────────────────────────────────

-- C1  How many declarations have no TIN, and which TIN is the importer?
-- Look for: the size of no_taxpayer_tin (this activity cannot be scored and is reported,
-- not hidden), and how often taxpayer_tin = consignee_tin.
SELECT COUNT(*) AS declarations,
       SUM(CASE WHEN taxpayer_tin IS NULL OR TRIM(taxpayer_tin) = '' THEN 1 ELSE 0 END)   AS no_taxpayer_tin,
       SUM(CASE WHEN consignee_tin IS NULL OR TRIM(consignee_tin) = '' THEN 1 ELSE 0 END) AS no_consignee_tin,
       SUM(CASE WHEN taxpayer_tin = consignee_tin THEN 1 ELSE 0 END)                      AS same_tin,
       COUNT(DISTINCT taxpayer_tin)                                                        AS distinct_taxpayers
FROM (SELECT DISTINCT instance_id, taxpayer_tin, consignee_tin
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930') t;

-- C2  Do TINs look valid? (length and characters)
-- Look for: lengths other than the standard TIN length, letters, placeholder values
-- such as 0000000000. These are excluded like missing TINs.
SELECT length(TRIM(taxpayer_tin))                         AS tin_length,
       CASE WHEN TRIM(taxpayer_tin) RLIKE '^[0-9]+$' THEN 'digits' ELSE 'other' END AS tin_chars,
       COUNT(DISTINCT taxpayer_tin)                       AS taxpayers,
       COUNT(DISTINCT instance_id)                        AS declarations
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY length(TRIM(taxpayer_tin)),
         CASE WHEN TRIM(taxpayer_tin) RLIKE '^[0-9]+$' THEN 'digits' ELSE 'other' END
ORDER BY declarations DESC;

-- C3  The busiest TINs. Are any of them placeholders or clearing agents?
-- Look for: a TIN with a huge number of declarations and many different names, which
-- suggests a placeholder or a default value rather than a real importer.
SELECT taxpayer_tin,
       COUNT(DISTINCT instance_id)  AS declarations,
       COUNT(DISTINCT taxpayer_nm)  AS names_used,
       MAX(taxpayer_nm)             AS a_name
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY taxpayer_tin
ORDER BY declarations DESC
LIMIT 30;


-- ─────────────────────────────────────────────────────────────────────────────────────
-- D. WHAT IS IN SCOPE: STATUS AND REGIME
-- ─────────────────────────────────────────────────────────────────────────────────────

-- D1  Which statuses exist?
-- Look for: cancelled, rejected, deleted or unassessed declarations. They should not
-- count against a taxpayer. List the values to exclude in the cleaning log.
SELECT decl_status, entry_status, pay_status, sad_current_status,
       COUNT(DISTINCT instance_id) AS declarations
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY decl_status, entry_status, pay_status, sad_current_status
ORDER BY declarations DESC
LIMIT 50;

-- D2  Which regimes and procedure codes exist, and how much tax does each carry?
-- Look for: regimes with little or no duty (exports, transit). The top-up parameters
-- measure duty, so those regimes would dilute every rate. Decide which regimes to score.
SELECT regime_cd, cpc_cd,
       COUNT(DISTINCT instance_id)     AS declarations,
       COUNT(DISTINCT taxpayer_tin)    AS taxpayers,
       SUM(tax_assessed)               AS tax_assessed
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY regime_cd, cpc_cd
ORDER BY declarations DESC
LIMIT 50;


-- ─────────────────────────────────────────────────────────────────────────────────────
-- E. FLAGS
-- ─────────────────────────────────────────────────────────────────────────────────────

-- E1  How are the flags coded, and are they filled in?
-- Look for: Y/N or 1/0, nulls, and flags that are always the same value (useless).
SELECT amendment_flg, top_up_flg, top_up_greater_1_flg, lane_hit_greater_1_flg,
       is_red_flg, is_yellow_flg, is_green_flg, is_blue_flg,
       COUNT(DISTINCT instance_id) AS declarations
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY amendment_flg, top_up_flg, top_up_greater_1_flg, lane_hit_greater_1_flg,
         is_red_flg, is_yellow_flg, is_green_flg, is_blue_flg
ORDER BY declarations DESC
LIMIT 40;

-- E2  Preferential treatment flag and the unexplained inf column
-- Look for: how preferential_treatment_flag is coded, and what inf holds.
SELECT preferential_treatment_flag, inf, COUNT(*) AS item_rows
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY preferential_treatment_flag, inf
ORDER BY item_rows DESC
LIMIT 30;


-- ─────────────────────────────────────────────────────────────────────────────────────
-- F. VALUES, WEIGHTS AND QUANTITIES
-- ─────────────────────────────────────────────────────────────────────────────────────

-- F1  Missing, zero and negative values in the fields the features use
-- Look for: high shares of zero or missing. A field that is mostly empty cannot carry a
-- feature, a negative value is an error to exclude.
SELECT COUNT(*)                                                         AS item_rows,
       AVG(CASE WHEN customs_value IS NULL THEN 1 ELSE 0 END)           AS customs_value_null,
       AVG(CASE WHEN customs_value <= 0 THEN 1 ELSE 0 END)              AS customs_value_zero_or_neg,
       AVG(CASE WHEN net_weight IS NULL OR net_weight <= 0 THEN 1 ELSE 0 END)   AS net_weight_missing,
       AVG(CASE WHEN gross_weight < net_weight THEN 1 ELSE 0 END)       AS gross_below_net,
       AVG(CASE WHEN supplementary_qnty IS NULL OR supplementary_qnty <= 0 THEN 1 ELSE 0 END) AS supp_qty_missing,
       AVG(CASE WHEN hsc_cd IS NULL OR TRIM(hsc_cd) = '' THEN 1 ELSE 0 END)     AS hs_missing,
       AVG(CASE WHEN gds_org_cty IS NULL OR TRIM(gds_org_cty) = '' THEN 1 ELSE 0 END) AS origin_missing,
       AVG(CASE WHEN clearance_station_cd IS NULL THEN 1 ELSE 0 END)    AS station_missing,
       AVG(CASE WHEN tax_assessed < 0 THEN 1 ELSE 0 END)                AS tax_negative
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930';

-- F2  Is customs_value in shillings? Is the dollar conversion sensible?
-- Look for: customs_to_cif_ugx close to 1 (customs value is in UGX), ugx_per_usd should
-- look like a real shilling-dollar rate in every currency row.
SELECT foreign_curr,
       COUNT(*) AS item_rows,
       percentile_approx(customs_value / NULLIF(cif_value_amt_ugx, 0), 0.5)     AS customs_to_cif_ugx,
       percentile_approx(cif_value_amt_ugx / NULLIF(cif_value_amt_usd, 0), 0.5) AS ugx_per_usd
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
GROUP BY foreign_curr
ORDER BY item_rows DESC
LIMIT 15;

-- F3  Spread of declared values and unit values (outliers)
-- Look for: extreme tails. A unit value of 1 shilling per kg, or billions per kg, is almost
-- always a weight or quantity entry error. These would distort the benchmark comparison.
SELECT percentile_approx(customs_value, array(0.01, 0.25, 0.5, 0.75, 0.99))                  AS customs_value_pct,
       percentile_approx(customs_value / net_weight, array(0.001, 0.01, 0.5, 0.99, 0.999))   AS ugx_per_kg_pct,
       percentile_approx(net_weight, array(0.01, 0.5, 0.99))                                 AS net_weight_pct
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930' AND customs_value > 0 AND net_weight > 0;


-- ─────────────────────────────────────────────────────────────────────────────────────
-- G. TAX AND TOP-UPS
-- ─────────────────────────────────────────────────────────────────────────────────────

-- G1  How big are top-ups, and how many declarations carry no tax at all?
-- Look for: the share of zero-tax declarations (exempt or zero-rated, PAR_048 is undefined
-- for them and is treated as missing, not as zero), and the spread of the top-up ratio,
-- which is what PAR_048's thresholds (6% vs 33%) will be set against.
SELECT COUNT(*)                                                      AS declarations,
       AVG(CASE WHEN orig <= 0 THEN 1 ELSE 0 END)                    AS zero_original_tax,
       AVG(CASE WHEN top_up > 0 THEN 1 ELSE 0 END)                   AS with_positive_top_up,
       AVG(CASE WHEN top_up < 0 THEN 1 ELSE 0 END)                   AS with_negative_top_up,
       percentile_approx(CASE WHEN top_up > 0 AND orig > 0 THEN top_up / orig END,
                         array(0.25, 0.5, 0.75, 0.9, 0.99))          AS top_up_over_original_pct,
       percentile_approx(CASE WHEN top_up > 0 AND fin > 0 THEN top_up / fin END,
                         array(0.25, 0.5, 0.75, 0.9, 0.99))          AS top_up_over_final_pct
FROM (SELECT instance_id, MAX(original_tax_amt) AS orig, MAX(top_up_amt) AS top_up, MAX(final_amt) AS fin
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930'
      GROUP BY instance_id) t;

-- G2  How many taxpayers would be scored, by activity level?
-- Look for: how many fall below the 10-entry adequacy threshold (limited history).
SELECT CASE WHEN n < 10 THEN '1-9' WHEN n < 50 THEN '10-49' WHEN n < 200 THEN '50-199'
            WHEN n < 1000 THEN '200-999' ELSE '1000+' END AS entries_24m,
       COUNT(*) AS taxpayers
FROM (SELECT taxpayer_tin, COUNT(DISTINCT instance_id) AS n
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930'
      GROUP BY taxpayer_tin) t
GROUP BY CASE WHEN n < 10 THEN '1-9' WHEN n < 50 THEN '10-49' WHEN n < 200 THEN '50-199'
              WHEN n < 1000 THEN '200-999' ELSE '1000+' END
ORDER BY entries_24m;


-- ─────────────────────────────────────────────────────────────────────────────────────
-- H. FOLLOW-UPS FROM THE FIRST RESULTS
-- ─────────────────────────────────────────────────────────────────────────────────────

-- H1  Duplicated items: what differs between the copies?
-- Why: B1 found 14,215 items repeated about 100 times each. If the copies are identical,
-- keeping one is safe. If a value column differs, we need to know which copy is right.
-- Look for: zeros in the value columns. Non-zero in a status column is expected (it would
-- mean the view joined a status history), and keeping one row is then still safe.
SELECT COUNT(*)                                            AS duplicated_items,
       SUM(CASE WHEN n_val  > 1 THEN 1 ELSE 0 END)         AS customs_value_differs,
       SUM(CASE WHEN n_hs   > 1 THEN 1 ELSE 0 END)         AS hs_differs,
       SUM(CASE WHEN n_wgt  > 1 THEN 1 ELSE 0 END)         AS net_weight_differs,
       SUM(CASE WHEN n_itu  > 1 THEN 1 ELSE 0 END)         AS item_top_up_differs,
       SUM(CASE WHEN n_tin  > 1 THEN 1 ELSE 0 END)         AS tin_differs,
       SUM(CASE WHEN n_dt   > 1 THEN 1 ELSE 0 END)         AS date_differs,
       SUM(CASE WHEN n_st   > 1 THEN 1 ELSE 0 END)         AS decl_status_differs,
       SUM(CASE WHEN n_cur  > 1 THEN 1 ELSE 0 END)         AS current_status_differs,
       SUM(CASE WHEN n_inf  > 1 THEN 1 ELSE 0 END)         AS inf_differs,
       MAX(n)                                              AS most_copies
FROM (SELECT instance_id, key_itm_nbr, COUNT(*) AS n,
             COUNT(DISTINCT customs_value)      AS n_val,
             COUNT(DISTINCT hsc_cd)             AS n_hs,
             COUNT(DISTINCT net_weight)         AS n_wgt,
             COUNT(DISTINCT item_top_up)        AS n_itu,
             COUNT(DISTINCT taxpayer_tin)       AS n_tin,
             COUNT(DISTINCT assessment_dt_wid)  AS n_dt,
             COUNT(DISTINCT decl_status)        AS n_st,
             COUNT(DISTINCT sad_current_status) AS n_cur,
             COUNT(DISTINCT inf)                AS n_inf
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930'
      GROUP BY instance_id, key_itm_nbr
      HAVING COUNT(*) > 1) t;

-- H2  What does top_up_amt actually hold?
-- Why: B3 shows 1.02 million declarations with a positive top_up_amt but top_up_flg = N,
-- against 99,000 with the flag. B2 shows final <> original + top-up on 811,000. Five of the
-- seven scored parameters use top-ups, so we must know which figure is the real top-up.
-- Two explanations are possible, and this query tells them apart:
--   (a) the amounts on flag-N declarations are tiny (rounding), and the flag only marks
--       top-ups above some threshold. Then the amount is fine and the flag is a cut-off.
--   (b) the amounts are large and sit on declarations that were never amended. Then the
--       column holds something other than a top-up, and we use the flag.
-- Look for: in the N / N row (no top-up flag, not amended), small_positive and
-- top_up_amount_pct tell (a) from (b). In the Y / Y row, top_up_equals_final_minus_orig
-- near 1 means (final - original) is the top-up amount.
SELECT top_up_flg, amended,
       COUNT(*)                                                              AS declarations,
       AVG(CASE WHEN top_up > 0 THEN 1.0 ELSE 0.0 END)                       AS positive_top_up,
       AVG(CASE WHEN top_up > 0 AND top_up < 1000 THEN 1.0 ELSE 0.0 END)     AS small_positive_under_1000,
       percentile_approx(CASE WHEN top_up > 0 THEN top_up END,
                         array(0.25, 0.5, 0.75, 0.9))                        AS top_up_amount_pct,
       AVG(CASE WHEN fin > orig THEN 1.0 ELSE 0.0 END)                       AS final_above_orig,
       AVG(CASE WHEN fin = orig THEN 1.0 ELSE 0.0 END)                       AS final_equals_orig,
       AVG(CASE WHEN fin < orig THEN 1.0 ELSE 0.0 END)                       AS final_below_orig,
       AVG(CASE WHEN ABS(top_up - (fin - orig)) <= 1 THEN 1.0 ELSE 0.0 END)  AS top_up_equals_final_minus_orig,
       AVG(CASE WHEN ABS(top_up - fin) <= 1 THEN 1.0 ELSE 0.0 END)           AS top_up_equals_final,
       percentile_approx(CASE WHEN orig > 0 AND top_up > 0 THEN top_up / orig END,
                         array(0.25, 0.5, 0.75, 0.9))                        AS top_up_over_orig_pct
FROM (SELECT instance_id, MAX(top_up_flg) AS top_up_flg, MAX(amendment_flg) AS amended,
             MAX(original_tax_amt) AS orig, MAX(top_up_amt) AS top_up, MAX(final_amt) AS fin
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930'
        AND regime_cd IN ('IM4', 'IM7')
        AND decl_status <> 'Cancelled'
      GROUP BY instance_id) t
GROUP BY top_up_flg, amended
ORDER BY top_up_flg, amended;

-- H3  Where are the declarations with no TIN, and can the consignee TIN fill the gap?
-- Why: 480,000 declarations (20%) have no taxpayer TIN. If most are in regimes we are not
-- scoring, the real gap is smaller. If the consignee TIN is there, it may be usable.
SELECT regime_cd,
       COUNT(*)                                                               AS declarations,
       SUM(no_tin)                                                            AS no_taxpayer_tin,
       SUM(CASE WHEN no_tin = 1 AND consignee_tin RLIKE '^[0-9]{10}$' THEN 1 ELSE 0 END)
                                                                              AS no_tin_but_valid_consignee_tin
FROM (SELECT DISTINCT instance_id, regime_cd, TRIM(consignee_tin) AS consignee_tin,
             CASE WHEN taxpayer_tin IS NULL OR TRIM(taxpayer_tin) = '' THEN 1 ELSE 0 END AS no_tin
      FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
      WHERE assessment_dt_wid > '20240930') t
GROUP BY regime_cd
ORDER BY declarations DESC
LIMIT 25;

-- H4  (optional) The individuals at Busia with 10,000+ declarations: which regime and station?
-- Why: a private person with 17,000 declarations in two years is either a simplified
-- small-trader arrangement or a TIN being used for other people's goods. Which one decides
-- whether they belong in the scored population.
SELECT taxpayer_tin, regime_cd, clearance_station_cd,
       COUNT(DISTINCT instance_id) AS declarations,
       SUM(customs_value)          AS customs_value
FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
WHERE assessment_dt_wid > '20240930'
  AND taxpayer_tin IN ('1037067854', '1056716381', '1039235645', '1010754474')
GROUP BY taxpayer_tin, regime_cd, clearance_station_cd
ORDER BY taxpayer_tin, declarations DESC;


-- =====================================================================================
-- CLEANING LOG  (01_features applies these rules)
-- =====================================================================================
-- Rule  What                                     From     Decision
-- R1    Valid TIN only                           C1, C2   taxpayer_tin RLIKE '^[0-9]{10}$'. Drops the
--                                                         480k blank and the one 3-character TIN.
--                                                         Gap reported in the run summary.
-- R2    Placeholder TINs                         C3       None found among the busiest 30. Names are
--                                                         unreliable (addresses, typos) and not used.
-- R3    Cancelled declarations                   D1       Exclude decl_status = 'Cancelled' (14,065).
--                                                         Keep Assessed / NOT_PAID: they were assessed.
--                                                         Use decl_status, not sad_current_status
--                                                         (often NULL).
-- R4    Regimes scored                           D2       IM4 and IM7 only (see note 1).
-- R5    Duplicated items                         B1, H1   Keep one row per instance_id + key_itm_nbr.
--                                                         H1: copies identical in every column checked.
-- R6    Tax amounts                              B2       Repeat on every item: take once per
--                                                         declaration (confirmed).
-- R7    Top-up definition                        B3, H2   Top-up = flag Y AND final > original.
--                                                         Amount = final - original. top_up_amt is not
--                                                         used: on unflagged declarations it equals the
--                                                         final tax (99.5%). Negative top-up = final <
--                                                         original. Blank original tax = unchanged, so
--                                                         filled with final tax.
-- R8    Valuation features                       F1       Drop items with customs value <= 0 or no
--                                                         weight from valuation only.
-- R9    Unit-value outliers                      F3       Pending F3.
-- R10   Zero-tax declarations                    G1       PAR_048 missing, not zero.
-- R11   Back-test windows                        A2       Every month to Sep 2026 is complete; Oct 2026
--                                                         is partial and excluded. Features to 31 Mar
--                                                         2026, outcomes Apr to Sep 2026; live run to
--                                                         30 Sep 2026.
-- R12   Lane flags                               E1       Coded 1 or NULL (never 0); a declaration can
--                                                         carry several lanes. Test with = 1.
--
-- Note 1: transit and export regimes (IM8, WT8, ST8, EX8, EX1) carry large tax_assessed
-- figures that are guarantees or suspended amounts rather than duty paid, so a top-up ratio
-- there means something different. PB4, PP4 and SE1 have no TINs at all.
-- =====================================================================================
