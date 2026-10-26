-- =====================================================================================
-- Track B (discovery) features at @@SNAP_DATE@@, one row per taxpayer
-- Reads the cleaned item table ctrp_items (built once per snapshot by the Zeppelin notebook,
-- with the same cleaning rules as the main extract) and the view itself for first-seen dates.
-- History window: items after @@HIST_START@@ up to @@SNAP@@. Recent window: the last 6 months.
-- No input records what customs did (no top-ups, no lanes): Track B measures behaviour only.
-- =====================================================================================
WITH hist AS (
  SELECT * FROM ctrp_items WHERE assessment_dt_wid > '@@HIST_START@@' AND assessment_dt_wid <= '@@SNAP@@'
),

-- What: each taxpayer's first ever IM4 or IM7 declaration up to the snapshot (whole view).
-- Why:  "new" must mean new to customs, not new to the window.
first_seen AS (
  SELECT taxpayer_tin AS tin, MIN(assessment_dt_wid) AS first_dt
  FROM dm_modeled_ura_datascience.vw_cstm_AEO_model
  WHERE assessment_dt_wid <= '@@SNAP@@'
    AND regime_cd IN ('IM4', 'IM7')
    AND decl_status <> 'Cancelled'
    AND taxpayer_tin RLIKE '^[0-9]{10}$'
  GROUP BY taxpayer_tin
),

-- (1, 2) pace: value and declarations per active month, and the last 90 days of value
pace AS (
  SELECT taxpayer_tin AS tin,
         SUM(customs_value) / COUNT(DISTINCT substr(assessment_dt_wid, 1, 6))          AS value_per_active_month,
         COUNT(DISTINCT instance_id) / COUNT(DISTINCT substr(assessment_dt_wid, 1, 6))  AS entries_per_active_month,
         SUM(CASE WHEN adate > date_sub(DATE '@@SNAP_DATE@@', 90) THEN customs_value ELSE 0 END) AS value_last_90d,
         SUM(customs_value)                                                             AS value_hist
  FROM hist
  GROUP BY taxpayer_tin
),

-- (3) duty rate per tariff line: median rate other importers pay with no exemption (APC 000)
line_rate AS (
  SELECT hsc_cd, substr(hsc_cd, 1, 4) AS heading,
         percentile_approx(tax_assessed / customs_value, 0.5) AS med_rate
  FROM hist
  WHERE customs_value > 0 AND tax_assessed >= 0 AND cpc_cd = '000'
  GROUP BY hsc_cd
  HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),

-- headings whose lines carry different duty: the cheapest line, and how wide the gap is
heading_low AS (
  SELECT heading, MIN(med_rate) AS low_rate, MAX(med_rate) AS high_rate
  FROM line_rate
  GROUP BY heading
  HAVING MAX(med_rate) - MIN(med_rate) >= 0.05
),

items_h AS (
  SELECT i.taxpayer_tin AS tin, h.heading, i.customs_value,
         CASE WHEN r.med_rate <= h.low_rate THEN 1 ELSE 0 END AS on_low_line
  FROM hist i
  JOIN line_rate r ON i.hsc_cd = r.hsc_cd
  JOIN heading_low h ON r.heading = h.heading
  WHERE i.customs_value > 0 AND i.cpc_cd = '000'
),

-- the share of value all importers put on the cheapest line of each heading
heading_norm AS (
  SELECT heading, SUM(on_low_line * customs_value) / SUM(customs_value) AS norm_low_share
  FROM items_h
  GROUP BY heading
),

low_line AS (
  SELECT i.tin,
         SUM(i.on_low_line * i.customs_value) / SUM(i.customs_value)          AS low_line_share,
         SUM(n.norm_low_share * i.customs_value) / SUM(i.customs_value)       AS low_line_expected,
         SUM(i.on_low_line * i.customs_value) / SUM(i.customs_value)
           - SUM(n.norm_low_share * i.customs_value) / SUM(i.customs_value)   AS low_line_excess,
         SUM(i.customs_value)                                                AS low_line_value_tested
  FROM items_h i
  JOIN heading_norm n ON i.heading = n.heading
  GROUP BY i.tin
),

-- (4) profile drift: recent value in chapters or origins not seen in the 18 months before
early_ch AS (
  SELECT DISTINCT taxpayer_tin AS tin, substr(hsc_cd, 1, 2) AS ch
  FROM hist WHERE adate <= add_months(DATE '@@SNAP_DATE@@', -6)
),
early_or AS (
  SELECT DISTINCT taxpayer_tin AS tin, gds_org_cty AS org
  FROM hist WHERE adate <= add_months(DATE '@@SNAP_DATE@@', -6)
),
recent AS (
  SELECT taxpayer_tin AS tin, substr(hsc_cd, 1, 2) AS ch, gds_org_cty AS org, customs_value
  FROM hist WHERE adate > add_months(DATE '@@SNAP_DATE@@', -6)
),
drift AS (
  SELECT r.tin,
         SUM(CASE WHEN c.ch IS NULL THEN r.customs_value ELSE 0 END) / NULLIF(SUM(r.customs_value), 0)  AS new_chapter_value_share,
         SUM(CASE WHEN o.org IS NULL THEN r.customs_value ELSE 0 END) / NULLIF(SUM(r.customs_value), 0) AS new_origin_value_share,
         COUNT(*)                                                                                       AS recent_items
  FROM recent r
  LEFT JOIN early_ch c ON r.tin = c.tin AND r.ch = c.ch
  LEFT JOIN early_or o ON r.tin = o.tin AND r.org = o.org
  GROUP BY r.tin
),

