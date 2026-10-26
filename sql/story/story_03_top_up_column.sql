-- Story notebook, sample 3 of 3: 10 declarations without the top-up flag and 10 with it (step B2),
-- to show that top_up_amt holds the final tax when the flag is N.
-- Run in Hue as one statement, download as CSV, save as data/samples/story_top_up_column.csv
-- Looks only at 1 to 10 March 2026 to keep it fast.
WITH d AS (
  SELECT instance_id, MAX(top_up_flg) AS top_up_flg, MAX(original_tax_amt) AS original_tax_amt,
         MAX(final_amt) AS final_amt, MAX(top_up_amt) AS top_up_amt, MAX(amendment_flg) AS amendment_flg
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
  WHERE assessment_dt_wid > '20260301' AND assessment_dt_wid <= '20260310'
    AND regime_cd IN ('IM4', 'IM7') AND decl_status <> 'Cancelled'
  GROUP BY instance_id
)
SELECT * FROM (SELECT * FROM d WHERE top_up_flg = 'N' AND final_amt > 0 LIMIT 10) a
UNION ALL
SELECT * FROM (SELECT * FROM d WHERE top_up_flg = 'Y' LIMIT 10) b
