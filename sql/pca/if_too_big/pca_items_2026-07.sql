-- CTRP post-clearance audit list (items with a signal), entries assessed 20260630 to 20260731. Contains TINs: internal use only.
-- Run in Hue as ONE statement, download as CSV, save as data/pca/items_2026-07.csv
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
  WHERE v.assessment_dt_wid > '20260630' AND v.assessment_dt_wid <= '20260731'
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
SELECT entry_key, instance_id, entry_num, clearance_station_cd AS station, dec_ref_yer AS entry_year,
       to_date(assessment_dt_wid, 'yyyyMMdd') AS assessed_on, taxpayer_tin, key_itm_nbr AS item, hsc_cd AS hs_code,
       gds_org_cty AS origin, cpc_cd AS apc, preferential_treatment_flag AS preference,
       customs_value, net_weight, supplementary_qnty AS quantity, tax_assessed,
       price_kg, peer_kg, price_vs_peers, price_unit, peer_unit, unit_price_vs_peers, peer_basis, peer_importers,
       value_gap, duty_rate, peer_duty_rate, duty_vs_peers, duty_gap, tax_at_stake,
       CASE WHEN keying_error = 1 THEN 'Possible unit error' WHEN low_price = 1 THEN 'Under half the peer price'
            WHEN some_low_price = 1 THEN '50-80% of the peer price' ELSE '' END AS price_signal,
       CASE WHEN low_duty = 1 THEN 'Under half the peer duty rate' ELSE '' END AS duty_signal
FROM scored
WHERE keying_error = 1 OR low_price = 1 OR some_low_price = 1 OR low_duty = 1
