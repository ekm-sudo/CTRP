-- CTRP EDA report Q7: Which table repeats the item: header, item or inspection rows
-- Run as ONE statement in Hue, download as CSV, save as data/eda_report/Q7.csv
WITH v AS (SELECT instance_id, key_itm_nbr, hsc_cd, regime_cd FROM dm_modeled_ura_datascience.vw_cstm_AEO_model WHERE assessment_dt_wid > '20240930' AND assessment_dt_wid <= '20260930' AND regime_cd IN ('IM4', 'IM7')),
rep AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS copies FROM v
        GROUP BY instance_id, key_itm_nbr HAVING COUNT(*) > 1),
ids AS (SELECT DISTINCT instance_id FROM rep),
veh AS (SELECT instance_id, MAX(CASE WHEN substr(hsc_cd, 1, 4) IN ('8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711') THEN 1 ELSE 0 END) AS has_vehicle,
               MAX(regime_cd) AS regime
        FROM v WHERE instance_id IN (SELECT instance_id FROM ids) GROUP BY instance_id),
hdr AS (SELECT instance_id, COUNT(*) AS n FROM dm_modeled_ura.ft_cstm_decl_hdr WHERE instance_id IN (SELECT instance_id FROM ids)
        GROUP BY instance_id),
itm AS (SELECT instance_id, key_itm_nbr, COUNT(*) AS n FROM dm_modeled_ura.ft_cstm_decl_item_tax
        WHERE instance_id IN (SELECT instance_id FROM ids) GROUP BY instance_id, key_itm_nbr),
insp AS (SELECT instance_id, COUNT(*) AS n FROM awunadm.insp_act_tab_t WHERE instance_id IN (SELECT instance_id FROM ids)
         GROUP BY instance_id)
SELECT COUNT(*) AS repeated_items,
       SUM(CASE WHEN r.copies = COALESCE(h.n, 1) * COALESCE(t.n, 1) * GREATEST(COALESCE(a.n, 0), 1)
                THEN 1 ELSE 0 END) AS copies_explained_by_the_three_tables,
       SUM(CASE WHEN h.n > 1 THEN 1 ELSE 0 END) AS items_whose_header_repeats,
       SUM(CASE WHEN t.n > 1 THEN 1 ELSE 0 END) AS items_whose_item_row_repeats,
       SUM(CASE WHEN a.n > 1 THEN 1 ELSE 0 END) AS items_with_several_inspection_rows,
       MAX(h.n) AS most_header_rows, MAX(t.n) AS most_item_rows, MAX(a.n) AS most_inspection_rows,
       SUM(CASE WHEN x.has_vehicle = 1 THEN 1 ELSE 0 END) AS items_on_vehicle_declarations,
       SUM(CASE WHEN x.regime = 'IM7' THEN 1 ELSE 0 END) AS items_on_im7_declarations
FROM rep r
LEFT JOIN hdr h ON r.instance_id = h.instance_id
LEFT JOIN itm t ON r.instance_id = t.instance_id AND r.key_itm_nbr = t.key_itm_nbr
LEFT JOIN insp a ON r.instance_id = a.instance_id
LEFT JOIN veh x ON r.instance_id = x.instance_id
