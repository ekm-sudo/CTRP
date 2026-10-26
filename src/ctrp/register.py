"""
Parameter register: every parameter in the lists NTC and the Business Analysis team have shared, and where
each one stands for the taxpayer risk score.

Sources (Ethan, 16 Oct 2026):
  eHub   = "Confirmed in eHub - Risk Parameters" (PAR codes with the eHub table and column)
  BRP    = "Business Risk Profile Parameters" (General, Importer and Agent sheets; Importer "PICKED" column)
  RP     = "RISK PARAMETERS 27 10 2025 amended" (the profile build list with score guides)
  SC     = NTC Business Risk scorecard and Compliance Measurement scorecard
  LANE   = Lane targeting parameters (tiers and thresholds)

Status values:
  Scored                    in Track A now
  Tested: not added         tested on the back-test dates with data we hold; does not improve the ranking
  Tested: small gain, held  slightly better on some measures, worse on others; not enough to add now
  Query written             the view has the data; the add-on query (sql/long_run_addon) fetches it
  Data request              the data is not in our view; where it lives is given
  Not for this score        belongs to another model (entry, agent, commodity, transit, exports) or to
                            the officers' manual review
"""

# (code, parameter, listed in, status, where it stands / result, data needed and where it is)
REGISTER = [
    # ---------------- scored ----------------
    ('PAR_045', '% of IM4/IM7 declarations amended', 'eHub, BRP, RP', 'Scored', 'In Track A (amendment rate).',
     'View: amendment_flg'),
    ('PAR_045T', "Officers' rule: share of declarations topped up", 'Officers', 'Scored', 'Largest weight in Track A.',
     'View'),
    ('PAR_048', 'Top-ups over original tax (IM4 and IM7)', 'eHub, BRP, SC, LANE', 'Scored',
     'In Track A as top-ups over final tax. IM4 and IM7 separately: see the add-on.', 'View'),
    ('PAR_066', '% declarations with negative top-ups', 'eHub, BRP', 'Scored', 'In Track A.', 'View'),
    ('PAR_076', 'Declared unit value against the average for the goods', 'eHub, BRP', 'Scored',
     'In Track A (price against other importers of the same HS code).', 'View'),
    ('PAR_077', 'Declarations with 30% or more added duty', 'eHub, BRP', 'Scored',
     'In Track A for the importer. The agent version needs the agent TIN.', 'View; agent TIN for the agent version'),
    ('PAR_105', 'Importer assessed more duty in the last 90 days (PAR_102 to PAR_104 are other windows)', 'eHub, BRP',
     'Scored', 'In Track A (top-up in the last 180 days). The window lengths are variants of one parameter.', 'View'),
    ('PAR_023', 'Migrations between stations (PAR_024)', 'eHub, BRP', 'Scored',
     'In Track A (clearing away from the main station).', 'View'),
    # ---------------- tested now ----------------
    ('NTC hit rate', 'Hit rate: share of checks that found a top-up', 'SC, RP, LANE', 'Tested: small gain, held',
     'Alone it ranks checks as well as Track A (AUC 0.816 against 0.816). Added at weight 9: +0.0006, better on 7 of '
     '18 dates, worse on 1. Replacing PAR_045T with it is worse on all 18 dates. It repeats what PAR_045T already '
     'says; better shown to officers as information than given points.', 'View (long run)'),
    ('NTC average top-up', 'Average top-up per topped-up declaration (above UGX 15 million)', 'SC, RP, LANE',
     'Tested: not added',
     'Alone AUC 0.64. Added: worse on 10 of 18 dates. A large amount mostly marks a large importer, not a frequent '
     'one.', 'View (long run)'),
    ('PAR_049', 'Value of top-ups', 'eHub', 'Tested: not added',
     'Alone AUC 0.61. Added: worse on 17 of 18 dates (same reason: size).', 'View (long run)'),
    ('PAR_063', 'Number of import declarations', 'eHub', 'Tested: not added',
     'Alone AUC 0.26: the more a taxpayer declares, the LOWER its hit rate per check. Worse on 18 of 18 dates. Size '
     'stays in the peer groups, not in the points.', 'View (long run)'),
    ('LANE IM7', 'Share of declarations into bond (IM7)', 'LANE', 'Tested: not added',
     'Alone AUC 0.33 (bonded traders are topped up less often). Worse on 18 of 18 dates. The lane list\'s "IM7 '
     'ratio" is the top-up ratio at IM7: see the add-on.', 'View (long run)'),
    ('PAR_019', 'First-time importer (PAR_101 the same)', 'eHub', 'Tested: small gain, held',
     'Long run, 18 dates: +0.0015 AUC, better on 10, worse on 2, but precision in the top 5% falls slightly (53.0% '
     'to 52.8%): it helps at the bottom of the list, not the top. Already in Track B as "recently started importing".',
     'View (long run); eHub IS_FIRST_IMPORT would be exact'),
    ('PAR_072', '% of entries declared and not paid within 96 hours', 'eHub, RP, SC', 'Tested: not added',
     'Stand-in "assessed but not paid" (pay_status): alone AUC 0.47, worse on 7 of 7 dates. The 96-hour version '
     'needs the payment date.', 'View (pay_status); payment date for the exact version'),
    ('PAR_050', '% of declarations using preferential treatment (PAR_087 the same)', 'eHub, BRP', 'Tested: not added',
     'Alone AUC 0.40, worse on 6 of 7 dates. Kept as Track B information.', 'View'),
    ('PAR_062', 'Country of origin', 'eHub, RP, SC', 'Tested: not added (count); record-based version in the add-on',
     "Number of origins: alone AUC 0.37, worse on 7 of 7. The add-on measures the past hit rate of the taxpayer's "
     "origins and goods instead, and NTC's country list.", 'View'),
    ('NTC nature of imports', 'Number of different goods (HS headings)', 'RP, SC',
     'Tested: not added (count); sensitive goods in the add-on', 'Alone AUC 0.48, worse on 7 of 7.', 'View'),
    ('NTC APCs', 'Number of APCs used', 'RP, SC', 'Tested: not added (count); depth of exemption in the add-on',
     'Alone AUC 0.32, worse on 7 of 7.', 'View'),
    ('PAR_052', '% of entries with exempted goods', 'eHub', 'Tested: not added',
     'Share of value under exemption APCs: alone AUC 0.32, worse on 4 of 4. Exempt importers are topped up less, as '
     'expected: little tax to top up. The add-on splits full from partial exemption.', 'View'),
    ('PAR_053', 'Value of tax forgone through exemptions', 'eHub, BRP', 'Query written',
     'Watch-list APC share tested: no change. The add-on measures tax relief against the normal rate for the goods.',
     'View (add-on)'),
    ('PAR_067', '% of declarations where the unit value was reduced', 'eHub, BRP', 'Tested: not added',
     'Stand-in "price dropped against own history": alone AUC 0.41, no gain. The exact version needs earlier '
     'versions of each declaration.', 'View; declaration versions for the exact version'),
    ('PAR_096', 'HS code changes that lowered duty (PAR_097 to PAR_099 variants)', 'eHub, BRP',
     'Tested: small gain, held',
     'Stand-in "duty shortfall against HS peers": +0.0012 AUC, better on 3 of 4, worse on none, but top 5% precision '
     'falls 0.4 points. The exact version needs the HS code before and after (WC_CSTM_DECL_ITEM_F).',
     'eHub: DWH_CORE.WC_CSTM_DECL_ITEM_F (HS code versions)'),
    ('PAR_090', 'Unit value against EACCIS weighted average', 'eHub, BRP', 'Tested: not added',
     'NTC did not pick it (similar to PAR_076). Stand-in "prices far from other importers": +0.0005, better on 1 of '
     '4.', 'EACCIS data'),
    ('Splitting', 'Same-day splitting above the norm', 'Officers', 'Tested: not added',
     'Alone AUC 0.42, worse on 4 of 4. Stays in Track B.', 'View'),
    # ---------------- add-on query ----------------
    ('PAR_026', '% of entries with sensitive commodities (PAR_027, PAR_028)', 'eHub, BRP, RP, SC', 'Query written',
     'Add-on: value and declarations on the EAC CET 2022 Sensitive Items list (50 lines). eHub also has '
     'IS_SENSITIVE, which may use a wider list.', 'View (add-on); eHub IS_SENSITIVE'),
    ('NTC APCs depth', 'APCs exempting all taxes (10) or one tax head (5)', 'RP, SC', 'Query written',
     'Add-on: value under an APC with no tax at all, value with some tax, and the tax relief.', 'View (add-on)'),
    ('PAR_083', 'Goods from particular countries (PAR_089, NTC origin)', 'eHub, RP, SC', 'Query written',
     "Add-on: past hit rate of the same origin and HS chapter (only earlier half-years), and NTC's country list for "
     'comparison.', 'View (add-on)'),
    ('LANE ratios', 'Top-up ratio at IM4 and at IM7 separately', 'LANE, BRP', 'Query written',
     'Add-on: top-ups and original tax by regime.', 'View (add-on)'),
    ('NTC scorecard', 'NTC Business Risk scorecard as a whole', 'SC', 'Tested as a challenger',
     "The rows the data supports (hit rate, top-up ratio, average top-up, with NTC's points and weights): AUC 0.80 "
     'against Track A 0.82, lower on all 18 dates; precision in the top 5% 33% against 53%. Lane targeting '
     'thresholds: AUC 0.71 (Tier 1), 0.75 (Tier 2), 0.77 (Tier 3). Nature of imports, APCs and origin are added when '
     'the add-on returns.', 'View'),
    # ---------------- data requests: our view, from DWH_CORE (eHub confirmed) ----------------
    ('PAR_039', 'Number of penalties (PAR_041 seizures in 90 days)', 'eHub, BRP, RP, SC', 'Data request',
     'NTC gives offences the most weight after the compliance score (5 for number, 10 for nature). Blocked in Track '
     'A.', 'eHub: DWH_CORE.VW_CSTM_SEIZURE_F (confirmed)'),
    ('PAR_040', 'Value of penalties collected', 'eHub, BRP', 'Data request', 'Blocked in Track A.',
     'eHub: DWH_CORE.VW_CSTM_SEIZURE_F (confirmed)'),
    ('NTC offences', 'Nature of offences (sections 194, 199, 200, 202)', 'RP, SC', 'Data request', 'NTC weight 10.',
     'Seizure report (offence section)'),
    ('PAR_043', '% of entries handled by risky agents (PAR_044)', 'eHub, BRP, SC', 'Data request',
     "With the agent TIN we can define a risky agent from the data (its clients' top-up record), which eHub says is "
     'pending.', 'eHub: DWH_CORE.VW_AEO_CSTM_DECL_ITEM_F, AGENT_TIN (confirmed), IS_AGENT_RISKY (pending definition)'),
    ('PAR_173', 'Agents with over 3 risky taxpayers (PAR_065, PAR_042)', 'eHub, BRP', 'Data request',
     'Blocked in Track A; belongs mainly to the agent profile.', 'eHub: AGENT_TIN'),
    ('PAR_078', 'Agent assessed more duty in the last 30 days (PAR_079, PAR_080)', 'eHub, BRP', 'Data request',
     'Blocked in Track A; agent profile.', 'eHub: AGENT_TIN'),
    ('PAR_015', '% of declarations with undervaluation risk identified', 'eHub, BRP, RP', 'Data request',
     'NTC picked it (Importer sheet). Blocked in Track A.',
     'eHub: DWH_CORE.VW_AEO_CSTM_DECL_ITEM_F, IS_UNDER_VALUED (confirmed)'),
    ('PAR_016', '% of declarations misclassified', 'eHub, BRP', 'Data request', 'NTC picked it. Blocked in Track A.',
     'eHub: DWH_CORE.WC_CSTM_DECL_HDR_F, IS_MISCLASSIFIED (confirmed)'),
    ('PAR_012', 'Original against final declaration (PAR_010, PAR_011)', 'eHub, BRP', 'Data request',
     'NTC picked it. Blocked in Track A. Also unlocks PAR_051, PAR_054, PAR_084, PAR_086, PAR_088.',
     'eHub: DWH_CORE.VW_ERM_CSTM_DECL_ITEM_F, VARIANCE_ORIG_FINAL_VALUE (being added)'),
    ('PAR_051', 'Preferential-rate declarations amended', 'eHub, BRP', 'Data request',
     'NTC picked it. Needs the declaration versions (box 36).', 'eHub: declaration versions'),
    ('PAR_054', '% of declarations with amended APCs', 'eHub, BRP', 'Data request',
     'NTC picked it. Needs the declaration versions.', 'eHub: declaration versions'),
    ('PAR_084', 'Origin changed by an officer in the last 90 days (PAR_086, PAR_088)', 'eHub', 'Data request',
     'Needs the declaration versions.', 'eHub: declaration versions'),
    ('PAR_017', '% of entries with high-risk commodities (PAR_018)', 'eHub, BRP, RP, SC', 'Data request',
     'NTC gives risky goods 10 points but the list was not shared.',
     "eHub: DWH_CORE.VW_AEO_CSTM_DECL_ITEM_F, IS_HIGH_RISK (confirmed), or NTC's list"),
    ('PAR_029', '% of entries with high-value goods (PAR_030)', 'eHub, BRP', 'Data request',
     'Note: size measures lowered the ranking in every test above.', 'eHub: IS_HIGH_VALUE (confirmed)'),
    ('PAR_035', 'Individuals importing sensitive or high-value goods (PAR_036)', 'eHub', 'Data request', '',
     'eHub: TAXPAYER_TYPE_CD, IS_SENSITIVE (confirmed)'),
    ('PAR_075', 'Customs value against statistical value (boxes 45 and 46)', 'eHub, BRP', 'Data request',
     'NTC rank 8. Blocked in Track A.', 'Boxes 45 and 46 (not located in eHub yet)'),
    ('PAR_001', '% of declarations failing the value test (PAR_002 to PAR_009)', 'eHub, BRP', 'Data request (low)',
     'NTC did not pick it: the value guide (TSC) is unreliable.',
     'eHub: DWH_CORE.VW_ERM_CSTM_DECL_ITEM_F, VALUE_FAILURE_FLAG, IS_BELOW_TSC, IS_ABOVE_TSC (confirmed)'),
    ('PAR_094', 'Related-party transactions in the last 90 days (PAR_095); supplier relationship', 'eHub, RP, SC',
     'Data request', 'NTC: related supplier and importer = 5 points, weight 5.',
     'Supplier name and relationship indicator (valuation declaration)'),
    ('PAR_082', 'Country of export (PAR_081 destination)', 'eHub', 'Data request (low)', '',
     'eHub: DWH_CORE.WC_CSTM_DECL_HDR_F'),
    ('PAR_073', 'FOB value of goods', 'eHub', 'Data request (low)', 'A size measure.',
     'eHub: DWH_CORE.WC_CSTM_DECL_HDR_F'),
    ('PAR_013', 'Original against final manifest', 'eHub', 'Data request', '', 'Manifest data'),
    ('PAR_004', 'Data-related errors (PAR_005)', 'eHub', 'Data request', 'Needs a definition of "data error".',
     'Not located'),
    ('PAR_074', 'FOB against SGS information', 'eHub, BRP', 'Data request (low)',
     'NTC did not pick it (not relevant for road and air).', 'SGS data'),
    # ---------------- data requests: other systems ----------------
    ('PAR_123', 'VAT sales, income tax sales, EFRIS against ASYCUDA imports', 'BRP, RP, SC', 'Data request',
     'NTC: three Domestic Tax variance rows (CIF against the income tax return, the VAT input schedule, exports '
     'against VAT output), weight 5 each.', 'e-tax returns, EFRIS'),
    ('PAR_136', 'High customs-value importers not registered for VAT or income tax (PAR_137)', 'BRP', 'Data request',
     'NTC picked it.', 'e-tax registration'),
    ('PAR_134', '% of NIL returns by importers', 'BRP', 'Data request', 'NTC picked it.', 'e-tax returns'),
    ('PAR_071', 'TINs sharing registration details (PAR_121, PAR_069, PAR_070)', 'eHub, BRP', 'Data request',
     'Network risk (shared directors, phones, emails, bank details).', 'e-tax registration'),
    ('PAR_068', 'Change of location in the last 90 days', 'eHub', 'Data request', '', 'e-tax registration history'),
    ('NTC registration', 'Accuracy of registration details; missing bank details', 'RP, SC', 'Data request', '',
     'e-tax'),
    ('NTC tier', 'Taxpayer tier', 'LANE', 'Data request',
     "NTC's lane thresholds differ by tier; without the tier each tier's thresholds were applied to everyone.",
     'e-tax / segmentation'),
    ('NTC DT audits', 'Domestic Tax audits and recoveries; arrears', 'RP, SC', 'Data request', '',
     'e-tax audit reports, ledger'),
    ('NTC audits', 'Customs post-clearance audits and recoveries', 'RP, SC', 'Data request',
     'Mostly on paper (DECISIONS 97). Also a less biased outcome than top-ups.', 'Audit team Excel'),
    ('PAR_113', 'Fraud history; investigations', 'BRP, RP, SC', 'Data request', 'NTC picked it.',
     'Tax Investigations Department'),
    ('NTC legal', 'Legal cases with URA', 'RP, SC', 'Data request', '', 'Legal'),
    ('NTC compliance score',
     'Compliance measurement score (documents, tariff, valuation, origin, APC, quantities, description, payment)', 'SC',
     'Data request',
     'Scored by officers on sampled entries. Past scores per taxpayer would be a check on the model that does not '
     'depend on top-ups.', 'NTC files'),
    ('NTC alerts', 'Business analysis alerts, NII alerts, seizure fines', 'LANE', 'Data request', '', 'NTC, NII'),
    # ---------------- not for this score ----------------
    ('PAR_025',
     'First-time exporter; exports (PAR_031 to PAR_034, PAR_037, PAR_038, PAR_046, PAR_060, PAR_061, PAR_064, '
     'PAR_091)', 'eHub', 'Not for this score',
     'Export risk: a separate profile. The view has export declarations if needed.', 'View'),
    ('PAR_055', 'Fuel entering through other stations', 'eHub', 'Not for this score', 'An entry rule for selectivity.',
     'View'),
    ('PAR_056', 'Transit destination and transit time (PAR_057)', 'eHub', 'Not for this score', 'Transit model.',
     'eHub: WC_CSTM_TRANSIT_HDR_F'),
    ('PAR_058', 'Red-lane entries cleared below the standard time', 'eHub', 'Not for this score',
     'Measures officers, not taxpayers.', 'Process times'),
    ('PAR_059', 'Warehousing entries ex-warehoused within 48 hours (PAR_047 amendments)', 'eHub', 'Not for this score',
     'Warehouse model.', 'eHub: WC_CSTM_WAREHOUSE_ITEM_F'),
    ('PAR_020', 'First, second, third time agent / transporter / warehouse / station / HS / origin (PAR_021, PAR_022)',
     'eHub', 'Not for this score', 'Entry-level rules; eHub says the definition is pending.', 'eHub: FIRST_IMPORT_DT'),
    ('PAR_108', 'Regime on the declaration', 'eHub', 'Not for this score', 'Context for entry selectivity.', 'View'),
    ('NTC documents', 'Attached documents, quantities, description, container numbers', 'RP, SC', 'Not for this score',
     "Officers' manual review of sampled entries.", 'ASYCUDA attachments'),
    ('NTC points', 'Entry points, exit points, warehouses, export destinations', 'RP', 'Not for this score',
     'Descriptive in the profile; NTC gives them no points.', 'View'),
]

