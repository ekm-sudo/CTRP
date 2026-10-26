-- Audit list 2 of 2, and the "unknown revenue" estimate: every IM4/IM7 declaration since 1 Jul 2026
-- with at least one item priced under HALF of what other importers declare for the same goods.
--
-- Scope (Oct 2026): one declaration per entry (entry number + station + year, latest declaration ID) and no
-- motor vehicle declarations (HS 8701 to 8708 and 8711), as in the model (R14, R15).
-- Benchmark (the "price other importers pay"): the middle price per kg (and per unit, where a
-- quantity is given) of all importers' items over the 24 months BEFORE 1 Jul 2026, for the same HS code
-- and origin where 5+ importers bring it from that origin, otherwise the same HS code from all origins
-- (5+ importers). Fuel (HS chapter 27) is left out: it is priced per litre with specific duties.
-- An item counts as "below peers" when its price per kg is under half the benchmark (and, where a unit
-- quantity is declared, its price per unit is also under half). Prices under 1% of the benchmark are
-- treated as keying errors and left out.
-- Shortfall value = how much more the item would be worth at the benchmark (the smaller of the per-kg
-- and per-unit figures). Tax at stake = shortfall value x the item's own tax rate (tax_assessed / value).
-- This is a CEILING of revenue at risk, not proof: a low price can be legitimate.
-- APCs: the APC(s) on the underpriced items are listed. An item under an exemption APC pays little or no
-- tax, so its tax at stake is small or zero; audit.py lists entries with no tax on those items separately
-- ("Exempt or zero-rated"), because the question for them is whether the exemption was valid.
--
-- One row per declaration (only declarations with a below-peers item). Contains TINs and entry numbers.
-- Run in Hue as ONE statement, download as CSV, save as data/audit/below_peers_since_july.csv
WITH recent_raw AS (
  SELECT v.instance_id, v.key_itm_nbr, v.taxpayer_tin, v.clearance_station_cd, v.dec_ref_yer, v.entry_num,
         v.assessment_dt_wid, v.hsc_cd, v.gds_org_cty, v.cpc_cd, v.customs_value, v.net_weight,
         v.supplementary_qnty, v.tax_assessed, v.top_up_flg, v.original_tax_amt, v.final_amt,
         v.is_red_flg, v.is_yellow_flg,
         ROW_NUMBER() OVER (PARTITION BY v.instance_id, v.key_itm_nbr ORDER BY v.assessment_dt_wid) AS rn,
         MAX(lpad(v.instance_id, 20, '0')) OVER (PARTITION BY COALESCE(concat(v.entry_num, v.clearance_station_cd, v.dec_ref_yer), v.instance_id)) AS latest_instance,   -- R14
         MAX(CASE WHEN substr(v.hsc_cd, 1, 4) IN ('8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711') THEN 1 ELSE 0 END) OVER (PARTITION BY v.instance_id) AS has_vehicle   -- R15
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid > '20260701'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND v.decl_status <> 'Cancelled'
    AND COALESCE(v.cpc_cd, '') <> '483'
    AND v.taxpayer_tin RLIKE '^[0-9]{10}$'
),
recent AS (SELECT * FROM recent_raw WHERE rn = 1
                 AND lpad(instance_id, 20, '0') = latest_instance   -- R14 latest declaration ID per entry
                 AND has_vehicle = 0),                                -- R15 no motor vehicle declarations

-- declaration-level lane and top-up, from all items (before any filter)
decl AS (
  SELECT instance_id,
         MAX(is_red_flg) AS red, MAX(is_yellow_flg) AS yellow, MAX(top_up_flg) AS top_up_flg,
         COALESCE(MAX(original_tax_amt), MAX(final_amt)) AS original_tax, MAX(final_amt) AS final_tax,
         SUM(customs_value) AS decl_value, COUNT(*) AS decl_items
  FROM recent GROUP BY instance_id
),

codes AS (SELECT DISTINCT hsc_cd FROM recent WHERE substr(hsc_cd, 1, 2) <> '27'),

peers AS (
  SELECT DISTINCT v.instance_id, v.key_itm_nbr, v.taxpayer_tin, v.hsc_cd, v.gds_org_cty,
         v.customs_value, v.net_weight, v.supplementary_qnty
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  JOIN codes c ON v.hsc_cd = c.hsc_cd
  WHERE v.assessment_dt_wid >  '20240701'
    AND v.assessment_dt_wid <= '20260701'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND v.decl_status <> 'Cancelled'
    AND v.customs_value > 0 AND v.net_weight > 0
),
bench_ho AS (
  SELECT hsc_cd, gds_org_cty, percentile_approx(customs_value / net_weight, 0.5) AS med_kg,
         COUNT(DISTINCT taxpayer_tin) AS importers
  FROM peers GROUP BY hsc_cd, gds_org_cty HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),
