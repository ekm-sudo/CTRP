"""
Build the Model Development Decision Record (Word, URA house format).

What: writes docs/CTRP_Decision_Record.docx from the decisions, evidence and charts of release 1.
Why:  one formal record of every decision, its reason and its evidence, for reviewers and approvers.

    python main.py docs        (or: python docs/builders/build_decision_record.py)

Needs the charts saved by the notebook (results/charts/chart_NN.png): run the notebook first.
Edit the text below and re-run to produce a new version; change VERSION and the history table.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # docs/builders
ROOT = HERE.parents[1]                          # the project folder
sys.path.insert(0, str(HERE))
from ura_doc import UraDoc  # noqa: E402

TEMPLATE = HERE / 'ura_template.docx'
LOGO = HERE / 'ura_logo.png'
CHARTS = ROOT / 'results' / 'charts'
OUT = ROOT / 'docs' / 'CTRP_Decision_Record.docx'
VERSION = '0.2'
DATE = 'October 2026'


def chart(n):
    return str(CHARTS / f'chart_{n:02d}.png')


def decisions_from_log():
    """Read every numbered decision from DECISIONS.md, so the register never drifts from the log."""
    rows = []
    text = (ROOT / 'docs' / 'DECISIONS.md').read_text(encoding='utf-8')
    text = text[text.index('## Stage 1'):]                     # skip the plan table (stage numbers)
    for line in text.splitlines():
        m = re.match(r'^\|\s*(\d+)\s*\|(.*)\|(.*)\|\s*$', line)
        if m:
            rows.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip()))
    rows.sort(key=lambda r: r[0])
    swaps = {"Ethan's": "Data Science's", 'Ethan': 'Data Science', "Andrew's": "an officer's",
             "'officers_judith' and 'officers_andrew'": 'two officer profiles'}
    def clean(t):
        for a, b in swaps.items():
            t = t.replace(a, b)
        return t
    return [[str(n), clean(d), clean(e)] for n, d, e in rows]


d = UraDoc(TEMPLATE, logo=LOGO)
d.cover(['CUSTOMS TAXPAYER RISK PROFILING MODEL'], 'Model Development Decision Record: Release 1',
        f'VERSION {VERSION}, {DATE.upper()} (DRAFT)')

# ------------------------------------------------------------------------------------ front matter
d.front_heading('Document Control & Authority')
d.table('Document Information', ['Field', 'Details'], [
    ['Document Title', 'Customs Taxpayer Risk Profiling Model: Model Development Decision Record'],
    ['Version', f'{VERSION} (draft for review)'],
    ['Classification', 'Confidential'],
    ['Owner', 'Data Science Section, Data, Innovations and Projects Division, ITID'],
    ['Model version recorded', '1.0.0-dev4 (settings fingerprint printed on every output)'],
], [4, 13])
d.table('Document Version History', ['Version', 'Date', 'Author(s)', 'Role', 'Changes'], [
    ['0.1', DATE, 'Ethan Mugire', 'Officer, Data Science',
     'First draft: decisions and evidence for Stages 1 to 6 of release 1, the first challenger comparison, '
     'and the open questions for Stage 7.'],
    ['0.2', DATE, 'Ethan Mugire', 'Officer, Data Science',
     'Lift worked through with real numbers; ensembles tested (decisions 52 to 54); project reorganised into the '
     'standard src layout with automatic tests (decision 55).'],
], [1.5, 2.5, 3, 3, 7])
d.table('Document Reviewers', ['Name', 'Role', 'Signature', 'Date'], [
    ['Stella Kwera Kisuze', 'Supervisor, Data Science', '', ''],
    ['Judith Phionah Kembabazi', 'Supervisor, National Targeting Centre', '', ''],
    ['Denis Lutaaya', 'Manager, National Targeting Centre', '', ''],
], [5, 7, 3, 2])
d.table('Document Approvals', ['Name', 'Role', 'Signature', 'Date'], [
    ['Kevin Mugumya', 'Manager, Data Science', '', ''],
    ['Nelson Keikara', 'Assistant Commissioner, Data, Innovations and Projects', '', ''],
    ['James Malinzi', 'Assistant Commissioner, Customs Risk Management', '', ''],
], [5, 7, 3, 2])

d.h2('Distribution')
d.p('This record was prepared by the Data Science Section under the Data, Innovations and Projects (DIP) '
    'Division of the Information Technology and Innovation Department (ITID). It is the reference for why the '
    'Customs Taxpayer Risk Profiling Model is built the way it is: every decision taken during release 1, the '
    'reason for it, and the evidence behind it. It is meant to be read with the model code, the working '
    'notebook and the decision log kept beside the code.')
d.table('Audience for Internal Distribution', ['Audience', 'Primary Use'], [
    ['Data Science', 'Reference for the design, the evidence behind each setting, and how to change it safely.'],
    ['Customs Risk Management and the National Targeting Centre', 'Review of the parameters, thresholds, bands and reason wording; '
     'the open questions in Part 7 need their answers.'],
    ['Data Engineering', 'The source view, the cleaning rules and the extract query the model depends on.'],
    ['Data Governance and Internal Audit', 'Traceability: every score carries a model version and a settings fingerprint that this record explains.'],
], [5, 12])

d.contents()
d.page_break()
d.front_heading('List of Acronyms')
d.table('Acronyms and Terms', ['Term', 'Meaning'], [
    ['APC', 'Additional Procedure Code: the last 3 digits of the CPC; claims a rebate or exemption'],
    ['ASYCUDA', 'Automated System for Customs Data'],
    ['Back-test', 'Scoring taxpayers as they stood at a past date and checking what happened next'],
    ['CPC', 'Customs Procedure Code (EPC + APC)'],
    ['EPC', 'Extended Procedure Code: the first 4 digits of the CPC'],
    ['HDBSCAN', 'Hierarchical Density-Based Spatial Clustering of Applications with Noise'],
    ['Hit', 'A red or yellow lane declaration that ended in a top-up'],
    ['Hit rate', 'Hits divided by checked (red or yellow) declarations'],
    ['HS', 'Harmonized System of commodity classification'],
    ['IM4, IM7', 'Import for home use; import into a warehouse'],
    ['ITID', 'Information Technology and Innovation Department'],
    ['L x I', 'Likelihood times impact: the rating behind each parameter\'s weight'],
    ['Lift', 'Hit rate of the model\'s top group divided by everyone\'s hit rate'],
    ['NTC', 'National Targeting Centre'],
    ['PCA', 'Principal Component Analysis'],
    ['Snapshot', 'The date at which taxpayers are scored; features come from the 24 months before it'],
    ['TIN', 'Taxpayer Identification Number'],
    ['Top-up', 'Tax raised after assessment: flag Y and final tax above original tax'],
    ['UGX', 'Uganda Shillings'],
    ['URA', 'Uganda Revenue Authority'],
    ['WCO', 'World Customs Organization'],
], [3.5, 13.5])

# ------------------------------------------------------------------------------------ PART 1
d.part('PART 1: PURPOSE AND CONTEXT',
       'This part sets out what this record is for, what the model does in one page, the data it was built '
       'on, and the standard of evidence every decision in the later parts was held to.')
d.h2('1.1 Purpose of this Record')
d.p('Release 1 of the Customs Taxpayer Risk Profiling Model was built in stages, and at each stage a choice was '
    'made between alternatives. This record keeps those choices in one place so that a reviewer can see, for '
    'each one, what was decided, why, and what evidence supported it. Decisions are numbered as in the decision '
    'log kept with the code (DECISIONS.md); Annex A lists all of them.')
d.h2('1.2 The Model in Brief')
d.p('The model ranks every importer (IM4 and IM7) by compliance risk, using the last 24 months of their '
    'declarations. Each taxpayer receives a score from 0 to 100, a band from VERY LOW to VERY HIGH, up to three '
    'reasons in fixed wording, and notes on how much weight the score can bear. It has four layers.')
d.table('The Four Layers of the Model', ['Layer', 'What it does', 'Status'], [
    ['L1 Peer groups', 'Places each regular taxpayer (10 or more declarations) in a group of similar traders: '
     'main goods (HS section) x size tier', 'Adopted (decisions 44, 45)'],
    ['L2 Scorecard', 'Turns 8 agreed risk parameters into points that add up to at most 100', 'Adopted (decision 41)'],
    ['L3 Pattern check', 'Flags taxpayers whose overall trading pattern is unusual for their peer group', 'A note, no points (decision 46)'],
    ['L4 Score and band', 'Rounds the points and assigns a band; writes reasons and notes', 'Bands provisional (Stage 7)'],
], [3.5, 9.5, 4])
d.h2('1.3 Data')
d.p('The model reads one view prepared by Data Engineering in the `dm_modeled_ura_datascience` schema (its name is in the query template), '
    'with one row per declaration item. A single SQL query (one per snapshot date) turns it into one row per '
    'taxpayer: features from the 24 months before the snapshot and outcomes from the 6 months after it.')
d.table('Extracts Used in Release 1', ['Snapshot', 'Taxpayers', 'Declarations (24 months)', 'Share topped up', 'Hit rate in the 6 months after'], [
    ['30 Sep 2023', '49,699', '967,757', '8.5%', '12.8%'],
    ['31 Mar 2024', '51,138', '996,507', '9.1%', '11.4%'],
    ['30 Sep 2024', '53,927', '1,032,038', '9.4%', '7.5%'],
    ['31 Mar 2025', '55,110', '1,076,894', '8.6%', '7.2%'],
    ['30 Sep 2025', '56,691', '1,120,008', '7.7%', '7.2%'],
    ['31 Mar 2026', '58,161', '1,198,776', '6.5%', '7.0%'],
    ['30 Sep 2026 (live)', '57,501', '1,291,508', '5.4%', 'not yet known'],
], [3.5, 2.5, 4, 3, 4])
d.h2('1.4 Standard of Evidence')
d.p('Every setting was judged in a back-test on each of the six past snapshots, not on the average alone. The measure is **lift**: the hit rate, in the 6 months after the snapshot, of the taxpayers the '
    'model ranks in its top 1%, 5% and 10%, divided by the hit rate of all taxpayers. A lift of 4 means the top '
    'group was topped up four times as often as the average taxpayer. Every result is compared with a simple '
    'baseline, ranking on past top-up ratio alone. From decision 48, lift is reported together with the number of '
    'hits caught, the share of top-up revenue caught and the share of small traders in the top group, because '
    'lift alone can be raised by moving the top of the list onto small one-off importers.')
d.table('Lift Worked Through (31 March 2026, release 1 model)', ['Group', 'Taxpayers', 'Checked declarations', 'Hits', 'Hit rate', 'Lift', 'Share of all hits'], [
    ['Top 1%', '582', '2,469', '794', '32.2%', '4.6', '6%'],
    ['Top 5%', '2,908', '19,134', '7,162', '37.4%', '5.4', '56%'],
    ['Top 10%', '5,816', '26,471', '7,774', '29.4%', '4.2', '61%'],
    ['All taxpayers', '58,161', '182,868', '12,726', '7.0%', '1.0', '100%'],
], [3, 2.3, 3.2, 2, 2.2, 1.6, 2.7])
d.p('Lift is used rather than accuracy because only about 7% of checks end in a top-up: a model that predicted "no '
    'top-up" for everything would be 93% accurate and useless. What matters with limited inspection capacity is how '
    'much more each check finds when officers follow the top of the list.')
d.figure(chart(29), 'Hit rate in each tenth of the ranked list, and the share of all hits caught down the list')

# ------------------------------------------------------------------------------------ PART 2
d.part('PART 2: DATA DECISIONS',
       'This part records how the source view was checked and cleaned (Stage 1) and how the extracts were '
       'designed and accepted (Stage 2). Each cleaning rule exists because a specific check found a specific '
       'problem.')
d.h2('2.1 Cleaning Rules (Stage 1)')
d.table('Cleaning Rules and Their Evidence', ['#', 'Rule', 'Evidence (query)'], [
    ['1', 'Score IM4 and IM7 only', 'Transit and export regimes carry guarantees or suspended amounts, not duty paid (D2)'],
    ['2, 3', 'Valid 10-digit TIN only', 'All valid TINs have 10 digits; the 479,719 declarations without a TIN are all in IM8, PB4, PP4 and SE1 (C1, H3)'],
    ['4', 'Exclude cancelled declarations', 'About 14,065 cancelled declarations (D1)'],
    ['5', 'One row per item', '14,215 items stored more than once, adding 1,478,314 identical rows (B1, H1)'],
    ['6', 'Tax amounts once per declaration', 'Tax is repeated on every item row (B2)'],
    ['7, 17', 'Top-up = flag Y and final tax above original; amount = final minus original', 'On unflagged declarations top_up_amt equals the final tax 99.8% of the time (H2)'],
    ['8', 'Negative top-up = final tax below original', 'H2'],
    ['9', 'Blank original tax filled with the final tax', 'Blank on about 37% of unflagged declarations; blank means unchanged'],
    ['16', 'Prices judged within each HS code; below 1% of the HS median is an entry error', 'Price per kg runs from UGX 69 to 17 million across all goods (F3)'],
    ['43', 'APC 483 excluded', 'Destroyed or abandoned goods and dummy reconciliation entries (procedure code guidance of 19 Nov 2025)'],
], [1.5, 7, 8.5])
d.figure(chart(3), 'The three data problems behind the cleaning rules')
d.h2('2.2 Extract Design (Stage 2)')
d.bullets([
    '**Six back-test snapshots, six months apart** (Sep 2023 to Mar 2026), plus the live snapshot of Sep 2026. '
    'Every month in the view is complete to September 2026 (A2).',
    '**Features from the 24 months before the snapshot; outcomes from the 6 months after.** The model never sees '
    'the period it is judged on.',
    '**Lift is measured against each snapshot\'s own hit rate** (decision 22), because the hit rate fell from '
    'about 12% to about 7% after March 2024 (decision 21). The cause is a question for the Risk team.',
    '**All extracts passed the automatic checks** (decisions 19 and 25): one row per TIN, valid TINs, rates between '
    '0 and 1, hits never above checks.',
])
d.figure(chart(7), 'Share topped up and later hit rate by snapshot')

# ------------------------------------------------------------------------------------ PART 3
d.part('PART 3: SCORECARD DECISIONS',
       'This part records how the risk parameters were chosen, measured, protected against small counts, '
       'thresholded and weighted (Stages 3 and 4). The scorecard produces every point of the score.')
d.h2('3.1 The Small-Count Problem and Credibility Weighting')
d.p('Most taxpayers declare very little: 87% of IM4 and IM7 taxpayers have fewer than 10 declarations in 24 '
    'months, and 28,626 have exactly one. A rate built on one or two declarations can only be 0%, 50% or 100%. '
    'Left alone, these taxpayers filled 84% of the HIGH band. Each rate is therefore blended with the population '
    'average by the weight n / (n + 10), where n is the number of declarations (decision 31), and the blend may '
    'only lower a rate, never raise it (decision 35).')
d.table('Effect of the Weighting Strength K (March 2026, one-way weighting)', ['K', 'Small traders in HIGH and VERY HIGH', 'Lift top 1% / 5% / 10%'], [
    ['None', '5,254', '4.10 / 3.69 / 3.46'],
    ['5', '1,540', '4.05 / 3.52 / 3.19'],
    ['10 (adopted)', '538', '3.90 / 3.33 / 2.96'],
], [4, 7, 6])
d.p('Two-way weighting was rejected because it gave clean small traders points for other people\'s behaviour. '
    'A data-estimated strength was tested in the challenger round (decision 49): the data put K near 3, and '
    'two-way shrinkage moved small traders to the top of the list and caught fewer hits.')
d.figure(chart(12), 'Share topped up per taxpayer before and after weighting')
d.h2('3.2 How Each Parameter is Measured')
d.bullets([
    '**PAR_048 is measured over final tax, not original tax** (decision 32). Over original tax, a declared tax of '
    'UGX 29 produced a ratio of 4,399; 2,318 taxpayers were above 1. Over final tax the measure stays between 0 '
    'and 1, keeps the same order, and the officers\' thresholds convert exactly (6% becomes 5.7%, 33% becomes 24.8%).',
    '**PAR_045T is the officers\' business rule** "entries with top-up / total entries" (decision 42). Its maximum is '
    '40%, not the officers\' 10%: at 10%, 35% of regular traders scored full points and the scale stopped ranking.',
    '**PAR_045 stays as amendments** (decision 37).',
    '**Consignee measures were dropped** (decision 30): in IM4 and IM7 the consignee is always the taxpayer.',
])
d.figure(chart(14), 'The top-up ratio over original tax and over final tax')
d.h2('3.3 The Adopted Scorecard')
d.table('Scored Parameters, Thresholds and Weights', ['Code', 'Parameter', 'Concern from', 'Maximum at', 'L x I', 'Weight'], [
    ['PAR_045T', 'Declarations topped up', '3%', '40%', '5 x 5', '33%'],
    ['PAR_077', 'Severe top-ups (30% or more of final tax)', '2%', '20%', '4 x 5', '26%'],
    ['PAR_045', 'Declarations amended', '10%', '50%', '4 x 4', '21%'],
    ['PAR_048', 'Top-ups as a share of final tax', '5%', '25%', '3 x 1', '4%'],
    ['PAR_076', 'Value below HS benchmark', '2%', '20%', '3 x 1', '4%'],
    ['PAR_066', 'Tax reduced after assessment', '2%', '20%', '3 x 1', '4%'],
    ['PAR_105', 'Top-up within 180 days', 'no', 'yes', '3 x 1', '4%'],
    ['PAR_023', 'Clearance away from main station', '30%', '70%', '3 x 1', '4%'],
], [2.2, 6.3, 2.2, 2.2, 1.8, 1.8])
d.p('Each parameter scores 0 at its concern level, full weight at its maximum, and a straight line between. If '
    'a parameter cannot be computed for a taxpayer, the others are reweighted to still total 100. The likelihood '
    'and impact ratings are Data Science working ratings set from the back-test, to be confirmed with the Risk '
    'Officers.')
d.figure(chart(16), 'Lift at the top 5% for each parameter alone, the baseline and the scorecard')
d.table('Scorecard Options Tested (average of 6 snapshots)', ['Scorecard', 'Lift top 1% / 5% / 10%', 'Snapshots beating the baseline'], [
    ['Lean: PAR_045T + PAR_077 + PAR_045', '4.87 / 4.26 / 4.19', '6 / 4 / 3'],
    ['All 8, evidence weights (adopted, decision 41)', '4.62 / 4.49 / 4.05', '6 / 4 / 4'],
    ['Earlier 7-parameter card', '4.00 / 3.39 / 2.94', '6 / 2 / 1'],
    ['Baseline: past top-up ratio', '2.87 / 3.60 / 3.55', ''],
], [7, 5, 5])
d.p('All eight were kept because scoring them costs almost nothing in ranking and keeps every agreed parameter '
    'with data in the score and in the reasons officers read.')
d.h2('3.4 Officers\' Thresholds Compared')
d.table('Threshold Profiles Compared (one-way weighting, K = 10)', ['Profile', 'Lift top 1% / 5% / 10%', 'Regular / small traders in HIGH and VERY HIGH'], [
    ['Data Science provisional', '3.90 / 3.33 / 2.96', '740 / 538'],
    ['Officers (profile 1)', '3.76 / 3.29 / 2.99', '1,466 / 3,205'],
    ['Officers (profile 2)', '3.77 / 3.26 / 2.88', '1,002 / 1,149'],
], [5, 5, 7])
d.p('Both officer profiles are kept in the code for continued testing (decision 34). PAR_048 uses the band of '
    '5% to 25% of final tax and PAR_105 the officers\' yes or no rule (decision 40).')
d.h2('3.5 Coverage of the 20 Agreed Parameters')
d.table('Status of the 20 Agreed Parameters', ['Status', 'Parameters', 'Reason'], [
    ['Scored (8)', 'PAR_045, PAR_045T, PAR_077, PAR_048, PAR_076, PAR_066, PAR_105, PAR_023', 'Data available in the view'],
    ['Built, awaiting the next extract (2)', 'PAR_067 (price against own history), PAR_053 (exemption and watch-list APC use)', 'Query written; the source platform was unavailable'],
    ['Data not available (11)', 'PAR_012, PAR_016, PAR_051, PAR_054, PAR_096', 'Need earlier versions of each declaration'],
    ['', 'PAR_015, PAR_075', 'Boxes 45 and 46 not in the view'],
    ['', 'PAR_039, PAR_040', 'Penalties not in the view'],
    ['', 'PAR_078, PAR_173', 'Agent TIN not in the view'],
], [4.5, 7.5, 5])

# ------------------------------------------------------------------------------------ PART 4
d.part('PART 4: PEER GROUPS AND THE PATTERN CHECK',
       'This part records why HDBSCAN was dropped in favour of named peer groups (main goods x size), and why '
       'the pattern check became a note with no points (Stages 5 and 6).')
d.h2('4.1 Peer Groups: Main Goods x Size (decision 44)')
d.p('A peer group answers one question: who is this taxpayer compared with? It is used only by the pattern '
    'check; it never changes scorecard points. Only regular taxpayers (10 or more declarations) are grouped.')
d.bullets([
    '**Main goods**: the WCO HS section of the chapter where most of the taxpayer\'s customs value sits over the '
    '24 months (for example HS 87 is Vehicles).',
    '**Size**: the taxpayer\'s total customs value over 24 months, ranked among regular taxpayers in the same '
    'section and cut into thirds: small, medium, large. The cut-offs are recalculated each run.',
    '**Pooling**: a group with fewer than 30 taxpayers is merged into "Other goods, <size>" and its members carry the '
    '"no close peers" note.',
])
d.table('Size Cut-offs for the Largest Sections (March 2026, customs value over 24 months)', ['Section', 'Small', 'Medium', 'Large'], [
    ['Vehicles', 'under UGX 380M', '380M to 1.39B', '1.39B and above'],
    ['Machinery, electrical', 'under 845M', '845M to 3.65B', '3.65B and above'],
    ['Textiles', 'under 735M', '735M to 3.13B', '3.13B and above'],
    ['Minerals and fuel', 'under 3.3B', '3.3B to 50B', '50B and above'],
], [5, 4, 4, 4])
d.figure(chart(17), 'Regular taxpayers by main goods and size (48 peer groups)')
d.h2('4.2 HDBSCAN Tested and Dropped (decision 45)')
d.p('HDBSCAN groups points that sit in crowded neighbourhoods and labels every point in a thin area as noise. On '
    'the nine trading-structure measures it left 77.1% of regular taxpayers unclustered. The six groups it found '
    'were piles of single-product traders sharing identical counts (one HS heading, one origin, one item per '
    'declaration), mostly vehicle importers and one group of fuel importers. Loosening the settings only reduced '
    'noise to about 70%. Trade is a continuum, not a set of separate types, so a density method has no gap to cut along.')
d.table('Peer Group Methods Compared (March 2026)', ['', 'HDBSCAN', 'Main goods x size (adopted)'], [
    ['Groups', '6', '48'],
    ['Regular taxpayers without a real group', '77% (sent to the nearest group)', '2.5% (pooled)'],
    ['What a group means', 'A pile of single-product traders', 'A named trade and size, e.g. Textiles, large'],
    ['Pattern check lift, top 1% / 5% / 10%', '4.41 / 4.44 / 3.96', '4.09 / 4.34 / 3.88'],
    ['Without pattern points', '4.62 / 4.49 / 4.05', '4.62 / 4.49 / 4.05'],
], [6, 5.5, 5.5])
d.p('HDBSCAN was removed from the model code. The test remains in the notebook as the record of why.')
d.figure(chart(20), 'HDBSCAN on regular taxpayers: the six groups sit in one corner, the rest is noise')
d.h2('4.3 Pattern Check: a Note, Not Points (decision 46)')
d.p('The pattern check runs an Isolation Forest within each peer group. It measures how few random cuts are '
    'needed to isolate a taxpayer from their peers: the fewer, the more unusual. It never sees outcomes, so it '
    'finds what is rare, not what is risky. It was tested as up to 15 extra points for the most unusual 20% of '
    'each group.')
d.table('Lift by Points Allowed to the Pattern Check (average of 6 snapshots)', ['Pattern points', 'Top 1%', 'Top 5%', 'Top 10%'], [
    ['0 (note only, adopted)', '4.62', '4.49', '4.05'],
    ['Up to 5', '4.44', '4.45', '3.99'],
    ['Up to 10', '4.32', '4.41', '3.92'],
    ['Up to 15 (as tested)', '4.09', '4.34', '3.88'],
], [7, 3, 3, 3])
d.table('Later Hit Rate of Regular Taxpayers by Scorecard and Pattern (average of 6 snapshots)', ['Group', 'Hit rate in the 6 months after'], [
    ['Scorecard under 15 points, usual pattern', '2.8%'],
    ['Scorecard under 15 points, unusual pattern (top 20%)', '2.4%'],
    ['Scorecard 15 points or more, usual pattern', '23.0%'],
    ['Scorecard 15 points or more, unusual pattern', '24.7%'],
    ['All taxpayers', '8.8%'],
], [11, 6])
d.p('Among taxpayers the scorecard sees as low risk, the unusual ones were hit no more often than the usual ones. '
    'The most unusual 10% use 7.7 times as many HS headings, 3.7 times as many items per declaration and twice the '
    'origins of the usual half: general merchants and consolidators. Pattern points therefore pushed varied but '
    'clean traders above taxpayers with real top-up records. The check is kept as a note (code PAT) for taxpayers '
    'more unusual than 95% of their peer group (413 taxpayers in March 2026), because officers asked to be made '
    'aware of such cases. The outcome used here only sees top-ups on checked declarations; risks it cannot see '
    'remain possible, and the decision can be revisited if audit outcomes show otherwise.')
d.figure(chart(23), 'Later hit rate by scorecard level and pattern')

# ------------------------------------------------------------------------------------ PART 5
d.part('PART 5: SCORES, BANDS AND OUTPUTS',
       'This part records the output contract officers receive and the current state of the bands, which '
       'remain provisional until Stage 7.')
d.h2('5.1 Output Contract (decisions 26 to 29)')
d.bullets([
    'One model (`src/ctrp/core.py`, in the `ctrp` package) is used by the notebook, the command line (`main.py`) and production, so the same input always gives the same scores. Automatic tests check its promises (decision 55).',
    'Officers receive an Excel workbook with fixed sheets: Read me, Scores, Reasons, Parameter values, Band summary, Reason codes, Run info.',
    'Every reason is a fixed sentence per code, ordered by points then code. Notes (PAT, LIM, NPE, LAG, MIS) carry no points.',
    'Every output carries the model version and a fingerprint of all settings.',
])
d.h2('5.2 Bands (provisional)')
d.table('Bands and Results for March 2026 (model 1.0.0-dev4)', ['Band', 'Score', 'Taxpayers', 'Hit rate in the 6 months after'], [
    ['VERY LOW', '0 to 15', '44,245', '2.8%'],
    ['LOW', '16 to 35', '9,888', '5.8%'],
    ['MEDIUM', '36 to 50', '1,897', '10.7%'],
    ['HIGH', '51 to 80', '1,785', '43.0%'],
    ['VERY HIGH', '81 to 100', '346', '38.4%'],
    ['All', '', '58,161', '7.0%'],
], [4, 3, 4, 6])
d.p('The hit rate rises band by band to HIGH. VERY HIGH sits above HIGH in the four earlier snapshots but below '
    'it in September 2025 and March 2026; the dip is concentrated in scores of 71 to 90. Stage 7 will set the '
    'cut-offs against this evidence and against inspection capacity.')
d.figure(chart(32), 'Hit rate by band in every snapshot')

# ------------------------------------------------------------------------------------ PART 6
d.part('PART 6: CHALLENGER COMPARISON, ROUND 1',
       'This part records the first comparison of the scorecard against alternative models: the candidates of '
       'the June 2026 Scope, Architecture and Design document and the challengers identified by desk research.')
d.h2('6.1 How the Comparison was Run')
d.bullets([
    'Every challenger scores the same taxpayers and is measured the same way (code: `src/ctrp/models/challengers.py`).',
    'Models that learn from outcomes train only on earlier snapshots whose outcome window had closed. Tests run on '
    'September 2024, March 2025, September 2025 and March 2026.',
    'A challenger is called better or worse than the scorecard only where a 90% paired bootstrap interval of the '
    'top-5% lift difference excludes zero.',
    'Unsupervised candidates were given one-sided features (how far above the HS-section median each parameter '
    'sits, floored at zero), so they could only react to worse-than-peer behaviour.',
])
d.h2('6.2 Results')
d.table('Challenger Results (average of 4 test snapshots)', ['Model', 'Lift 1% / 5% / 10%', 'Hits in top 5%', 'Revenue in top 5%', 'Small traders in top 5%', 'vs scorecard (top 5%)'], [
    ['Scorecard (release 1)', '4.30 / 4.37 / 3.86', '5,522', '45%', '53%', ''],
    ['Baseline: past top-up ratio', '1.93 / 2.58 / 2.71', '807', '13%', '94%', '0 better, 2 worse'],
    ['Learned weights (logistic)', '4.11 / 5.00 / 4.49', '5,070', '38%', '59%', '3 better, 0 worse'],
    ['Data-estimated shrinkage', '4.88 / 3.97 / 3.50', '2,238', '35%', '78%', '0 better, 1 worse'],
    ['Monotone boosting (same 8 inputs)', '5.71 / 4.75 / 4.13', '5,809', '43%', '53%', '3 better, 1 worse'],
    ['Monotone boosting with size', '7.33 / 6.30 / 5.85', '3,508', '19%', '83%', '4 better, 0 worse'],
    ['Peer percentile (one-sided)', '3.65 / 3.48 / 2.62', '4,228', '45%', '53%', '0 better, 4 worse'],
    ['Ensemble: Isolation Forest + PCA', '3.49 / 2.13 / 1.26', '6,678', '50%', '42%', '0 better, 4 worse'],
    ['K-Means distance', '3.41 / 2.49 / 1.46', '6,424', '45%', '37%', '0 better, 4 worse'],
    ['Gaussian mixture', '3.38 / 1.20 / 1.15', '8,414', '57%', '28%', '0 better, 4 worse'],
], [4.5, 3.4, 2.2, 2.2, 2.4, 2.8], size=8)
d.figure(chart(34), 'Challengers and blends against the scorecard: lift, hits and revenue in the top 5%')
d.h2('6.3 Decisions from the Comparison')
d.table('Decisions from Challenger Round 1', ['#', 'Decision', 'Reason'], [
    ['47', 'The scorecard stays the release 1 model. Monotone boosting on the same 8 inputs and the learned-weight '
     'logistic scorecard go forward to round 2', 'Boosting gains about 0.4 lift and 5% more hits at the top 5% with the same revenue and trader mix, '
     'but is worse in 1 of 4 tests and learns from selectivity-driven outcomes; the scorecard is explainable in '
     'officers\' own thresholds'],
    ['48', 'Lift is always reported with hits caught, revenue caught and the small-trader share', 'Boosting with size reaches lift 6.3 by filling the top 5% with one-off importers, catching fewer hits and 19% of revenue'],
    ['49', 'One-way weighting at K = 10 stays', 'The data-estimated K (about 3) with two-way shrinkage pushed small traders up and caught 60% fewer hits'],
    ['50', 'The four Scope and Design candidates are not pursued as scorers', 'All lose on lift in 4 of 4 tests even with one-sided features; they catch revenue by picking large, high-volume traders'],
    ['51', 'Learned weights are taken to the ratings session as evidence', 'Outcomes put about 76% of the weight on PAR_045T, 14% on PAR_066, 6% on PAR_077 and none on amendments once top-ups are known'],
], [1.2, 7.3, 8.5], size=8.5)
d.figure(chart(36), 'Parameter weights: expert ratings against weights learned from outcomes')
d.h2('6.4 Ensembles')
d.p('A blend gives each taxpayer the average of their rank positions in its member models, so a taxpayer stays at '
    'the top only if several models agree. The stacked blend learns how much each member counts from earlier test '
    'snapshots (three tests only). The same protocol applies.')
d.table('Blends Against the Scorecard (average of 4 test snapshots)', ['Model', 'Lift 1% / 5% / 10%', 'Hits in top 5%', 'Revenue in top 5%', 'Small traders in top 5%', 'vs scorecard (top 5%)'], [
    ['Scorecard (release 1)', '4.30 / 4.37 / 3.86', '5,522', '45%', '53%', ''],
    ['Blend: all models', '4.53 / 4.57 / 3.94', '6,119', '46%', '52%', '2 better, 0 worse'],
    ['Blend: scorecard + boosting + learned weights', '5.24 / 4.80 / 4.32', '5,393', '42%', '55%', '3 better, 0 worse'],
    ['Blend: scorecard + Scope and Design candidates', '4.83 / 3.90 / 2.40', '6,680', '49%', '43%', '0 better, 2 worse'],
    ['Blend: scorecard + Gaussian mixture', '5.30 / 3.92 / 3.14', '6,673', '49%', '44%', '0 better, 2 worse'],
    ['Stacked blend (3 tests)', '2.17 / 3.95 / 3.92', '2,919', '21%', '72%', '1 better, 1 worse'],
], [4.5, 3.4, 2.2, 2.2, 2.4, 2.8], size=8)
d.table('Decisions on Ensembles', ['#', 'Decision', 'Reason'], [
    ['52', 'The blend of all models is the leading round 2 challenger; not adopted for release 1',
     'It is the only model that improves lift, hits and revenue together (better in 2 of 4 tests, worse in none). '
     'Everyone in its top 5% has 15+ scorecard points (median 57) and 85% overlap the scorecard\'s top 5%, so the '
     'reasons still apply. Not adopted yet: significant in only half the tests, the rank would no longer follow the '
     'points officers see, and eight models would run in production. Next: shadow run and blind officer review'],
    ['53', 'Stacked blend rejected for now', 'With three earlier windows to learn from, member weights swing between snapshots and lift at the top 1% falls to 2.2'],
    ['54', 'Blends with the Scope and Design candidates trade efficiency for volume', 'More hits and revenue, lower lift at 5% and 10%: evidence for OQ-1'],
], [1.2, 6.8, 9], size=8.5)

# ------------------------------------------------------------------------------------ PART 7
d.part('PART 7: OPEN QUESTIONS AND NEXT STEPS',
       'This part lists what remains to be decided, who must decide it, and the work planned for the next round.')
d.h2('7.1 Open Questions')
d.table('Open Questions', ['Ref', 'Question', 'Who decides'], [
    ['OQ-1', 'What should the list maximise: hit rate per check (efficiency) or hits and revenue caught (volume)?', 'Customs Risk Management with Data Science'],
    ['OQ-2', 'Confirm the likelihood and impact ratings, using the learned weights (decision 51) as evidence', 'Risk Officers (ratings session)'],
    ['OQ-3', 'PAR_045T maximum at 40% instead of 10%', 'Risk Officers'],
    ['OQ-4', 'APC 483 exclusion', 'Risk Officers'],
    ['OQ-5', 'Why the hit rate fell after March 2024', 'Risk team'],
    ['OQ-6', 'Band cut-offs, including the VERY HIGH dip, against inspection capacity (Stage 7)', 'Data Science with NTC'],
    ['OQ-7', 'Does the selectivity system keep a random inspection share, and are post-clearance audit results available? Either would give an unbiased test set', 'Customs Risk Management'],
], [1.5, 10, 5.5])
d.h2('7.2 Next Steps')
d.numbered([
    'Re-run the seven extracts with the version 2 query and score PAR_067 and PAR_053 once tested (Stage 4 method).',
    'Stage 7: set band cut-offs against the score distribution, the VERY HIGH dip and capacity.',
    'Challenger round 2: a shadow run of the all-models blend; monotone boosting and the learned-weight scorecard '
    'with an expert-anchored variant; an expected-revenue model; network features once agent TINs are available. '
    'Officers review the top taxpayers of each list without knowing which model produced them.',
    'Stage 8: review the top 50 taxpayers with the Risk Officers.',
])

# ------------------------------------------------------------------------------------ Annex
d.annex('Annex A: Decision Register')
d.p('Every numbered decision in the decision log, with its evidence, as recorded at the time.')
d.table('Decision Register', ['#', 'Decision', 'Evidence'], decisions_from_log(), [1.0, 7.5, 8.5], size=8)

d.save(OUT)
print('written', OUT)
