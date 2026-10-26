-- CTRP EDA report Q5: Copies of an item against the inspection actions on its declaration
-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/Q5.csv
WITH v AS (SELECT instance_id, key_itm_nbr, sad_sid, op_date_time, inf FROM dm_modeled_ura_datascience.vw_cstm_AEO_model WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930' AND regime_cd IN ('IM4', 'IM7')),
actions AS (SELECT instance_id, size(collect_set(struct(sad_sid, op_date_time, inf))) AS inspection_actions
            FROM v WHERE sad_sid IS NOT NULL OR op_date_time IS NOT NULL OR inf IS NOT NULL
            GROUP BY instance_id),
items AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies FROM v GROUP BY instance_id, key_itm_nbr)
SELECT COUNT(*) AS repeated_items,
       SUM(CASE WHEN i.copies = GREATEST(COALESCE(a.inspection_actions, 0), 1) THEN 1 ELSE 0 END)
           AS copies_equal_inspection_actions,
       MAX(i.copies) AS most_copies
FROM items i LEFT JOIN actions a ON i.instance_id = a.instance_id
WHERE i.copies > 1