bench_h AS (
  SELECT hsc_cd, percentile_approx(customs_value / net_weight, 0.5) AS med_kg,
         COUNT(DISTINCT taxpayer_tin) AS importers
  FROM peers GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),
bench_u AS (
  SELECT hsc_cd, percentile_approx(customs_value / supplementary_qnty, 0.5) AS med_unit
  FROM peers WHERE supplementary_qnty > 0
  GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),

it AS (
  SELECT r.*,
         COALESCE(o.med_kg, h.med_kg)                         AS bm_kg,
         u.med_unit                                           AS bm_unit,
         COALESCE(o.importers, h.importers)                   AS importers,
         CASE WHEN o.med_kg IS NOT NULL THEN 'same line and origin' ELSE 'same line, all origins' END AS basis
  FROM recent r
  JOIN bench_h h ON r.hsc_cd = h.hsc_cd
  LEFT JOIN bench_ho o ON r.hsc_cd = o.hsc_cd AND r.gds_org_cty = o.gds_org_cty
  LEFT JOIN bench_u u ON r.hsc_cd = u.hsc_cd
  WHERE r.customs_value > 0 AND r.net_weight > 0 AND substr(r.hsc_cd, 1, 2) <> '27'
),
low AS (
  SELECT it.*,
         (customs_value / net_weight) / bm_kg                 AS price_vs_peers,
         LEAST(bm_kg * net_weight - customs_value,
               CASE WHEN supplementary_qnty > 0 AND bm_unit IS NOT NULL
                    THEN bm_unit * supplementary_qnty - customs_value END) AS shortfall_value,
         CASE WHEN customs_value > 0 THEN tax_assessed / customs_value END AS tax_rate
  FROM it
  WHERE customs_value / net_weight <  0.5  * bm_kg
    AND customs_value / net_weight >= 0.01 * bm_kg
    AND (bm_unit IS NULL OR supplementary_qnty IS NULL OR supplementary_qnty <= 0
         OR customs_value / supplementary_qnty < 0.5 * bm_unit)
)
SELECT l.instance_id,
       MAX(l.taxpayer_tin)                                   AS taxpayer_tin,
       MAX(l.clearance_station_cd)                           AS station,
       MAX(l.dec_ref_yer)                                    AS entry_year,
       MAX(l.entry_num)                                      AS entry_num,
       to_date(MAX(l.assessment_dt_wid), 'yyyyMMdd')         AS assessed_on,
       MAX(d.decl_items)                                     AS items_on_declaration,
       COUNT(*)                                              AS items_below_peers,
       MAX(d.decl_value)                                     AS declaration_value,
       SUM(l.customs_value)                                  AS value_of_items_below_peers,
       SUM(GREATEST(l.shortfall_value, 0))                   AS shortfall_value,
       SUM(GREATEST(l.shortfall_value, 0) * COALESCE(l.tax_rate, 0)) AS tax_at_stake,
       MIN(l.price_vs_peers)                                 AS lowest_price_vs_peers,
       MIN(l.importers)                                      AS fewest_importers_in_benchmark,
       MAX(l.hsc_cd)                                         AS example_hs_code,
       concat_ws(', ', sort_array(collect_set(COALESCE(l.cpc_cd, '')))) AS apcs_on_underpriced_items,
       SUM(l.tax_assessed)                                   AS tax_on_underpriced_items,
       CASE WHEN COALESCE(CAST(MAX(d.red) AS INT), 0) = 1 OR COALESCE(CAST(MAX(d.yellow) AS INT), 0) = 1 THEN 'Y' ELSE 'N' END AS checked,
       CASE WHEN MAX(d.top_up_flg) = 'Y' AND MAX(d.final_tax) > MAX(d.original_tax) THEN 'Y' ELSE 'N' END AS topped_up,
       GREATEST(MAX(d.final_tax) - MAX(d.original_tax), 0)  AS top_up_amount
FROM low l
JOIN decl d ON l.instance_id = d.instance_id
GROUP BY l.instance_id
ORDER BY tax_at_stake DESC
