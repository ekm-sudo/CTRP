-- Entry-level estimate to replace the rough taxpayer-level "UGX 1.5 trillion": the 2 years to 31 Mar 2026.
-- For every IM4/IM7 declaration, the items priced under HALF of what other importers declare for the same
-- goods (same HS code and origin with 5+ importers, else same HS code with 5+ importers; benchmark = the
-- middle price over the same 2 years, as the model uses), how much more they would be worth at the
-- middle price, and the tax on that at EACH ITEM'S OWN tax rate. Fuel (chapter 27) and prices under 1% of
-- the benchmark (keying errors) are left out. Result: one row per month x checked x topped up (about 100 rows).
-- A CEILING of tax at stake, not proof. Run in Hue as ONE statement, save as data/audit/below_peers_2y_by_month.csv
-- If Hue stops it at 30 minutes, run it twice with one year each (change the two dates in "items" only).
WITH raw AS (
  SELECT v.instance_id, v.key_itm_nbr, v.taxpayer_tin, v.assessment_dt_wid, v.hsc_cd, v.gds_org_cty,
         v.customs_value, v.net_weight, v.supplementary_qnty, v.tax_assessed, v.top_up_flg,
         v.original_tax_amt, v.final_amt, v.is_red_flg, v.is_yellow_flg,
         ROW_NUMBER() OVER (PARTITION BY v.instance_id, v.key_itm_nbr ORDER BY v.assessment_dt_wid) AS rn
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model v
  WHERE v.assessment_dt_wid >  '20240331'
    AND v.assessment_dt_wid <= '20260331'
    AND v.regime_cd IN ('IM4', 'IM7')
    AND v.decl_status <> 'Cancelled'
    AND COALESCE(v.cpc_cd, '') <> '483'
    AND v.taxpayer_tin RLIKE '^[0-9]{10}$'
),
items AS (SELECT * FROM raw WHERE rn = 1),

decl AS (
  SELECT instance_id, substr(MAX(assessment_dt_wid), 1, 6) AS month,
         CASE WHEN COALESCE(CAST(MAX(is_red_flg) AS INT), 0) = 1 OR COALESCE(CAST(MAX(is_yellow_flg) AS INT), 0) = 1 THEN 'Y' ELSE 'N' END AS checked,
         CASE WHEN MAX(top_up_flg) = 'Y' AND MAX(final_amt) > COALESCE(MAX(original_tax_amt), MAX(final_amt)) THEN 'Y' ELSE 'N' END AS topped_up,
         GREATEST(MAX(final_amt) - COALESCE(MAX(original_tax_amt), MAX(final_amt)), 0) AS increase,
         MAX(final_amt) AS final_tax
  FROM items GROUP BY instance_id
),

base AS (
  SELECT * FROM items
  WHERE customs_value > 0 AND net_weight > 0 AND substr(hsc_cd, 1, 2) <> '27'
),
bench_ho AS (
  SELECT hsc_cd, gds_org_cty, percentile_approx(customs_value / net_weight, 0.5) AS med_kg
  FROM base GROUP BY hsc_cd, gds_org_cty HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),
bench_h AS (
  SELECT hsc_cd, percentile_approx(customs_value / net_weight, 0.5) AS med_kg
  FROM base GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),
bench_u AS (
  SELECT hsc_cd, percentile_approx(customs_value / supplementary_qnty, 0.5) AS med_unit
  FROM base WHERE supplementary_qnty > 0 GROUP BY hsc_cd HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),
it AS (
  SELECT b.instance_id, b.customs_value, b.net_weight, b.supplementary_qnty, b.tax_assessed,
         COALESCE(o.med_kg, h.med_kg) AS bm_kg, u.med_unit AS bm_unit
  FROM base b
  JOIN bench_h h ON b.hsc_cd = h.hsc_cd
  LEFT JOIN bench_ho o ON b.hsc_cd = o.hsc_cd AND b.gds_org_cty = o.gds_org_cty
  LEFT JOIN bench_u u ON b.hsc_cd = u.hsc_cd
),
low AS (
  SELECT instance_id,
         COUNT(*) AS items_below,
         SUM(GREATEST(LEAST(bm_kg * net_weight - customs_value,
                            CASE WHEN supplementary_qnty > 0 AND bm_unit IS NOT NULL
                                 THEN bm_unit * supplementary_qnty - customs_value END), 0))      AS shortfall_value,
         SUM(GREATEST(LEAST(bm_kg * net_weight - customs_value,
                            CASE WHEN supplementary_qnty > 0 AND bm_unit IS NOT NULL
                                 THEN bm_unit * supplementary_qnty - customs_value END), 0)
             * (tax_assessed / customs_value))                                                    AS tax_at_stake
  FROM it
  WHERE customs_value / net_weight <  0.5  * bm_kg
    AND customs_value / net_weight >= 0.01 * bm_kg
    AND (bm_unit IS NULL OR supplementary_qnty IS NULL OR supplementary_qnty <= 0
         OR customs_value / supplementary_qnty < 0.5 * bm_unit)
  GROUP BY instance_id
)
SELECT d.month, d.checked, d.topped_up,
       COUNT(*)                                             AS declarations,
       SUM(d.final_tax)                                     AS final_tax,
       SUM(d.increase)                                      AS top_up_amount,
       SUM(CASE WHEN l.instance_id IS NOT NULL THEN 1 ELSE 0 END) AS declarations_below_peers,
       SUM(COALESCE(l.items_below, 0))                      AS items_below_peers,
       SUM(COALESCE(l.shortfall_value, 0))                  AS shortfall_value,
       SUM(COALESCE(l.tax_at_stake, 0))                     AS tax_at_stake
FROM decl d
LEFT JOIN low l ON d.instance_id = l.instance_id
GROUP BY d.month, d.checked, d.topped_up
ORDER BY d.month, d.checked, d.topped_up
