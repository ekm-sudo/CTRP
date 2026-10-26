-- CTRP post-clearance audit list (entries), entries assessed 20260731 to 20260831. Contains TINs: internal use only.
-- Run in Hue as ONE statement, download as CSV, save as data/pca/entries_2026-08.csv
WITH recent_raw AS (
  SELECT COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id) AS entry_key, v.instance_id, v.key_itm_nbr, v.taxpayer_tin, v.taxpayer_nm, v.consignee_tin,
         v.consignee_nm, v.clearance_station_cd, v.dec_ref_yer, v.entry_num, v.assessment_dt_wid, v.regime_cd,
         v.decl_status, v.pay_status, v.extended_proc_cd, v.cpc_cd, v.hsc_cd, v.gds_org_cty,
         CAST(v.customs_value AS DOUBLE) AS customs_value, CAST(v.net_weight AS DOUBLE) AS net_weight,
         CAST(v.supplementary_qnty AS DOUBLE) AS supplementary_qnty, CAST(v.tax_assessed AS DOUBLE) AS tax_assessed,
         CAST(v.original_tax_amt AS DOUBLE) AS original_tax_amt, CAST(v.final_amt AS DOUBLE) AS final_amt,
         v.top_up_flg, v.amendment_flg, v.preferential_treatment_flag,
         CAST(v.is_red_flg AS INT) AS red, CAST(v.is_yellow_flg AS INT) AS yellow,
         CAST(v.is_green_flg AS INT) AS green, CAST(v.is_blue_flg AS INT) AS blue,
         ROW_NUMBER() OVER (PARTITION BY v.instance_id, v.key_itm_nbr ORDER BY v.assessment_dt_wid) AS rn,
         MAX(lpad(v.instance_id, 20, '0')) OVER (PARTITION BY COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id)) AS latest_instance,
         MAX(CASE WHEN substr(v.hsc_cd, 1, 4) IN ('8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711') THEN 1 ELSE 0 END) OVER (PARTITION BY v.instance_id) AS has_vehicle
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20260731' AND v.assessment_dt_wid <= '20260831'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND COALESCE(v.decl_status, '') <> 'Cancelled'
    AND COALESCE(v.cpc_cd, '') <> '483'
    AND v.taxpayer_tin RLIKE '^[0-9]{10}$'
),
recent AS (SELECT * FROM recent_raw
           WHERE rn = 1 AND lpad(instance_id, 20, '0') = latest_instance AND has_vehicle = 0),

