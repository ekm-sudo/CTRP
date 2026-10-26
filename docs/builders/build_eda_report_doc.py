"""
Build the CTRP EDA report in the URA house format: docs/CTRP_EDA_Report.docx.

What: the data exploration report for review and sign-off (missing data, duplicates, cleaning, the 10 data
      issues with their evidence workbooks, and the features), with the house cover page, Document Control and
      Authority, Distribution, contents, lists of tables and acronyms, and a PART-based body.
Why:  the one-page note was too tight for review; this is the document Stella signs off.

    python docs/builders/build_eda_report_doc.py

The numbers are the Hue results of 21 and 22 October 2026 (data/eda_report/Q1..Q8.csv, data/eda_issues/E01..E11.csv)
and the extract data/bt_2026-03-31.csv.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'src'))
from ura_doc import UraDoc  # noqa: E402
from ctrp import eda_note as N  # noqa: E402

OUT = ROOT / 'docs' / 'CTRP_EDA_Report.docx'
VERSION = '1.0'
DATE = '22 October 2026'

d = UraDoc(HERE / 'ura_template.docx', logo=HERE / 'ura_logo.png')
d.cover(['CUSTOMS TAXPAYER RISK PROFILING MODEL'], 'Data Exploration Report: Missing Data, Duplicates and Data Issues',
        f'VERSION {VERSION}, OCTOBER 2026')

# ------------------------------------------------------------------------------------ front matter
d.front_heading('Document Control & Authority')
d.table('Document Information', ['Field', 'Details'], [
    ['Document Title', 'Customs Taxpayer Risk Profiling Model: Data Exploration Report'],
    ['Version', VERSION],
    ['Classification', 'Confidential (the attached workbooks contain TINs and taxpayer names)'],
    ['Owner', 'Data Science Section, Data, Innovations and Projects Division, ITID'],
    ['Data', 'dm_modeled_ura_datascience.vw_cstm_AEO_model, IM4 and IM7, 24 months to 30 September 2026'],
], [4, 13])
d.table('Document Version History', ['Version', 'Date', 'Author(s)', 'Role', 'Changes'], [
    ['1.0', DATE, 'Ethan Mugire', 'Officer, Data Science', 'First issue for review.'],
], [1.5, 2.5, 3, 3, 7])
d.table('Document Reviewers', ['Name', 'Role', 'Signature', 'Date'], [
    ['Stella Kwera Kisuze', 'Supervisor, Data Science', '', ''],
], [5, 7, 3, 2])
d.table('Document Approvals', ['Name', 'Role', 'Signature', 'Date'], [
    ['Kevin Mugumya', 'Manager, Data Science', '', ''],
], [5, 7, 3, 2])

d.h2('Distribution')
d.p('This report was prepared by the Data Science Section under the Data, Innovations and Projects (DIP) Division '
    'of the Information Technology and Innovation Department (ITID). It records what was found in the customs data '
    'used by the Customs Taxpayer Risk Profiling Model before the version 3 retest: how complete the data is, '
    'where it repeats, how it is cleaned, and the data issues found, each with the declarations and taxpayers '
    'behind it in an attached workbook.')
d.table('Audience for Internal Distribution', ['Audience', 'Primary Use'], [
    ['Data Science', 'Sign-off of the data the model is built on, and of how each issue is handled.'],
    ['Customs Risk Management', 'Confirmation of the business readings in Part 6 (blank original tax, unflagged tax rises).'],
    ['Data Engineering', 'The questions in Part 6 on the repeated item rows and the declarations with no lane flag.'],
], [5, 12])

d.contents()
d.page_break()
d.front_heading('List of Acronyms')
d.table('Acronyms and Terms', ['Term', 'Meaning'], [
    ['APC', 'Additional Procedure Code: the last 3 digits of the CPC; claims a rebate or exemption'],
    ['ASYCUDA', 'Automated System for Customs Data'],
    ['CPC', 'Customs Procedure Code (EPC + APC)'],
    ['Declaration ID', 'instance_id: the number the system gives each declaration record; it links the header, '
     'item and inspection tables'],
    ['EDA', 'Exploratory Data Analysis'],
    ['Entry', 'A declaration as officers know it: entry number + station + year (for example C 12345, UGKLA, 2026)'],
    ['EPC', 'Extended Procedure Code: the first 4 digits of the CPC'],
    ['HS', 'Harmonized System of commodity classification'],
    ['IM4, IM7', 'Import for home use; import into a warehouse'],
    ['ITID', 'Information Technology and Innovation Department'],
    ['Snapshot', 'The date at which taxpayers are profiled; features come from the 24 months before it'],
    ['TIN', 'Taxpayer Identification Number'],
    ['Top-up', 'Tax raised after assessment: flag Y and final tax above original tax'],
    ['UGX', 'Uganda Shillings'],
    ['URA', 'Uganda Revenue Authority'],
], [3.5, 13.5])

# ------------------------------------------------------------------------------------ PART 1
d.part('PART 1: PURPOSE, DATA AND EVIDENCE',
       'This part sets out why the data was explored, which data was used, how declarations are identified, '
       'and the evidence workbooks that come with this report.')
d.h2('1.1 Purpose')
d.p('Before the model is retested (version 3: motor vehicle declarations removed, and each entry identified by '
    'entry number, station and year), the data it reads was checked for two things in particular: **missing '
    'data** and **duplicates**. Along the way ten data issues were found. For each one this report states what was '
    'found, how many declarations and taxpayers it touches, and what the model does about it.')
d.h2('1.2 The Data')
d.p('The model reads one view prepared by Data Engineering, dm_modeled_ura_datascience.vw_cstm_AEO_model. One row of '
    'the view is one item on one declaration. The view joins three tables on the declaration ID:')
d.bullets(['**Declaration header** (dm_modeled_ura.ft_cstm_decl_hdr): the taxpayer, date, station, regime, status, '
           'tax and flags of the declaration;',
           '**Items** (dm_modeled_ura.ft_cstm_decl_item_tax): HS code, origin, value, weight and tax of each item;',
           '**Inspection actions** (awunadm.insp_act_tab_t): what was done at inspection.'])
d.p('Unless stated otherwise, the figures cover IM4 and IM7 declarations assessed in the 24 months to 30 September '
    '2026: 4,585,662 item rows on 1,301,602 declarations.')
d.h2('1.3 Entries and Declaration IDs')
d.p('An **entry** is the declaration as officers and agents know it: an entry number such as C 12345, which is unique '
    'only within a station and a year. The model therefore identifies an entry by **entry number + station + year**.')
d.p('A **declaration ID** (instance_id) is the number the system gives each declaration record. It is what links '
    'the header, item and inspection tables. If an entry were lodged again as a new record, it would carry two '
    'declaration IDs; the model would then keep only the latest. Issue E01 checks this.')
d.h2('1.4 The Evidence Workbooks')
d.p('Each issue in Part 5 has its own Excel workbook in the evidence folder. Every workbook has the same four sheets, '
    'so a Risk Officer or Data Engineer can find and check any declaration.')
d.table('Sheets in Each Evidence Workbook', ['Sheet', 'What it holds'], [
    ['Issue', 'What was found, what the model does, and how to check it in ASYCUDA (Risk Officers) or in the data '
     'lake (Data Engineering)'],
    ['Entry list', 'One row per declaration: entry number, station, year, declaration ID, date, taxpayer, consignee, '
     'regime, APCs, tax and flags, with a column for the reviewer\'s verdict'],
    ['Taxpayers', 'One row per TIN: name and the number of declarations affected'],
    ['Item rows', 'The rows exactly as the view returned them'],
], [3.5, 13.5])

# ------------------------------------------------------------------------------------ PART 2
d.part('PART 2: MISSING DATA',
       'Almost every column is complete. Two need a reading: the original tax, blank on a quarter of rows, and the '
       'lane flags, which look half empty but are not. Both are explained by how the data is recorded.')
d.h2('2.1 Completeness by Column')
d.p('Of the 27 columns checked, 22 have no blanks at all, and only three are blank on more than 1 row in 10,000.')
d.table('Columns with Blanks (24 months to September 2026)', ['Column', 'Blank, % of rows', 'Reading'], [
    ['Red lane flag (is_red_flg)', '48.9', 'Not missing: see 2.3'],
    ['Original tax (original_tax_amt)', '24.8', 'Most likely unchanged tax: see 2.2'],
    ['Yellow lane flag (is_yellow_flg)', '25.3', 'Not missing: see 2.3'],
    ['Supplementary quantity', '0.006', 'Too few to matter; price per unit is then not compared'],
    ['Taxpayer name', '0.0001', 'Names are not used; the TIN identifies the taxpayer'],
], [6, 3, 8])
d.p('A zero is not a blank. Final tax is zero on 43.8% of item rows; this is a recorded value, and the model reads '
    'it as zero tax.')

d.h2('2.2 Original Tax')
d.p('The original tax is blank on 24.8% of rows, and more so each year.')
d.table('Original Tax Blank by Year', ['Year', 'Item rows', 'Original tax blank, %'], [
    ['2024 (October to December)', '527,478', '21.6'],
    ['2025', '2,252,920', '23.6'],
    ['2026 (January to September)', '1,805,264', '27.1'],
], [7, 5, 5])
d.p('If a blank means the tax was never changed, declarations **with** a top-up (which changes the tax) should almost '
    'never have one. That is what the data shows:')
d.table('Original Tax Blank by Top-up Flag', ['Top-up flag', 'Declarations', 'Original tax blank, %'], [
    ['Y', '79,834', '0.04'],
    ['N', '1,221,768', '37.1'],
], [5, 6, 6])
d.p('So the model reads a blank original tax as "unchanged" and uses the final tax in its place (issue E08). This is '
    'our reading of the data, not something the data states, and is put for confirmation in Part 6.')

d.h2('2.3 Lane Flags')
d.p('The red flag is blank on 48.9% of rows and the yellow flag on 25.3%. Counting the flags per declaration shows '
    'that they build on each other: a red declaration also carries the yellow and green flags, and a yellow one also '
    'carries green.')
d.table('Lane Flags per Declaration', ['Red', 'Yellow', 'Green', 'Blue', 'Declarations', '%'], [
    ['1', '1', '1', '', '454,926', '35.0'],
    ['', '1', '1', '', '379,513', '29.2'],
    ['', '', '1', '', '284,626', '21.9'],
    ['', '', '', '1', '142,940', '11.0'],
    ['', '', '', '', '28,486', '2.2'],
    ['Other combinations', '', '', '', '11,111', '0.9'],
    ['Total', '', '', '', '1,301,602', '100.0'],
], [2.2, 2.2, 2.2, 2.2, 4, 2])
d.p('97.0% of declarations follow this pattern, so a blank flag means "not this lane", not missing data. The model '
    'counts a declaration as checked when the red or yellow flag is 1. The 28,486 declarations with no flag at all '
    'are put to Data Engineering in Part 6.')

# ------------------------------------------------------------------------------------ PART 3
d.part('PART 3: DUPLICATES',
       'No entry appears under more than one declaration ID. Some items are repeated many times in the view; the '
       'repeats come from the item table, almost all are on motor vehicle (mostly motorcycle) declarations, and the '
       'model removes them.')
d.h2('3.1 Entries')
d.p('No entry appears under more than one declaration ID (issue E01: none found), and no declaration ID has more '
    'than one TIN or date. The model still identifies entries by entry number, station and year and keeps the '
    'latest declaration ID, so an entry lodged again could never be counted twice.')
d.h2('3.2 Repeated Items')
d.p('The same declaration ID and item number appear more than once for **7,783 items**, on **7,568 declarations** of '
    '**154 taxpayers** (issue E02). One item appears 412 times. Together the repeats add 927,778 rows, about 20% of '
    'all rows. Except for one item, every copy is the same in every column.')
d.table('Where the Repeated Items Come From', ['Check', 'Items'], [
    ['Items repeated in the view', '7,783'],
    ['The item table holds more than one row for the item', '7,783'],
    ['The declaration header repeats', '0'],
    ['The inspection actions repeat', '0'],
    ['On motor vehicle declarations (headings 8701 to 8708, 8711)', '7,748 (99.6%)'],
    ['Of which motorcycles (heading 8711)', '7,618 (97.9%)'],
    ['On IM7 declarations / on IM4 declarations', '4,401 / 3,382'],
], [12, 5])
d.h2('3.3 Why They Are Not Steps in the Customs Process')
d.p('A declaration passes through several steps (assessed, paid, exited), so repeats could be one row per step. '
    'The evidence says otherwise:')
d.bullets(['A step changes the status or a date, but the copies are identical in every column, status and date '
           'included.',
           'A declaration has a handful of steps, but the copies run to 412, and the same count repeats across '
           'unrelated declarations: 1,167 declarations have exactly 192 copies of their item, and 1,016 exactly 166.',
           'The steps are recorded on the declaration header, which never repeats. The repeats sit in the item table.',
           'Restricting the data to IM4 and IM7 decides which declarations are kept; it does not change how many rows '
           'each one has, so it cannot remove repeats within a declaration.'])
d.p('The repeats therefore come from how the item table holds or loads these vehicle declarations. Data Engineering '
    'is asked to confirm the cause in Part 6.')
d.h2('3.4 What the Model Does')
d.p('The model keeps each item once (rule R5) and, from version 3, leaves out every declaration with a motor vehicle '
    'item (rule R15). After R15, only 76 repeated rows remain in 36 months of data, and R5 removes them.')

# ------------------------------------------------------------------------------------ PART 4
d.part('PART 4: CLEANING',
       'Seven rules turn the 11.1 million rows of 36 months into the 4.1 million the model reads. Each rule is '
       'applied in turn, and a row is counted at the first rule it fails.')
d.h2('4.1 Rows Removed by Each Rule')
d.table('Cleaning Rules and Rows Removed (36 Months to September 2026, All Regimes)',
        ['Rule', 'What it removes', 'Rows removed', 'Rows left'], [
    ['', 'Rows loaded', '', '11,135,207'],
    ['R1', 'TIN blank or not 10 digits', '1,325,413', '9,809,794'],
    ['R3', 'Cancelled declarations (status Cancelled)', '56,004', '9,753,790'],
    ['R4', 'Regimes other than IM4 and IM7', '3,396,602', '6,357,188'],
    ['R13', 'APC 483 (destroyed or abandoned goods, dummy reconciliation entries)', '8,083', '6,349,105'],
    ['R14', 'Older declaration IDs of the same entry', '0', '6,349,105'],
    ['R15', 'Declarations with a motor vehicle item (headings 8701 to 8708, 8711)', '2,284,966', '4,064,139'],
    ['R5', 'Repeated copies of an item', '76', '4,064,063'],
], [1.5, 9.5, 3, 3])
d.p('The rows add up: 11,135,207 loaded, 7,071,144 removed, 4,064,063 left.')

# ------------------------------------------------------------------------------------ PART 5
d.part('PART 5: DATA ISSUES AND EVIDENCE',
       'Ten data issues were checked. For each: what was found, how it was found in the data, how many declarations '
       'and taxpayers it touches, and what the model does. The declarations and taxpayers are listed in the '
       'evidence workbook of the same code.')
d.h2('5.1 Summary')
d.table('Data Issues, Declarations and Taxpayers (24 Months to September 2026, IM4 and IM7)',
        ['Code', 'Issue', 'Declarations', 'Taxpayers', 'What the model does'], [
    ['E01', 'Same entry under more than one declaration ID', '0', '0', 'Keeps the latest ID per entry (R14)'],
    ['E02', 'The same item row repeated', '7,568', '154', 'Keeps each item once (R5); drops vehicles (R15)'],
    ['E03', 'TIN blank or not 10 digits', '0', '0', 'Profiles 10-digit TINs only (R1)'],
    ['E04', 'Cancelled declarations', '9,894', '1,809', 'Leaves them out (R3)'],
    ['E05', 'APC 483', '1,582', '356', 'Leaves them out (R13)'],
    ['E06', 'Top-up flag Y, but final tax not above original tax', '10,087', '4,919', 'Not counted as a top-up'],
    ['E07', 'Final tax above original tax, but no top-up flag', '7,031', '1,929', 'Not counted as a top-up (to confirm)'],
    ['E08', 'Original tax blank', 'about 453,000', 'see 5.2', 'Reads blank as unchanged (to confirm)'],
    ['E09', 'top_up_amt holds the final tax when there is no top-up', 'about 628,000', 'see 5.2', 'Does not use top_up_amt'],
    ['E11', 'Customs value or weight zero, negative or blank', '32', '26', 'Leaves the item out of the price measures'],
], [1.4, 6, 2.4, 2, 5.2])
d.h2('5.2 Each Issue')
issues = [
    ('E01', 'Same Entry under More than One Declaration ID',
     'Counted the declaration IDs per entry (entry number + station + year). None has more than one.',
     'Nothing to correct today. The rule stays so that a re-lodged entry could never be counted twice.'),
    ('E02', 'The Same Item Row Repeated',
     'Counted the rows per declaration ID and item number; see Part 3.',
     'Each item is kept once, and motor vehicle declarations are left out.'),
    ('E03', 'TIN Blank or Not 10 Digits',
     'Checked every TIN against the 10-digit pattern. Among IM4 and IM7 declarations in the 24 months, none fails. '
     'The 1,325,413 rows R1 removes in Part 4 belong to other regimes and the earlier year.',
     'Only 10-digit TINs are profiled.'),
    ('E04', 'Cancelled Declarations',
     'Read from the declaration status (decl_status) in the declaration header table: the value "Cancelled" is '
     'the status ASYCUDA gives the declaration. Nothing is inferred.',
     'Cancelled declarations are left out, since they did not go ahead. The workbook lets a Risk Officer confirm '
     'in ASYCUDA that no goods were released and no tax was paid on them.'),
    ('E05', 'APC 483',
     'Read from the APC (cpc_cd). The CPC memo describes APC 483 as destroyed or abandoned goods and dummy '
     'reconciliation entries, not trade.',
     'These declarations are left out.'),
    ('E06', 'Top-up Flag Y, but Final Tax Not above Original Tax',
     'Compared the top-up flag with the original and final tax on each declaration.',
     'A top-up counts only when the flag is Y **and** the final tax is above the original tax.'),
    ('E07', 'Final Tax above Original Tax, but No Top-up Flag',
     'Same comparison: the tax rose but the flag is not Y.',
     'Not counted as top-ups, since the flag is customs\' own marking. To be confirmed (Part 6).'),
    ('E08', 'Original Tax Blank',
     'See 2.2. Listed from a random 1 in 50 of the entries (9,066 entries of 972 taxpayers), so about 453,000 '
     'entries in all.',
     'A blank is read as unchanged, and the final tax is used. To be confirmed (Part 6).'),
    ('E09', 'top_up_amt Holds the Final Tax when There Is No Top-up',
     'On declarations with no top-up flag, top_up_amt equals the final tax 99.5% of the time. Listed from a random '
     '1 in 50 of the entries (12,560 entries of 4,038 taxpayers), so about 628,000 in all.',
     'top_up_amt is not used. The top-up is worked out as final tax minus original tax.'),
    ('E11', 'Customs Value or Weight Zero, Negative or Blank',
     'Checked customs value and net weight on every item.',
     'These items still count as declarations, but are left out of the price comparisons.'),
]
for code, title, how, does in issues:
    d.h3(f'{code}: {title}')
    d.bullets([f'**How it was found:** {how}', f'**What the model does:** {does}',
               f'**Evidence:** workbook {code} in the evidence folder.'])

# ------------------------------------------------------------------------------------ PART 6
d.part('PART 6: FEATURES, CONFIRMATIONS AND NEXT STEPS',
       'The 25 features are built from the cleaned data and match the production code exactly. Two readings need '
       'confirmation and two questions go to Data Engineering.')
d.h2('6.1 Features')
d.p('The model reads 25 features: 8 for the compliance history scorecard (Track A) and 17 on behaviour (Track B). '
    'The working notebook builds them step by step from the Hue extract (snapshot 31 March 2026, 35,281 '
    'taxpayers) and checks the result against the production code: all 64 columns of the final dataset are the '
    'same. Each name says what is measured, over which window, and in what unit.')
d.table('The Features', ['Feature', 'What it measures'],
        [[r[1].replace(' (Track A)', ' (A)').replace(' (Track B)', ' (B)'), r[4]] for r in N.feature_sheet().itertuples()],
        [8, 9], size=8)
d.h2('6.2 Confirmations Requested')
d.table('Readings to Confirm', ['Issue', 'Reading', 'Asked of'], [
    ['E08', 'A blank original tax means the tax was not changed.', 'Supervisor, Data Science; Customs Risk Management'],
    ['E07', 'A tax rise with no top-up flag is not a top-up.', 'Supervisor, Data Science; Customs Risk Management'],
], [2, 9, 6])
d.h2('6.3 Questions for Data Engineering')
d.table('Questions for Data Engineering', ['Topic', 'Question'], [
    ['Repeated item rows (E02)', 'Why does the item table hold several identical rows for one item on motor vehicle '
     'declarations, with the same counts (192, 166) on unrelated declarations?'],
    ['Declarations with no lane flag', 'What are the 28,486 declarations with no red, yellow, green or blue flag?'],
], [5, 12])
d.h2('6.4 Next Steps')
d.numbered(['Sign-off of this report and the readings in 6.2.',
            'Retest of the model (version 3) on the cleaned data.',
            'Update of the cleaning rules if Data Engineering\'s answers change the reading of E02.'])

d.save(OUT)
print('written', OUT)
