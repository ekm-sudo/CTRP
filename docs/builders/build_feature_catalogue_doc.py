"""
Build the CTRP data and feature catalogue in the URA house format: docs/CTRP_Data_and_Feature_Catalogue.docx.

What: what Data Governance asks of a model: the data sources, every feature with its definition, the lineage from
      ASYCUDA to the final score, the data quality rules, and the access controls. Written so a reader with no
      customs or data background can follow it.
Why:  the model's data must be documented before it goes into production.

    python docs/builders/build_feature_catalogue_doc.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'src'))
from ura_doc import UraDoc  # noqa: E402
from ctrp import eda_note as N  # noqa: E402

OUT = ROOT / 'docs' / 'CTRP_Data_and_Feature_Catalogue.docx'
VERSION = '1.0'
DATE = '22 October 2026'
VIEW = 'dm_modeled_ura_datascience.vw_cstm_AEO_model'

d = UraDoc(HERE / 'ura_template.docx', logo=HERE / 'ura_logo.png')
d.cover(['CUSTOMS TAXPAYER RISK PROFILING MODEL'], 'Data and Feature Catalogue',
        f'VERSION {VERSION}, OCTOBER 2026')

# ------------------------------------------------------------------------------------ front matter
d.front_heading('Document Control & Authority')
d.table('Document Information', ['Field', 'Details'], [
    ['Document Title', 'Customs Taxpayer Risk Profiling Model: Data and Feature Catalogue'],
    ['Version', VERSION],
    ['Classification', 'Confidential'],
    ['Owner', 'Data Science Section, Data, Innovations and Projects Division, ITID'],
    ['Model settings described', '1.0.0-dev5, version 3 data rules (entry key, no motor vehicles, no APC 483)'],
], [4, 13])
d.table('Document Version History', ['Version', 'Date', 'Author(s)', 'Role', 'Changes'], [
    ['1.0', DATE, 'Ethan Mugire', 'Officer, Data Science',
     'First issue: sources, features, lineage, quality rules and access controls.'],
], [1.5, 2.5, 3, 3, 7])
d.table('Document Reviewers', ['Name', 'Role', 'Signature', 'Date'], [
    ['Stella Kwera Kisuze', 'Supervisor, Data Science', '', ''],
    ['', 'Data Governance', '', ''],
], [5, 7, 3, 2])
d.table('Document Approvals', ['Name', 'Role', 'Signature', 'Date'], [
    ['Kevin Mugumya', 'Manager, Data Science', '', ''],
], [5, 7, 3, 2])

d.h2('Distribution')
d.h3('Internal Distribution')
d.table('Internal Distribution Audience', ['Recipient', 'Use'], [
    ['Data Governance', 'Review of the sources, definitions, lineage, quality rules and access controls'],
    ['Data Science', 'Reference for building, checking and changing the features'],
    ['Data Engineering', 'The view and source columns the model depends on (Part 2)'],
    ['Customs Risk Management and the National Targeting Centre', 'What each feature means when it appears in a reason'],
], [6, 11])
d.h3('External Distribution')
d.p('In line with URA\'s mandate, controlled parts of this document may be shared outside URA only under URA\'s data '
    'protection, confidentiality and security policies. No taxpayer data is included in this document.')

d.contents()
d.page_break()
d.front_heading('List of Acronyms')
d.table('Acronyms and Terms', ['Term', 'Meaning'], [
    ['APC', 'Additional Procedure Code: the last 3 digits of the CPC; claims an exemption or relief (000 = none)'],
    ['ASYCUDA', 'Automated System for Customs Data: where declarations are lodged'],
    ['CPC', 'Customs Procedure Code (EPC + APC)'],
    ['Declaration ID', 'instance_id: the system\'s number for one declaration record; it joins the source tables'],
    ['Entry', 'A declaration as officers know it: entry number + station + year'],
    ['EPC', 'Extended Procedure Code: the first 4 digits of the CPC'],
    ['Extract', 'The table the query produces: one row per taxpayer, the counts the features need'],
    ['Feature', 'One measured fact about a taxpayer that the model reads, for example how often their tax was raised'],
    ['HS code', 'Harmonized System code: the tariff code that says what the goods are'],
    ['IM4, IM7', 'Import for home use; import into a bonded warehouse'],
    ['Peer group', 'Importers of the same main goods (HS section) and similar size'],
    ['Snapshot', 'The date the risk profile is made; features look back from it'],
    ['TIN', 'Taxpayer Identification Number'],
    ['Top-up', 'Tax raised by customs after the first assessment: top-up flag Y and final tax above the original tax'],
    ['Track A', 'The compliance history scorecard: what customs has already found'],
    ['Track B', 'The Risky Behaviour Flag: how the taxpayer declares, with nothing customs did'],
    ['UGX', 'Uganda Shillings'],
], [3.5, 13.5])

# ------------------------------------------------------------------------------------ PART 1
d.part('PART 1: OVERVIEW',
       'What the model does, what data it uses and how to read the catalogue. In short: the model looks at each '
       'importer\'s last 24 months of declarations and turns them into 25 features, which give a risk score.')
d.h2('1.1 What the Model Does')
d.p('The Customs Taxpayer Risk Profiling Model ranks every importer by compliance risk. It has two parts:')
d.bullets(['**Track A, the compliance history scorecard (8 features):** how often customs has already had to raise '
           'the taxpayer\'s tax, and by how much. It answers: "has this taxpayer been caught before?"',
           '**Track B, the Risky Behaviour Flag (17 features):** how the taxpayer declares (prices, duty rates, '
           'exemptions, splitting, new activity), using nothing customs did. It answers: "does this taxpayer behave '
           'like someone who has not been caught yet?"'])
d.h2('1.2 The Data in One Paragraph')
d.p(f'All data comes from ASYCUDA through the URA data lake. Data Engineering joins three tables into one view, '
    f'{VIEW}, where one row is one item on one declaration. A query run in Hue cleans these rows and counts, for each '
    f'taxpayer, what the features need. Python code turns the counts into the 25 features and the score.')
d.h2('1.3 How to Read This Catalogue')
d.table('Where to Find What Data Governance Asks For', ['Requirement', 'Where'], [
    ['Sources', 'Part 2: the view, its three source tables, and every column the model uses'],
    ['Lineage', 'Part 3: each step from ASYCUDA to the score, who runs it and what it produces'],
    ['Definitions', 'Part 4: every feature: what it measures, the columns it uses, its formula and why it is needed'],
    ['Quality rules', 'Part 5: cleaning rules and reading rules'],
    ['Access controls', 'Part 6: who can see each data asset and how it is protected'],
], [4, 13])

# ------------------------------------------------------------------------------------ PART 2
d.part('PART 2: DATA SOURCES',
       'One view, built by Data Engineering from three ASYCUDA tables in the data lake. The model reads 27 of its '
       'columns; each is listed below with what it means and what it is used for.')
d.h2('2.1 The View')
d.table('The Source View', ['Field', 'Details'], [
    ['Name', VIEW],
    ['Built by', 'Data Engineering'],
    ['One row is', 'One item on one declaration'],
    ['Joins', 'Declaration header, items and inspection actions, on the declaration ID (instance_id)'],
    ['Read through', 'Hue (Spark SQL), with the Data Science officer\'s own data lake login'],
    ['Period used', 'Rolling: 24 months for features, 36 months for recency, 5 years for the new importer check'],
], [4, 13])
d.h2('2.2 Declaration Header: dm_modeled_ura.ft_cstm_decl_hdr')
d.p('One record per declaration: who declared, where, when, under which regime, its status, its tax and its flags.')
d.table('Header Columns Used', ['Column', 'Type', 'What it means', 'Used for'], [
    ['instance_id', 'text', 'Declaration ID: the system\'s number for the declaration', 'Joining tables; keeping the latest ID per entry'],
    ['entry_num', 'text', 'Entry number officers see, for example C 12345', 'Entry key'],
    ['clearance_station_cd', 'text', 'Customs station of clearance', 'Entry key; station feature'],
    ['dec_ref_yer', 'text', 'Year of the declaration reference', 'Entry key'],
    ['assessment_dt_wid', 'text date (YYYYMMDD)', 'Date the declaration was assessed', 'Every time window'],
    ['taxpayer_tin', 'text (10 digits)', 'TIN of the importer', 'Who the features describe'],
    ['taxpayer_nm', 'text', 'Name of the importer', 'Display only, never a feature'],
    ['regime_cd', 'text', 'Customs regime, for example IM4, IM7, EX1', 'Keeping imports only'],
    ['decl_status', 'text', 'Status, for example Paid, Totally exited, Cancelled', 'Dropping cancelled declarations'],
    ['pay_status', 'text', 'Payment status, for example FULLY_PAID, NOT_PAID', 'Unpaid tax feature'],
    ['original_tax_amt', 'number (UGX)', 'Tax at first assessment; blank when never changed', 'Top-ups; tax reduced'],
    ['final_amt', 'number (UGX)', 'Tax after any change', 'Top-ups; tax reduced; unpaid tax'],
    ['top_up_flg', 'Y / N', 'Customs marked the declaration as topped up', 'Top-ups'],
    ['amendment_flg', 'Y / N', 'The declaration was amended after lodgement', 'Amended features'],
    ['is_red_flg, is_yellow_flg', '1 / blank', 'Lane: physical or documentary check', 'Testing the model only (never a feature)'],
    ['top_up_amt', 'number (UGX)', 'Meant to hold the top-up, but holds the final tax on most declarations', 'Not used (issue E09)'],
], [3.6, 2.6, 6, 4.8], size=8)
d.h2('2.3 Items: dm_modeled_ura.ft_cstm_decl_item_tax')
d.p('One record per item (line) on a declaration: what the goods are, where they come from, their value, weight and tax.')
d.table('Item Columns Used', ['Column', 'Type', 'What it means', 'Used for'], [
    ['key_itm_nbr', 'text', 'Item number on the declaration', 'Keeping each item once'],
    ['hsc_cd', 'text (11 digits)', 'HS code: what the goods are', 'Price and duty comparisons; goods spread; motor vehicles'],
    ['gds_org_cty', 'text', 'Country of origin', 'Comparing prices with goods of the same origin'],
    ['cpc_cd', 'text (3 digits)', 'APC: exemption or relief claimed (000 = none)', 'Exemption features; dropping APC 483'],
    ['extended_proc_cd', 'text (4 digits)', 'EPC: the procedure (for example 4000 home use)', 'Leaving fuel transit out of splitting'],
    ['customs_value', 'number (UGX)', 'Customs value of the item', 'Values; prices; duty rate'],
    ['net_weight', 'number (kg)', 'Net weight of the item', 'Price per kg'],
    ['supplementary_qnty', 'number', 'Quantity in units (pieces, litres, ...)', 'Price per unit'],
    ['tax_assessed', 'number (UGX)', 'Tax assessed on the item', 'Duty rate against peers'],
    ['preferential_treatment_flag', 'Y / N', 'A trade preference (lower duty for the origin) was claimed', 'Preference feature'],
], [3.6, 2.6, 6, 4.8], size=8)
d.h2('2.4 Inspection Actions: awunadm.insp_act_tab_t')
d.p('What was done at inspection. The view joins it, but no feature uses its columns. It was checked as a possible '
    'cause of repeated rows and ruled out (EDA report, issue E02).')

# ------------------------------------------------------------------------------------ PART 3
d.part('PART 3: LINEAGE',
       'The path from a declaration in ASYCUDA to a taxpayer\'s score, in six steps. Every step is written down as '
       'code or a query, so the same data always gives the same result.')
d.h2('3.1 From ASYCUDA to the Score')
d.table('Lineage, Step by Step', ['Step', 'What happens', 'Run by', 'Where it is defined', 'Output'], [
    ['1', 'Declarations are lodged and assessed', 'Traders, agents, officers', 'ASYCUDA', 'ASYCUDA records'],
    ['2', 'Records are copied into the data lake tables of Part 2', 'Data Engineering', 'Data lake loads',
     'Header, item and inspection tables'],
    ['3', 'The three tables are joined into one view', 'Data Engineering', VIEW, 'One row per item per declaration'],
    ['4', 'The rows are cleaned (Part 5) and counted per taxpayer', 'Data Science, in Hue',
     'sql/bt_<date>.sql, sql/live_<date>.sql, made from one template (src/ctrp/sql/features_outcomes.sql); only the '
     'dates change', 'Extract: one row per taxpayer, 79 columns (data/<name>.csv)'],
    ['5', 'Every extract is checked for cut-off downloads, repeated TINs and impossible values', 'Data Science', 'python main.py check', 'PASS / CHECK per test'],
    ['6', 'Counts become the 25 features, then the score', 'Data Science',
     'src/ctrp/core.py (Track A), src/ctrp/discovery.py (Track B)', 'Final dataset and score workbook (results/)'],
], [1, 4.5, 2.8, 5, 3.7], size=8)
d.h2('3.2 Time Windows')
d.table('How Far Back Each Measure Looks', ['Window', 'Used for'], [
    ['24 months before the snapshot', 'Most features; the declaration count; size; peer groups'],
    ['36 months before the snapshot, recent years counting more', 'Five Track A history rates (recency: 1, 0.5, 0.25 by year)'],
    ['The 3 years before those 24 months', 'Only to tell whether a taxpayer is a new importer'],
    ['6 months and 90 days before the snapshot', 'Own price drop; declaration surge'],
    ['6 months after the snapshot', 'Outcomes, to test the model on past dates only; never a feature'],
], [7, 10])
d.h2('3.3 Traceability')
d.bullets(['Every score workbook carries the model version and a fingerprint of all its settings, so any score can be '
           'traced to the exact rules that made it.',
           'Every design decision, with its evidence, is numbered in the decision log kept with the code (docs/DECISIONS.md).',
           'The working notebook (notebooks/CTRP_EDA_report.ipynb) rebuilds the features step by step from an extract '
           'and confirms they equal the production code: all 64 columns match.'])

# ------------------------------------------------------------------------------------ PART 4
d.part('PART 4: FEATURE CATALOGUE',
       'Every feature the model reads: its name, what it measures, the columns it comes from, its formula and why '
       'it is needed. 8 features in Track A and 17 in Track B; three measures appear in both.')
d.h2('4.1 How the Names Work')
d.p('Each name says **what** is measured, **per what**, **over which window**, and ends with the **unit**. For example '
    '**topped_up_per_decl_3y_rate** = declarations topped up, per declaration, over 3 years, as a rate (0 to 1).')
d.table('Short Forms Used in Names', ['Short form', 'Meaning'], [[a, b] for a, b in N.ABBREVIATIONS], [3.5, 13.5], size=8)
d.h2('4.2 Two Steps Applied after the Formulas')
d.bullets(['**Small numbers (both tracks):** a rate from few declarations says little (1 top-up in 2 declarations is '
           '50%). The rate is pulled towards everyone\'s average with the weight n ÷ (n + 10), where n is the number of '
           'declarations (items compared, for price rates). It can only lower a rate, never raise it. Track A keeps the '
           'value before this step as raw_<name>.',
           '**Peer percentile (Track B):** each Track B feature becomes its rank among importers of the same main goods '
           'and size, from 0 to 1 (column ending _pct). A blank sits in the middle (0.5).'])

A_ROWS = [
    ('PAR_045T', 'topped_up_per_decl_3y_rate', 'top_up_flg, original_tax_amt, final_amt',
     'W(topped_up) ÷ W(decl)'),
    ('PAR_077', 'severe_top_up_per_decl_3y_rate', 'top_up_flg, original_tax_amt, final_amt',
     'W(severe) ÷ W(decl)'),
    ('PAR_045', 'amended_per_decl_3y_rate', 'amendment_flg', 'W(amendment_flg = Y) ÷ W(decl)'),
    ('PAR_048', 'top_up_per_final_tax_3y_rate', 'original_tax_amt, final_amt, top_up_flg',
     'W(top_up_ugx) ÷ (W(original_tax_ugx) + W(top_up_ugx))'),
    ('PAR_076', 'peer_price_shortfall_per_value_24m_rate',
     'customs_value, net_weight, supplementary_qnty, hsc_cd, gds_org_cty',
     'Σ gap on low items ÷ Σ customs_value, where low item = price < 0.5 x peer price and '
     'gap = min(peer_kg x kg, peer_unit x units) - value'),
    ('PAR_066', 'tax_reduced_per_decl_3y_rate', 'original_tax_amt, final_amt', 'W(final_amt < original_tax) ÷ W(decl)'),
    ('PAR_105', 'top_up_last_180d_flag', 'assessment_dt_wid, top_up_flg',
     '1 if snapshot - date of last top-up ≤ 180 days, else 0'),
    ('PAR_023', 'away_from_main_station_per_decl_24m_rate', 'clearance_station_cd',
     '1 - max(decl at one station) ÷ decl'),
]
WHY = {r[0]: r[5] for r in N.FEATURE_LIST}
PROD = {v: k for k, v in N.TRACK_A_NAMES.items()}
d.h2('4.3 Track A: Compliance History Scorecard')
d.p('Shorthand used in the formulas:')
d.code(['original_tax = original_tax_amt, or final_amt when blank',
        'topped_up    = top_up_flg = Y  AND  final_amt > original_tax',
        'top_up_ugx   = final_amt - original_tax, when topped_up (else 0)',
        'severe       = topped_up  AND  top_up_ugx >= 0.30 x final_amt',
        'W(x)         = 1 x x(latest year) + 0.5 x x(year before) + 0.25 x x(year before that)',
        'decl         = number of declarations'])
d.table('Track A Features', ['Parameter', 'Feature', 'Columns used', 'Formula', 'Why it is needed'],
        [[par, n, cols, f, WHY[PROD[n]]] for par, n, cols, f in A_ROWS], [1.8, 4, 3.3, 4.5, 3.4], size=8)

WHAT = {}
for r in N.feature_sheet().itertuples():
    for name in r[1].split('; '):
        WHAT[name.replace(' (Track A)', '').replace(' (Track B)', '').removeprefix('b_')] = r[4]
INPUTS = {r[0]: r[4] for r in N.FEATURE_LIST}
PARAM = {r[0]: r[2] for r in N.FEATURE_LIST}
B_ROWS = []
for prod, name in N.TRACK_B_NAMES.items():
    key = 'par023_station_spread' if prod == 'station_spread' else prod
    B_ROWS.append([PARAM[key] or 'New', 'b_' + name, INPUTS[key], WHAT[name], WHY[key]])
d.h2('4.4 Track B: Risky Behaviour Flag')
d.p('"Middle price" and "middle duty rate" are those of all other importers of the same HS code (and origin, where '
    'at least 5 importers bring it). Only comparisons with 5 or more importers are used.')
d.p('Parameter: the code in the agreed parameter lists. "Stand-in" means the closest measure the data allows; '
    '"New" means a measure added by Data Science.')
d.table('Track B Features', ['Parameter', 'Feature', 'Columns used', 'Formula', 'Why it is needed'], B_ROWS,
        [1.8, 4.2, 3.2, 4.4, 3.4], size=8)

d.h2('4.5 Other Columns of the Final Dataset')
d.table('Supporting Columns', ['Column', 'In view or derived', 'What it is'], [
    ['taxpayer_tin', 'In view', 'The taxpayer'],
    ['taxpayer_nm', 'In view', 'The taxpayer\'s name (display only)'],
    ['snapshot_date', 'Set by the query', 'The date of the profile'],
    ['decl_24m_count', 'Derived', 'count(declarations) in the 24 months'],
    ['customs_value_24m_ugx', 'Derived', 'Σ customs_value in the 24 months: sets the size tier'],
    ['limited_history', 'Derived', 'Y if decl_24m_count < 10: ranked on a separate list'],
    ['no_top_up_history', 'Derived', 'Y if no top-up in the 24 months: the group Track B is for'],
    ['peer_group', 'Derived', 'HS section of the main chapter + size tier (thirds of value), e.g. "Textiles, large"'],
    ['raw_<name>', 'Derived', 'A Track A value before the small-numbers step'],
    ['b_<name>_pct', 'Derived', 'rank of a Track B feature within its peer group (0 to 1): what the Track B model reads'],
    ['out_<name>', 'Derived', 'checks, hits and top-ups in the 6 months after a past snapshot: for testing only'],
], [4.5, 3, 9.5])

# ------------------------------------------------------------------------------------ PART 5
d.part('PART 5: DATA QUALITY RULES',
       'Which rows are removed and why, and how doubtful values are read. The counts behind each rule are in the '
       'EDA report.')
d.h2('5.1 Cleaning Rules')
d.table('Cleaning Rules (Rows Removed: 36 Months to 30 September 2026, All Regimes)', ['Rule', 'Keeps', 'Why', 'Rows removed'], [
    ['R1', 'TINs of exactly 10 digits', 'A malformed TIN cannot be tied to a taxpayer', '1,325,413'],
    ['R3', 'Declarations not cancelled (a blank status counts as a fail)', 'A cancelled declaration did not go ahead', '56,004'],
    ['R4', 'Regimes IM4 and IM7', 'The model profiles importers', '3,396,602'],
    ['R13', 'Everything except APC 483', 'Destroyed or abandoned goods and dummy entries are not trade', '8,083'],
    ['R14', 'The latest declaration ID of each entry (entry number + station + year)', 'An entry is never counted twice', '0'],
    ['R15', 'Declarations with no motor vehicle item (HS 8701 to 8708, 8711)', 'A separate model covers vehicles', '2,284,966'],
    ['R5', 'Each item once', 'The view repeats some item rows (issue E02)', '76'],
], [1.4, 5.6, 7, 3], size=8)
d.h2('5.2 Reading Rules')
d.table('How Doubtful Values Are Read', ['Rule', 'The rule', 'Why'], [
    ['R7', 'A top-up is counted only when the flag is Y and the final tax is above the original tax; its amount is final '
     'minus original tax', 'The flag alone is wrong on some declarations, and top_up_amt is unreliable (E06, E09)'],
    ['Blank tax', 'A blank original tax is read as unchanged: the final tax is used', 'Blank on 37% of declarations '
     'without a top-up but 0.04% of those with one (E08)'],
    ['R8', 'Items with zero, negative or blank value or weight are left out of the price measures', 'A price needs both'],
    ['R9', 'A price under 1% of the middle price is a keying error: counted in its own feature, not as undervaluation',
     'Usually a weight in the wrong unit (E12)'],
    ['Peers', 'A comparison with other importers needs at least 5 importers of the goods', 'One importer must not set the standard'],
    ['R12', 'A declaration counts as checked when the red or yellow flag is 1', 'Used for testing the model only'],
    ['Size', 'Fewer than 10 declarations = limited history, ranked on its own list', 'Few declarations say little'],
], [1.8, 8, 7.2], size=8)
d.h2('5.3 Known Data Issues')
d.p('The EDA report (October 2026) lists each known issue with the declarations and taxpayers behind it and how the '
    'model handles it: repeated item rows (E02), cancelled declarations (E04), APC 483 (E05), the top-up flag and '
    'amounts (E06, E07, E09), blank original tax (E08) and missing value or weight (E11). None found: entries under '
    'two declaration IDs (E01) and malformed TINs among imports (E03).')

# ------------------------------------------------------------------------------------ PART 6
d.part('PART 6: ACCESS CONTROLS',
       'Who can see each data asset and how it is protected. The source data stays in '
       'the data lake; what leaves it is counted per taxpayer, and the outputs that carry names are confidential.')
d.table('Data Assets, Access and Controls', ['Asset', 'Holds', 'Who can use it', 'Control'], [
    ['Source tables and view (data lake)', 'Every declaration and item', 'Users granted access by Data Engineering',
     'Read only, with a personal data lake login, through Hue'],
    ['Queries (sql/) and code (src/)', 'Rules and formulas; no taxpayer data', 'Data Science', 'Kept with the project; '
     'changes recorded in the decision log'],
    ['Extracts (data/*.csv)', 'One row per TIN with counts; no names', 'Data Science',
     'Confidential; kept in the project folder on a URA workstation'],
    ['Score and evidence workbooks (results/)', 'TINs, names, scores and entries', 'Data Science; Customs Risk '
     'Management and NTC for review', 'Confidential; marked "internal use only"; shared internally only'],
    ['Data lake password', 'Login', 'The officer only', 'Never written in code or files; typed at run time or set for '
     'the session only'],
], [3.8, 3.6, 4, 5.6], size=8)
d.save(OUT)
print('written', OUT)