COLUMNS = ['Code', 'Parameter', 'Listed in', 'Status', 'Where it stands', 'Data needed and where it is']

# What to ask for first, and why. Priority follows (1) the weight NTC gives the item, (2) how many blocked
# parameters it unlocks, (3) whether eHub has already confirmed where it is (an easier request).
DATA_REQUEST = [
    (1, 'Seizures, penalties and offence sections', 'DWH_CORE.VW_CSTM_SEIZURE_F (eHub confirmed)',
     'PAR_039, PAR_040, PAR_041; NTC offences',
     'NTC weights offences 5 (number) and 10 (nature), more than any history row. Two of the 11 blocked parameters.'),
    (2, 'Agent TIN on each declaration', 'DWH_CORE.VW_AEO_CSTM_DECL_ITEM_F, AGENT_TIN (eHub confirmed)',
     'PAR_043, PAR_044, PAR_042, PAR_065, PAR_173, PAR_078 to PAR_080; NTC agent compliance',
     'One column unlocks the whole agent family (two blocked parameters) and lets us define a risky agent from the '
     'data.'),
    (3, 'Declaration versions: original against final value, HS code, APC, origin, preference',
     'DWH_CORE.VW_ERM_CSTM_DECL_ITEM_F, VARIANCE_ORIG_FINAL_VALUE (being added); DWH_CORE.WC_CSTM_DECL_ITEM_F',
     'PAR_012, PAR_010, PAR_011, PAR_051, PAR_054, PAR_084, PAR_086, PAR_088, PAR_096 to PAR_099, exact PAR_067',
     'Unlocks five blocked parameters, three of them picked by NTC.'),
    (4, 'Undervaluation and misclassification flags',
     'VW_AEO_CSTM_DECL_ITEM_F.IS_UNDER_VALUED; WC_CSTM_DECL_HDR_F.IS_MISCLASSIFIED (eHub confirmed)',
     'PAR_015, PAR_016',
     'Both picked by NTC and both blocked; eHub has confirmed the columns, so this should be a small change to our '
     'view.'),
    (5,
     'e-tax: tier, VAT and income tax registration, returns (CIF, VAT input and output schedules), NIL returns, '
     'arrears', 'e-tax, EFRIS', 'PAR_123, PAR_134, PAR_136, PAR_137; NTC Domestic Tax rows; lane tier',
     "Three NTC rows at weight 5 each, and the tier that NTC's lane thresholds depend on."),
    (6, 'Boxes 45 (adjustment) and 46 (statistical value)', 'Not located in eHub yet', 'PAR_075',
     'NTC rank 8; blocked.'),
    (7, "High-risk commodity flag or NTC's risky-goods list; sensitive flag",
     'VW_AEO_CSTM_DECL_ITEM_F.IS_HIGH_RISK, IS_SENSITIVE (eHub confirmed)', 'PAR_017, PAR_018, PAR_026 to PAR_028',
     'NTC gives risky goods 10 points. Sensitive goods are already testable from the CET list.'),
    (8, 'Supplier name and related-party indicator', 'Valuation declaration',
     'PAR_094, PAR_095; NTC supplier relationship', 'NTC weight 5.'),
    (9, 'Customs audits, investigations, legal cases', 'Audit team Excel, TID, Legal',
     'PAR_113; NTC audit, investigation, legal rows',
     'Mostly on paper. Post-clearance audit findings would also be a less biased outcome than top-ups.'),
    (10, 'NTC compliance measurement scores per taxpayer', 'NTC files', 'NTC compliance score (weight 20)',
     "The heaviest row in NTC's scorecard; past scores would test the model against something other than top-ups."),
]
DATA_REQUEST_COLUMNS = ['Priority', 'What', 'Where it is', 'Parameters it unlocks', 'Why this priority']