-- peers: every importer of the same goods in the 24 months before 1 July 2026, each item once
codes AS (SELECT DISTINCT hsc_cd FROM recent),
peers AS (
  SELECT DISTINCT v.instance_id, v.key_itm_nbr, v.taxpayer_tin, v.hsc_cd, v.gds_org_cty, v.cpc_cd,
         v.extended_proc_cd, v.assessment_dt_wid,
         CAST(v.customs_value AS DOUBLE) AS customs_value, CAST(v.net_weight AS DOUBLE) AS net_weight,
         CAST(v.supplementary_qnty AS DOUBLE) AS supplementary_qnty, CAST(v.tax_assessed AS DOUBLE) AS tax_assessed
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  JOIN codes c ON v.hsc_cd = c.hsc_cd
  WHERE v.assessment_dt_wid > '20240630' AND v.assessment_dt_wid <= '20260630'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND COALESCE(v.decl_status, '') <> 'Cancelled'
    AND v.customs_value > 0
),
bench_h AS (SELECT hsc_cd, percentile_approx(customs_value / net_weight, 0.5) AS med_kg,
                   COUNT(DISTINCT taxpayer_tin) AS importers
            FROM peers WHERE net_weight > 0 GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
bench_ho AS (SELECT hsc_cd, gds_org_cty, percentile_approx(customs_value / net_weight, 0.5) AS med_kg,
                    COUNT(DISTINCT taxpayer_tin) AS importers
             FROM peers WHERE net_weight > 0 GROUP BY hsc_cd, gds_org_cty HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
bench_u AS (SELECT hsc_cd, percentile_approx(customs_value / supplementary_qnty, 0.5) AS med_unit
            FROM peers WHERE supplementary_qnty > 0 GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
bench_duty AS (SELECT hsc_cd, percentile_approx(tax_assessed / customs_value, 0.5) AS med_rate
               FROM peers WHERE cpc_cd = '000' AND tax_assessed >= 0
               GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5),
peer_days AS (SELECT taxpayer_tin, assessment_dt_wid, hsc_cd, COUNT(DISTINCT instance_id) AS n FROM peers
              WHERE substr(hsc_cd, 1, 2) NOT IN ('25', '27') AND COALESCE(extended_proc_cd, '') NOT IN ('4080', '7180')
              GROUP BY taxpayer_tin, assessment_dt_wid, hsc_cd),
split_norm AS (SELECT hsc_cd, SUM(CASE WHEN n >= 2 THEN n ELSE 0 END) / SUM(n) AS norm_share
               FROM peer_days GROUP BY hsc_cd),

-- the same taxpayer, same goods, same day, in the recent entries
days AS (SELECT taxpayer_tin, assessment_dt_wid, hsc_cd, COUNT(DISTINCT instance_id) AS same_day_decl FROM recent
         WHERE substr(hsc_cd, 1, 2) NOT IN ('25', '27') AND COALESCE(extended_proc_cd, '') NOT IN ('4080', '7180')
         GROUP BY taxpayer_tin, assessment_dt_wid, hsc_cd),

-- the taxpayer's first import in the last 5 years
tins AS (SELECT DISTINCT taxpayer_tin FROM recent),
first_seen AS (SELECT v.taxpayer_tin, MIN(v.assessment_dt_wid) AS first_import
               FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v JOIN tins t ON v.taxpayer_tin = t.taxpayer_tin
               WHERE v.assessment_dt_wid > '20210630' AND v.regime_cd IN ('IM4', 'IM7')
                 AND COALESCE(v.decl_status, '') <> 'Cancelled'
               GROUP BY v.taxpayer_tin),

-- every item with its prices, its peers and its signals
it AS (
  SELECT r.*,
         CASE WHEN r.customs_value > 0 AND r.net_weight > 0 THEN r.customs_value / r.net_weight END AS price_kg,
         CASE WHEN r.customs_value > 0 AND r.supplementary_qnty > 0 THEN r.customs_value / r.supplementary_qnty END AS price_unit,
         CASE WHEN substr(r.hsc_cd, 1, 2) <> '27' THEN COALESCE(o.med_kg, h.med_kg) END AS peer_kg,
         CASE WHEN substr(r.hsc_cd, 1, 2) <> '27' THEN u.med_unit END AS peer_unit,
         COALESCE(o.importers, h.importers) AS peer_importers,
         CASE WHEN o.med_kg IS NOT NULL THEN 'HS code and origin' WHEN h.med_kg IS NOT NULL THEN 'HS code' END AS peer_basis,
         CASE WHEN r.customs_value > 0 AND r.tax_assessed >= 0 THEN r.tax_assessed / r.customs_value END AS duty_rate,
         t.med_rate AS peer_duty_rate,
         d.same_day_decl, s.norm_share AS same_day_norm
  FROM recent r
  LEFT JOIN bench_h h ON r.hsc_cd = h.hsc_cd
  LEFT JOIN bench_ho o ON r.hsc_cd = o.hsc_cd AND r.gds_org_cty = o.gds_org_cty
  LEFT JOIN bench_u u ON r.hsc_cd = u.hsc_cd
  LEFT JOIN bench_duty t ON r.hsc_cd = t.hsc_cd
  LEFT JOIN days d ON r.taxpayer_tin = d.taxpayer_tin AND r.assessment_dt_wid = d.assessment_dt_wid AND r.hsc_cd = d.hsc_cd
  LEFT JOIN split_norm s ON r.hsc_cd = s.hsc_cd
),
ratios AS (
  SELECT it.*,
         CASE WHEN price_kg IS NOT NULL AND peer_kg > 0 THEN price_kg / peer_kg END AS price_vs_peers,
         CASE WHEN price_unit IS NOT NULL AND peer_unit > 0 THEN price_unit / peer_unit END AS unit_price_vs_peers,
         CASE WHEN cpc_cd = '000' AND peer_duty_rate > 0 AND duty_rate IS NOT NULL THEN duty_rate / peer_duty_rate END AS duty_vs_peers
  FROM it
),
items AS (
  SELECT ratios.*,
         CASE WHEN price_vs_peers < 0.01 THEN 1 ELSE 0 END AS keying_error,
         CASE WHEN price_vs_peers >= 0.01 AND price_vs_peers < 0.5
                   AND (unit_price_vs_peers IS NULL OR unit_price_vs_peers < 0.5) THEN 1 ELSE 0 END AS low_price,
         CASE WHEN price_vs_peers >= 0.5 AND price_vs_peers < 0.8
                   AND (unit_price_vs_peers IS NULL OR unit_price_vs_peers < 0.8) THEN 1 ELSE 0 END AS some_low_price,
         GREATEST(LEAST(peer_kg * net_weight - customs_value,
                        CASE WHEN supplementary_qnty > 0 AND peer_unit IS NOT NULL
                             THEN peer_unit * supplementary_qnty - customs_value END), 0) AS value_gap,
         CASE WHEN duty_vs_peers < 0.5 THEN 1 ELSE 0 END AS low_duty,
         CASE WHEN duty_vs_peers IS NOT NULL THEN GREATEST(peer_duty_rate * customs_value - tax_assessed, 0) ELSE 0 END AS duty_gap
  FROM ratios
),
scored AS (
  SELECT items.*,
         CASE WHEN low_price = 1 THEN COALESCE(value_gap, 0) * LEAST(COALESCE(duty_rate, 0), 1)
              WHEN low_duty = 1 THEN duty_gap ELSE 0 END AS tax_at_stake
  FROM items
)
SELECT s.entry_key, s.instance_id,
       MAX(s.entry_num) AS entry_num, MAX(s.clearance_station_cd) AS station, MAX(s.dec_ref_yer) AS entry_year,
       to_date(MAX(s.assessment_dt_wid), 'yyyyMMdd') AS assessed_on,
       MAX(s.taxpayer_tin) AS taxpayer_tin, MAX(s.taxpayer_nm) AS taxpayer_nm,
       MAX(s.consignee_tin) AS consignee_tin, MAX(s.consignee_nm) AS consignee_nm,
       MAX(s.regime_cd) AS regime, MAX(s.decl_status) AS status, MAX(s.pay_status) AS pay_status,
       CASE WHEN COALESCE(MAX(s.red), 0) = 1 THEN 'Red' WHEN COALESCE(MAX(s.yellow), 0) = 1 THEN 'Yellow'
            WHEN COALESCE(MAX(s.green), 0) = 1 THEN 'Green' WHEN COALESCE(MAX(s.blue), 0) = 1 THEN 'Blue'
            ELSE 'No flag' END AS lane,
       COALESCE(MAX(s.original_tax_amt), MAX(s.final_amt)) AS original_tax, MAX(s.final_amt) AS final_tax,
       CASE WHEN MAX(s.top_up_flg) = 'Y' AND MAX(s.final_amt) > COALESCE(MAX(s.original_tax_amt), MAX(s.final_amt))
            THEN 'Y' ELSE 'N' END AS topped_up,
       GREATEST(MAX(s.final_amt) - COALESCE(MAX(s.original_tax_amt), MAX(s.final_amt)), 0) AS tax_raised,
       MAX(s.amendment_flg) AS amended,
       COUNT(*) AS items, SUM(s.customs_value) AS customs_value, SUM(s.tax_assessed) AS tax_assessed,
       concat_ws(', ', sort_array(collect_set(s.cpc_cd))) AS apcs,
       concat_ws(', ', sort_array(collect_set(s.extended_proc_cd))) AS epcs,
       COUNT(DISTINCT s.hsc_cd) AS hs_codes,
       -- price
       SUM(s.low_price) AS items_under_half_peer_price,
       SUM(s.some_low_price) AS items_50_80_pct_of_peer_price,
       SUM(s.keying_error) AS items_possible_unit_error,
       MIN(CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_vs_peers,
       min_by(s.hsc_cd, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_hs_code,
       min_by(s.gds_org_cty, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_origin,
       min_by(s.price_kg, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_per_kg,
       min_by(s.peer_kg, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_price_per_kg,
       min_by(s.price_unit, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS lowest_price_per_unit,
       min_by(s.peer_unit, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_price_per_unit,
       min_by(s.peer_basis, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_basis,
       min_by(s.peer_importers, CASE WHEN s.keying_error = 0 THEN s.price_vs_peers END) AS peer_importers,
       SUM(CASE WHEN s.low_price = 1 THEN s.value_gap ELSE 0 END) AS value_gap,
       -- duty
       SUM(s.low_duty) AS items_under_half_peer_duty,
       MIN(s.duty_vs_peers) AS lowest_duty_vs_peers,
       min_by(s.hsc_cd, s.duty_vs_peers) AS lowest_duty_hs_code,
       min_by(s.duty_rate, s.duty_vs_peers) AS lowest_duty_rate,
       min_by(s.peer_duty_rate, s.duty_vs_peers) AS peer_duty_rate,
       SUM(CASE WHEN s.low_duty = 1 THEN s.duty_gap ELSE 0 END) AS duty_gap,
       -- exemptions and preference
       SUM(CASE WHEN COALESCE(s.cpc_cd, '000') <> '000' THEN s.customs_value ELSE 0 END) AS value_under_exemption,
       concat_ws(', ', sort_array(collect_set(CASE WHEN s.cpc_cd IN ('404', '409', '417', '451', '455', '457', '476', '479', '481', '482', '484') THEN s.cpc_cd END))) AS watchlist_apcs,
       SUM(CASE WHEN s.preferential_treatment_flag = 'Y' THEN 1 ELSE 0 END) AS items_claiming_preference,
       -- same-day split
       MAX(s.same_day_decl) AS same_day_same_hs_declarations,
       max_by(s.same_day_norm, s.same_day_decl) AS same_day_norm_for_goods,
       -- new importer
       to_date(MAX(f.first_import), 'yyyyMMdd') AS first_import_in_5_years,
       CASE WHEN MAX(f.first_import) > '20250630' THEN 'Y' ELSE 'N' END AS new_importer,
       SUM(s.tax_at_stake) AS tax_at_stake
FROM scored s
LEFT JOIN first_seen f ON s.taxpayer_tin = f.taxpayer_tin
GROUP BY s.entry_key, s.instance_id