-- (5) quantity: kilograms per unit against the norm for the tariff line
kgpu_norm AS (
  SELECT hsc_cd, percentile_approx(net_weight / supplementary_qnty, 0.5) AS med_kgpu
  FROM hist
  WHERE net_weight > 0 AND supplementary_qnty > 0
  GROUP BY hsc_cd
  HAVING COUNT(DISTINCT taxpayer_tin) >= 5
),
qty AS (
  SELECT i.taxpayer_tin AS tin,
         SUM(CASE WHEN i.net_weight / i.supplementary_qnty > 3 * n.med_kgpu
                   AND i.net_weight / i.supplementary_qnty <= 100 * n.med_kgpu
                  THEN i.customs_value ELSE 0 END) / NULLIF(SUM(i.customs_value), 0) AS heavy_per_unit_value_share,
         COUNT(*)                                                                    AS items_unit_tested
  FROM hist i
  JOIN kgpu_norm n ON i.hsc_cd = n.hsc_cd
  WHERE i.net_weight > 0 AND i.supplementary_qnty > 0
  GROUP BY i.taxpayer_tin
),

-- (6) preference claimed on an origin outside the preference area (list to be confirmed by
-- the Risk Officers: EAC and COMESA partner states, ISO two-letter codes)
pref AS (
  SELECT taxpayer_tin AS tin,
         SUM(CASE WHEN preferential_treatment_flag = 'Y' AND gds_org_cty NOT IN (@@PREF_ORIGINS@@)
                  THEN customs_value ELSE 0 END)
           / NULLIF(SUM(CASE WHEN preferential_treatment_flag = 'Y' THEN customs_value ELSE 0 END), 0)
                                                                     AS pref_outside_area_share
  FROM hist
  GROUP BY taxpayer_tin
),

-- (7) exemption codes: the longest span, in months, over which one exemption APC kept being used
apc_span AS (
  SELECT taxpayer_tin AS tin, cpc_cd,
         months_between(to_date(MAX(assessment_dt_wid), 'yyyyMMdd'), to_date(MIN(assessment_dt_wid), 'yyyyMMdd')) AS span_months,
         COUNT(DISTINCT substr(assessment_dt_wid, 1, 6))                                                       AS months_used
  FROM hist
  WHERE cpc_cd <> '000'
  GROUP BY taxpayer_tin, cpc_cd
),
apc_tp AS (
  SELECT tin, MAX(span_months) AS exemption_longest_span_months, MAX(months_used) AS exemption_most_months_used
  FROM apc_span
  GROUP BY tin
),

-- (8) revenue at stake: the share of value in tariff lines where peers pay 25% or more
exposure AS (
  SELECT i.taxpayer_tin AS tin,
         SUM(CASE WHEN r.med_rate >= 0.25 THEN i.customs_value ELSE 0 END) / NULLIF(SUM(i.customs_value), 0) AS high_duty_value_share
  FROM hist i
  JOIN line_rate r ON i.hsc_cd = r.hsc_cd
  WHERE i.customs_value > 0
  GROUP BY i.taxpayer_tin
)

SELECT p.tin                                   AS taxpayer_tin,
       '@@SNAP_DATE@@'                         AS snapshot_date,
       f.first_dt                              AS first_declaration_date,
       CASE WHEN f.first_dt > '@@NEW_SINCE@@' THEN 'Y' ELSE 'N' END AS new_in_last_12m,
       p.value_per_active_month, p.entries_per_active_month, p.value_last_90d, p.value_hist,
       l.low_line_share, l.low_line_expected, l.low_line_excess, l.low_line_value_tested,
       d.new_chapter_value_share, d.new_origin_value_share, d.recent_items,
       q.heavy_per_unit_value_share, q.items_unit_tested,
       pr.pref_outside_area_share,
       a.exemption_longest_span_months, a.exemption_most_months_used,
       e.high_duty_value_share
FROM pace p
LEFT JOIN first_seen f ON f.tin = p.tin
LEFT JOIN low_line l   ON l.tin = p.tin
LEFT JOIN drift d      ON d.tin = p.tin
LEFT JOIN qty q        ON q.tin = p.tin
LEFT JOIN pref pr      ON pr.tin = p.tin
LEFT JOIN apc_tp a     ON a.tin = p.tin
LEFT JOIN exposure e   ON e.tin = p.tin
