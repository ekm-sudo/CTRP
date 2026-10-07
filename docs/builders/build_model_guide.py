"""
Build the Model Guide (Word, URA house format): the plain-language explanation of the whole model.

What: writes docs/CTRP_Model_Guide.docx: what the model does, how every step works (with a worked
      example), how we know it works, what was tried and dropped, how to run it, how to change it,
      and how to answer the questions people will ask.
Why:  the person presenting and maintaining the model must be able to understand, explain, defend
      and modify it without reading the code first.

    python main.py docs        (or: python docs/builders/build_model_guide.py)

Needs the charts saved by the notebook (results/charts/chart_NN.png): run the notebook first.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # docs/builders
ROOT = HERE.parents[1]                          # the project folder
sys.path.insert(0, str(HERE))
from ura_doc import UraDoc  # noqa: E402

TEMPLATE = HERE / 'ura_template.docx'
LOGO = HERE / 'ura_logo.png'
CHARTS = ROOT / 'results' / 'charts'
OUT = ROOT / 'docs' / 'CTRP_Model_Guide.docx'
VERSION = '0.2'
DATE = 'October 2026'


def chart(n):
    return str(CHARTS / f'chart_{n:02d}.png')


d = UraDoc(TEMPLATE, logo=LOGO)
d.cover(['CUSTOMS TAXPAYER RISK PROFILING MODEL'], 'Model Guide: Understand, Explain, Defend and Change the Model',
        f'VERSION {VERSION}, {DATE.upper()} (DRAFT)')

# ================================================================================ front matter
d.front_heading('Document Control & Authority')
d.table('Document Information', ['Field', 'Details'], [
    ['Document Title', 'Customs Taxpayer Risk Profiling Model: Model Guide'],
    ['Version', f'{VERSION} (draft)'],
    ['Classification', 'Confidential'],
    ['Owner', 'Data Science Section, Data, Innovations and Projects Division, ITID'],
    ['Describes', 'Model version 1.0.0-dev4 and the ctrp project (src layout, run with main.py)'],
], [4, 13])
d.table('Document Version History', ['Version', 'Date', 'Author(s)', 'Role', 'Changes'], [
    ['0.1', DATE, 'Ethan Mugire', 'Officer, Data Science', 'First version, written alongside release 1.'],
    ['0.2', DATE, 'Ethan Mugire', 'Officer, Data Science', 'Lift explained step by step; ensembles; new project layout and commands.'],
], [1.5, 2.5, 3, 3, 7])
d.h2('Distribution')
d.p('This guide is for anyone who has to run, present, defend or change the Customs Taxpayer Risk Profiling '
    'Model: Data Science officers first, and any officer who joins the work later. It assumes no knowledge of '
    'the code. It is the teaching companion to the formal Model Development Decision Record.')
d.table('Audience', ['Audience', 'How to use this guide'], [
    ['Data Science officers', 'Read it front to back once. Then use Parts 7 and 8 as the manual for running and changing the model.'],
    ['Risk Officers and reviewers', 'Parts 1, 3, 4 and 9 explain what a score means and why it can be trusted.'],
    ['New contributors', 'Part 8 shows where everything lives in the code and the safe way to change it.'],
], [5, 12])
d.contents()
d.page_break()
d.front_heading('List of Acronyms')
d.table('Acronyms', ['Term', 'Meaning'], [
    ['APC', 'Additional Procedure Code (last 3 digits of the CPC)'], ['CPC', 'Customs Procedure Code'],
    ['CSV', 'Comma-separated values: the plain table file Hue downloads'], ['EPC', 'Extended Procedure Code (first 4 digits of the CPC)'],
    ['HDBSCAN', 'A clustering method that groups crowded points (tested and dropped)'],
    ['HS', 'Harmonized System: the commodity code'], ['IM4, IM7', 'Import for home use; import into a warehouse'],
    ['L x I', 'Likelihood times impact'], ['NTC', 'National Targeting Centre'], ['PCA', 'Principal Component Analysis'],
    ['SQL', 'Structured Query Language: the language Hue queries are written in'], ['TIN', 'Taxpayer Identification Number'],
    ['UGX', 'Uganda Shillings'], ['URA', 'Uganda Revenue Authority'],
], [3, 14])

# ================================================================================ PART 1
d.part('PART 1: THE BIG PICTURE',
       'What problem the model solves, what an officer actually receives, how the four layers fit together, and '
       'the handful of words you need for everything else in this guide.')
d.h2('1.1 The Problem in One Paragraph')
d.p('Customs cannot look closely at every importer. More than 58,000 taxpayers lodge about 1.2 million import '
    'declarations every two years. Officers need to know where to look first. Some importers have a long record '
    'of declarations that were later corrected upward (top-ups); some have a clean record; most have declared so '
    'little that nobody can tell yet. The model reads each taxpayer\'s last 24 months and puts them in order, '
    'riskiest first, with the reasons written out.')
d.note('In plain words', 'Think of a school with 58,000 students and a few teachers. The teachers cannot sit with '
       'every student, so they want a list: who most needs attention, and why. The model makes that list from '
       'each student\'s past marks, the same way for everyone.')
d.h2('1.2 What an Officer Receives')
d.p('For every taxpayer, the Excel workbook gives one row like this (a made-up taxpayer, worked through in full in Part 3):')
d.table('One Row of the Scores Sheet (made-up example)', ['Column', 'Value'], [
    ['Score', '26 (out of 100)'], ['Band', 'LOW'],
    ['Reason 1', 'PAR_045T: 15% of declarations needed a top-up (concern from 3%, maximum at 40%)'],
    ['Reason 2', 'PAR_077: 8% of declarations had a top-up of 30% or more of the final tax (concern from 2%, maximum at 20%)'],
    ['Reason 3', 'PAR_045: 25% of declarations were amended (concern from 10%, maximum at 50%)'],
    ['Notes', '(none: 40 declarations is enough history, the pattern is not unusual)'],
    ['Peer group', 'Textiles, medium'],
], [4, 13])
d.h2('1.3 The Four Layers as a Story')
d.table('The Four Layers', ['Layer', 'What it does', 'School analogy'], [
    ['L2 Scorecard', 'Eight risk measures, each turned into points; together at most 100', 'Marks in eight subjects, some subjects count more'],
    ['L1 Peer groups', 'Puts each regular taxpayer with similar traders (main goods x size)', 'Which class the student is in'],
    ['L3 Pattern check', 'Notes taxpayers who trade very differently from their peer group; adds no points', 'A note: "studies very differently from classmates"'],
    ['L4 Score and band', 'Rounds the points and gives a band: VERY LOW, LOW, MEDIUM, HIGH, VERY HIGH', 'The final grade'],
], [3.5, 8, 5.5])
d.p('Only the scorecard produces points. Everything else either tells you who the taxpayer is compared with, or '
    'adds a note to help the officer judge the score.')
d.h2('1.4 The Words You Need')
d.table('Key Words', ['Word', 'Meaning', 'Example'], [
    ['Declaration', 'One customs entry (an instance_id); it has one or more items', 'An import of 3 kinds of goods = 1 declaration, 3 items'],
    ['Top-up', 'Tax raised after assessment: flag Y and final tax above the original', 'Declared UGX 10M, assessed UGX 12M: top-up of 2M'],
    ['Amendment', 'The declaration was changed after lodging', 'HS code corrected'],
    ['Lane', 'How customs treats a declaration: red (physical check), yellow (documents), green (released)', ''],
    ['Hit', 'A red or yellow declaration that ended in a top-up', 'Checked and found short'],
    ['Hit rate', 'Hits divided by checked declarations', '70 hits in 1,000 checks = 7%'],
    ['Snapshot', 'The date we score taxpayers "as at"', '31 March 2026'],
    ['History window', 'The 24 months before the snapshot: where features come from', 'Apr 2024 to Mar 2026'],
    ['Outcome window', 'The 6 months after the snapshot: what actually happened next', 'Apr 2026 to Sep 2026'],
    ['Feature', 'A number computed per taxpayer from their history', 'Share of declarations topped up'],
    ['Parameter', 'A feature the officers agreed to score, with a code', 'PAR_045T'],
    ['Back-test', 'Score taxpayers at a past date, then check what happened next', 'Score at Mar 2026, check Apr to Sep 2026'],
    ['Lift', 'Hit rate of the model\'s top group divided by everyone\'s hit rate', 'Top 5% hit 31.5%, everyone 7%: lift 4.5'],
    ['Baseline', 'The simplest sensible rule, used as the bar to beat', 'Rank on past top-up ratio alone'],
], [3, 8, 6])

# ================================================================================ PART 2
d.part('PART 2: FROM RAW DATA TO ONE ROW PER TAXPAYER',
       'Where the data comes from, what the SQL query does step by step, why each cleaning rule exists, and '
       'why the model is never allowed to see the future it is judged on.')
d.h2('2.1 The Source')
d.p('Data Engineering built one view in Hue, in the `dm_modeled_ura_datascience` schema (its full name is in `src/ctrp/sql/features_outcomes.sql`). It has one row per '
    '**declaration item**, for every regime, from November 2012. Key columns: the declaration (`instance_id`) and '
    'item number, the date (`assessment_dt_wid`, as YYYYMMDD text), the taxpayer TIN, original and final tax, '
    'the top-up flag and amount, the amendment flag, the lane flags, the regime, station, HS code, CPC, origin, '
    'weights and the customs value.')
d.h2('2.2 What the Query Does, Step by Step')
d.p('The query lives in `src/ctrp/sql/features_outcomes.sql`. `python main.py sql` fills in the dates and writes one '
    'ready-to-run copy per snapshot into `sql/`. Each copy is a chain of small steps (called CTEs); each step '
    'reads the one before. In plain words:')
d.numbered([
    '**p**: the snapshot date.',
    '**raw**: keep IM4 and IM7 rows in the window, with a valid TIN, not cancelled, not APC 483; number each copy of an item.',
    '**items**: keep only the first copy of each item (the view repeats some items hundreds of times).',
    '**decl_all, decl**: one row per declaration: its tax, whether it was topped up, by how much, its lane.',
    '**hist and fut**: split declarations into the 24-month history (features) and the 6 months after (outcomes).',
    '**tp**: one row per taxpayer with every rate the scorecard uses (share topped up, amended, severe top-ups, and so on).',
    '**struct and dom**: how each taxpayer trades: number of HS headings, origins, CPCs, stations, items per declaration, main HS chapter.',
    '**bench, val, v76**: price checks: each item\'s price per kg against the median for its HS code, to measure value below benchmark (PAR_076).',
    '**outc**: what happened next: checked declarations and hits in the 6 months after.',
    '**final SELECT**: joins everything into one row per taxpayer: about 42 columns now, 57 in version 2.',
])
d.h2('2.3 Why Each Cleaning Rule Exists')
d.p('Every rule answers a problem found in the Stage 1 checks (`00_eda_cleaning.sql`). If you remember the problem, '
    'you remember the rule.')
d.table('Cleaning Rules Explained', ['Rule', 'The problem it fixes'], [
    ['IM4 and IM7 only', 'Other regimes (transit, export, re-export) hold guarantees or suspended duty, not duty paid. A "top-up" there means something else.'],
    ['One row per item', '14,215 items were stored more than once, adding 1.48 million identical rows. Counting them would multiply some taxpayers\' numbers.'],
    ['Tax once per declaration', 'The tax is repeated on every item row. Adding it per item would count a declaration\'s tax several times.'],
    ['Top-up = flag Y and final above original', 'On unflagged declarations, `top_up_amt` holds the FINAL tax, not a top-up (99.8% of the time). Reading it as a top-up would invent billions of shillings.'],
    ['Blank original tax = final tax', 'Blank means the tax never changed.'],
    ['Valid 10-digit TIN', 'All real TINs have 10 digits. The 479,719 declarations with no TIN are all in regimes we do not use.'],
    ['Prices judged within HS code', 'A kilogram costs UGX 69 for some goods and UGX 17 million for others. Only same-code comparisons are fair.'],
    ['APC 483 out', 'These are destroyed or abandoned goods and dummy reconciliation entries, not real trade.'],
], [5, 12])
d.figure(chart(3), 'The three data problems: repeated items, missing TINs, and what the top-up column really holds')
d.h2('2.4 Snapshots and Windows: Never Peek at the Future')
d.p('To test a model honestly, we pretend to stand at a past date, score everyone using only what was known then, '
    'and then look at what happened in the next 6 months. That is a back-test. We do it six times, six months apart.')
d.table('The Back-test Timeline', ['Snapshot (score "as at")', 'History used for features', 'Outcomes checked'], [
    ['30 Sep 2023', 'Oct 2021 to Sep 2023', 'Oct 2023 to Mar 2024'],
    ['31 Mar 2024', 'Apr 2022 to Mar 2024', 'Apr 2024 to Sep 2024'],
    ['30 Sep 2024', 'Oct 2022 to Sep 2024', 'Oct 2024 to Mar 2025'],
    ['31 Mar 2025', 'Apr 2023 to Mar 2025', 'Apr 2025 to Sep 2025'],
    ['30 Sep 2025', 'Oct 2023 to Sep 2025', 'Oct 2025 to Mar 2026'],
    ['31 Mar 2026', 'Apr 2024 to Mar 2026', 'Apr 2026 to Sep 2026'],
    ['30 Sep 2026 (live)', 'Oct 2024 to Sep 2026', 'Not yet happened'],
], [5, 6, 6])
d.note('In plain words', 'It is like checking a weather forecast: you only believe a forecaster whose predictions, '
       'written down BEFORE the day, turned out right. If the model could see the outcome window, it would be '
       'copying the answers, and its results would mean nothing.')
d.h2('2.5 Checking Each Download')
d.p('`python main.py check` runs simple tests on every CSV before it is used: one row per TIN, TINs are 10 digits, one '
    'snapshot date, rates between 0 and 1, no negative amounts, hits never above checks, and the row count is not '
    'a round number (a round number like 100,000 usually means Hue cut the download short). Any line marked CHECK '
    'must be looked at before modelling.')

# ================================================================================ PART 3
d.part('PART 3: HOW A SCORE IS MADE',
       'Every step from the taxpayer\'s row to their score, band and reasons, worked through with one made-up '
       'taxpayer whose numbers were computed by the real model code.')
d.h2('3.1 The Example Taxpayer')
d.p('A made-up textile importer, scored as at 31 March 2026 alongside the real population:')
d.table('The Example Taxpayer\'s History (24 months)', ['Measure', 'Value'], [
    ['Declarations', '40'], ['Declarations topped up', '6 (15%)'], ['Severe top-ups (30%+ of final tax)', '3 (7.5%)'],
    ['Declarations amended', '10 (25%)'], ['Original tax / top-ups', 'UGX 200M / UGX 16M'],
    ['Last top-up', '60 days before the snapshot'], ['Share cleared at main station', '80%'],
    ['Value below benchmark, tax reduced after assessment', 'none'],
], [9, 8])
d.h2('3.2 Step 1: Work Out the Measures')
d.p('`derive()` in `src/ctrp/core.py` computes the measures the SQL does not give directly:')
d.bullets([
    '**PAR_048** = top-ups / (original tax + top-ups) = 16 / 216 = **7.4%**. Measured over the final tax so it can never explode (Part 5.2).',
    '**PAR_105** = was there a top-up within 180 days? 60 days, so **yes** (1).',
    '**PAR_023** = share cleared away from the main station = 1 - 0.80 = **20%**.',
])
d.h2('3.3 Step 2: Protect Against Small Counts')
d.p('A rate built on very few declarations is mostly luck. Toss a coin twice: getting two heads (100%) does not '
    'mean the coin always lands heads. So each rate is blended with the population average:')
d.code(['weighted rate = w x own rate + (1 - w) x population average,   w = n / (n + 10)',
        'then keep the LOWER of the weighted rate and the own rate'])
d.p('For our taxpayer, n = 40 declarations, so w = 40 / 50 = 0.8. The population average share topped up is 6.5%:')
d.code(['0.8 x 15.0% + 0.2 x 6.5% = 13.3%   (lower than 15%, so 13.3% is used)'])
d.table('Small-count Weight for Different Histories', ['Declarations (n)', 'Weight on own rate', 'Meaning'], [
    ['1', '9%', 'Almost all population average: one event proves little'],
    ['2', '17%', ''], ['10', '50%', 'Half own record, half average'],
    ['40', '80%', 'Our example'], ['100', '91%', 'Own record dominates'], ['1,000', '99%', 'Practically raw'],
], [4, 4, 9])
d.note('Why only lower, never raise?', ['If the blend could raise a rate, a small trader with a perfect record (0 top-ups) '
       'would be pulled UP towards the average and get points for other people\'s behaviour. That is unfair and '
       'hard to explain. So the weighting can spare a small trader, but never accuse one.',
       'The officer still sees the RAW rate (15%) in the reason sentence; the weighted rate (13.3%) is only used to '
       'compute points.'])
d.figure(chart(11), 'Amendment rate by number of declarations: rates on few declarations are noise')
d.h2('3.4 Step 3: Put Each Measure on a 0 to 1 Ruler')
d.p('Each parameter has two officer-style thresholds: a **concern level** (below it, 0) and a **maximum** (at or '
    'above it, 1). In between is a straight line.')
d.code(['scaled = (value - concern) / (maximum - concern), held between 0 and 1',
        'PAR_045T: (13.3% - 3%) / (40% - 3%) = 0.278'])
d.figure(chart(13), 'Each parameter for regular taxpayers, with its concern level (dotted) and maximum (dashed)')
d.h2('3.5 Step 4: Weigh the Measures')
d.p('Each parameter has a likelihood (L) and an impact (I) rating from 1 to 5. Its weight is its L x I divided by '
    'the total of all L x I, times 100, so all weights add up to 100 points.')
d.table('Weights', ['Code', 'L x I', 'Weight (points available)'], [
    ['PAR_045T', '5 x 5 = 25', '25 / 76 x 100 = 32.9'], ['PAR_077', '4 x 5 = 20', '26.3'], ['PAR_045', '4 x 4 = 16', '21.1'],
    ['PAR_048, PAR_076, PAR_066, PAR_105, PAR_023', '3 x 1 = 3 each', '3.9 each'], ['Total', '76', '100'],
], [6, 4, 7])
d.p('If a parameter cannot be computed for a taxpayer (for example no items could be benchmarked), it is left '
    'out and the others are scaled up so the total available is still 100. The officer sees a MIS note.')
d.h2('3.6 Step 5: Add Up the Points')
d.table('The Example Taxpayer\'s Points', ['Code', 'Raw value', 'After small-count step', 'Scaled 0 to 1', 'Weight', 'Points'], [
    ['PAR_045T', '15.0%', '13.3%', '0.278', '32.9', '9.16'],
    ['PAR_077', '7.5%', '6.6%', '0.254', '26.3', '6.68'],
    ['PAR_045', '25.0%', '22.5%', '0.311', '21.1', '6.55'],
    ['PAR_048', '7.4%', '6.7%', '0.087', '3.9', '0.34'],
    ['PAR_076', '0%', '0%', '0', '3.9', '0'],
    ['PAR_066', '0%', '0%', '0', '3.9', '0'],
    ['PAR_105', 'yes (1)', '0.92', '0.92', '3.9', '3.63'],
    ['PAR_023', '20%', '19.3%', '0 (below 30%)', '3.9', '0'],
    ['**Total**', '', '', '', '100', '**26.36, rounded to 26**'],
], [2.4, 2.4, 3.2, 2.8, 2, 4.2])
d.p('Score 26 falls in the LOW band (16 to 35). Out of 58,162 taxpayers that day, it ranked 8,608th.')
d.h2('3.7 Step 6: Reasons and Notes')
d.p('Every parameter that earned points gets a fixed sentence, filled with the taxpayer\'s raw value. The three '
    'largest become Reason 1 to 3; all of them are on the Reasons sheet. Ties are broken by code, so two taxpayers '
    'with the same facts always get word-for-word the same reasons.')
d.table('Notes (no points)', ['Code', 'When it appears', 'What it tells the officer'], [
    ['PAT', 'Trading pattern more unusual than 95% of the peer group', 'Look at how this taxpayer trades; the score itself is unaffected'],
    ['LIM', 'Fewer than 10 declarations in 24 months', 'The score rests on little history'],
    ['NPE', 'Peer group too small, pooled into "Other goods"', 'The pattern check compared them with a mixed group'],
    ['LAG', 'Scorecard and pattern check point opposite ways', 'Worth a closer look either way'],
    ['MIS', 'Some parameters could not be computed', 'The rest were reweighted'],
], [1.6, 6.4, 9])
d.h2('3.8 Step 7: Peer Group and Pattern Note')
d.p('Regular taxpayers (10 or more declarations) are placed in a peer group: main goods (the HS section where most '
    'of their customs value is) x size (bottom, middle or top third by customs value within that section). Our '
    'example is "Textiles, medium". Within the group, an Isolation Forest measures how unusual each taxpayer\'s '
    'overall pattern is; the top 5% get the PAT note. Part 5 explains why this adds no points.')
d.h2('3.9 Step 8: The Band')
d.table('Bands (provisional until Stage 7)', ['Band', 'Score', 'Intended handling', 'Taxpayers, March 2026', 'Later hit rate'], [
    ['VERY LOW', '0 to 15', 'No routine attention', '44,245', '2.8%'],
    ['LOW', '16 to 35', 'Visible in monitoring', '9,888', '5.8%'],
    ['MEDIUM', '36 to 50', 'Reviewed where capacity allows', '1,897', '10.7%'],
    ['HIGH', '51 to 80', 'Prioritised for review', '1,785', '43.0%'],
    ['VERY HIGH', '81 to 100', 'Prioritised and escalated', '346', '38.4%'],
], [2.8, 2.2, 5, 3.6, 3.4])
d.figure(chart(27), 'Where the points come from, by band')
d.h2('3.10 The Workbook, Sheet by Sheet')
d.table('The Officers\' Workbook', ['Sheet', 'What is on it'], [
    ['Read me', 'What the file is, how to read a score, the bands, the status of the settings'],
    ['Scores', 'One row per taxpayer, highest risk first: rank, TIN, score, band, reasons 1 to 3, notes, flags'],
    ['Reasons', 'Every reason for every taxpayer, one per row, with the value, thresholds and points (for filtering)'],
    ['Parameter values', 'The value and points of every parameter for every taxpayer'],
    ['Band summary', 'Taxpayers, declarations and value per band'],
    ['Reason codes', 'Every code that can appear, with its fixed wording, thresholds and L x I'],
    ['Run info', 'Model version, settings fingerprint, snapshot, run time, input file'],
], [4, 13])

# ================================================================================ PART 4
d.part('PART 4: HOW WE KNOW IT WORKS',
       'How the back-test measures the model, how to read lift, what the results are, and the limits you must '
       'state honestly whenever you present them.')
d.h2('4.1 Lift, Step by Step')
d.p('Lift is the single most important number in this project, so here it is slowly, with the real numbers from '
    'the 31 March 2026 snapshot.')
d.numbered([
    '**Start with everyone.** In the 6 months after the snapshot, customs checked (red or yellow lane) 182,868 '
    'declarations from these 58,161 taxpayers. 12,726 of those checks ended in a top-up. So the hit rate for '
    'everyone is 12,726 / 182,868 = **7.0%**. If officers picked declarations to check at random, about 7 checks in '
    '100 would find a top-up.',
    '**Now take the top of the list.** The model\'s top 5% is 2,908 taxpayers. Their declarations got 19,134 checks, '
    'and 7,162 of them ended in a top-up. Their hit rate is 7,162 / 19,134 = **37.4%**: about 37 top-ups per 100 checks.',
    '**Divide the two.** Lift = 37.4% / 7.0% = **5.4**. Checks on the top of the list found top-ups 5.4 times as '
    'often as checks picked at random.',
    '**Read it.** Lift 1 means the list is no better than chance. Lift 2 means twice as good. Below 1 means worse '
    'than chance (the list is pointing at the wrong people).',
])
d.table('Lift at Three Cut-offs (31 March 2026)', ['Top of the list', 'Taxpayers', 'Checks', 'Hits', 'Hit rate', 'Lift', 'Share of all hits'], [
    ['Top 1%', '582', '2,469', '794', '32.2%', '4.6', '6%'],
    ['Top 5%', '2,908', '19,134', '7,162', '37.4%', '5.4', '56%'],
    ['Top 10%', '5,816', '26,471', '7,774', '29.4%', '4.2', '61%'],
    ['Everyone', '58,161', '182,868', '12,726', '7.0%', '1.0', '100%'],
], [2.8, 2.2, 2.4, 2, 2.2, 1.6, 3.2])
d.h3('Why lift matters')
d.p('Customs can only check a small share of declarations. The question that matters is therefore not "is the '
    'model right about everyone?" but "if officers follow the top of the list, how much more do they find per '
    'check?" That is exactly what lift measures. In this snapshot, the top 5% of taxpayers produced **56% of all '
    'hits**: following the list would put officers in front of more than half of the problems while looking at a '
    'twentieth of the taxpayers.')
d.note('Why not "accuracy"?', ['Only 7% of checks end in a top-up. A lazy model that says "no top-up" for every '
       'declaration is 93% accurate, and completely useless. Accuracy rewards being right about the easy majority. '
       'Lift only looks at the top of the list, where officers actually spend their time.'])
d.figure(chart(29), 'Left: hit rate in each tenth of the ranked list. Right: share of all hits caught as you go down the list')
d.p('The left chart shows the shape we want: one tall bar at the top (29% hit rate, lift 4.2) and short bars '
    'after it, all below average. The right chart shows the same thing as a running total: the blue line shoots '
    'up at the start (the top of the list catches most of the hits) while a random order would follow the dashed '
    'diagonal.')
d.note('How to say it in a meeting', 'If officers had checked only the taxpayers in the top 5% of the list, each '
       'check would have been more than five times as likely to find a top-up as a check picked at random, and '
       'they would have met more than half of all the top-ups found that half-year.')
d.h2('4.2 Why We Compare With a Baseline')
d.p('A model is only worth its complexity if it beats the simplest sensible rule. Our baseline ranks taxpayers on '
    'their past top-up ratio alone. Averaged over the six snapshots:')
d.table('Release 1 Model Against the Baseline (average of 6 snapshots)', ['Ranking', 'Lift top 1%', 'Lift top 5%', 'Lift top 10%'], [
    ['Scorecard (release 1)', '4.62', '4.49', '4.05'], ['Baseline: past top-up ratio', '2.87', '3.60', '3.55'],
], [7, 3.3, 3.3, 3.4])
d.p('Snapshot by snapshot, the model beats the baseline at the top 1% every time, and at the top 5% and 10% in '
    'four of six. It loses in the two earliest snapshots (2023 and early 2024), when past top-ups alone happened to '
    'predict unusually well; it wins clearly in the four latest. Say this openly if asked: it is the honest picture.')
d.figure(chart(31), 'Lift by snapshot: model against past top-ups alone')
d.h2('4.3 Do the Bands Mean Anything?')
d.p('If the bands work, the hit rate should climb band by band. It does from VERY LOW (2.8%) to HIGH (43%). VERY '
    'HIGH is the open problem: in the two latest snapshots it was hit less often than HIGH, with the dip in scores '
    '71 to 90. Stage 7 will look at what those taxpayers have in common before setting the cut-offs.')
d.figure(chart(32), 'Hit rate by band in every snapshot')
d.h2('4.4 Lift Is Not Everything')
d.p('Lift is a rate, so it can be raised by putting the "right" kind of small taxpayer at the top: an importer with '
    '2 declarations, both topped up, has a 100% hit rate but contributes 2 hits. A model doing this shows a high lift '
    'while catching fewer hits and less revenue. From decision 48, every comparison also shows hits caught, revenue '
    'caught and the share of small traders at the top (Part 6 has a real example).')
d.h2('4.5 The Limits You Must State')
d.bullets([
    '**Selection bias.** We only know the outcome of declarations that were checked, and the selectivity system chose '
    'which ones. It is like a teacher who only marks the homework they chose to collect: we never learn about the rest. '
    'The model may partly learn what selectivity already picks. The fix, in time, is a small random check share or '
    'post-clearance audit results.',
    '**The outcome is narrow.** It only sees top-ups on checked declarations. Risk that is never checked, or never '
    'found, cannot show up as a hit.',
    '**The base rate fell.** The hit rate dropped from about 12% to about 7% after March 2024. We judge each snapshot '
    'against its own rate, so this does not distort the comparison, but the cause is still unknown.',
    '**Flags are as they stand today**, not as they stood on the snapshot date. A top-up raised just after the '
    'snapshot on a declaration lodged just before it counts in the history. The effect is limited to a few weeks.',
    '**The six snapshots overlap** (each history window shares 18 months with the next), so they are not six fully '
    'independent tests. Consistency across them is still the best evidence we have.',
])

# ================================================================================ PART 5
d.part('PART 5: WHAT WE TRIED, WHAT WE DROPPED, AND WHY',
       'The choices most likely to be questioned. Each section tells the story: what was tried, what the evidence '
       'showed, and how to defend the decision in one sentence.')
d.h2('5.1 The Maximum for PAR_045T: 40%, Not 10%')
d.p('The officers\' rule says a taxpayer with more than 10% of declarations topped up is as bad as it gets. With 10% '
    'as the maximum, 35% of regular traders scored full points: they were all tied at the top, and the scale could '
    'no longer tell a 12% taxpayer from a 60% one. Ranked on this parameter alone, lift fell to 2.6; with a 40% maximum it was 5.3.')
d.note('Defend it in one sentence', 'We kept the officers\' concern level of 3%, and moved the maximum to 40% because '
       'a test that a third of the class passes with full marks cannot rank the class.')
d.h2('5.2 PAR_048 Measured Over Final Tax')
d.p('Top-ups divided by ORIGINAL tax explodes when the original tax is tiny: one taxpayer declared UGX 29 of tax and '
    'got a ratio of 4,399. 2,318 taxpayers were above 1. Dividing by FINAL tax (original plus top-ups) keeps the '
    'same order, stays between 0 and 1, and the officers\' thresholds convert exactly: 6% becomes 5.7%, 33% becomes 24.8%.')
d.figure(chart(14), 'The ratio over original tax explodes; over final tax it is bounded')
d.h2('5.3 One-way Small-count Weighting at K = 10')
d.bullets([
    '**No weighting**: 5,254 small traders in HIGH or VERY HIGH, many of them one-off vehicle importers with a single top-up.',
    '**K = 10, one-way**: 538, with a small cost in lift. Agreed as the fairer balance.',
    '**Two-way** (raising clean small traders towards the average): rejected, it accuses people for others\' behaviour.',
    '**K estimated from the data** (about 3) with two-way shrinkage, tested in the challenger round: it pushed small '
    'traders to the top and caught 60% fewer hits.',
])
d.h2('5.4 HDBSCAN Peer Groups: Dropped')
d.p('HDBSCAN looks for crowded neighbourhoods of points and calls everything in thin areas "noise". Picture a '
    'football field with people standing around: HDBSCAN only forms a group where people stand shoulder to '
    'shoulder. Our taxpayers do not stand in clumps; they spread smoothly from tiny to huge. The only crowded spots '
    'were piles of taxpayers with identical counts (one HS heading, one origin, one item per declaration). So '
    'HDBSCAN made 6 groups of single-product traders and left 77% of regular taxpayers as noise.')
d.figure(chart(19), 'Left: data with real clumps. Right: data like ours, a smooth spread plus a few piles')
d.figure(chart(20), 'HDBSCAN on our regular taxpayers: the six groups sit in one corner')
d.note('Defend it in one sentence', 'HDBSCAN found piles, not peers: it left three quarters of traders without a group, '
       'while main goods x size gives every regular trader a group an officer can name.')
d.h2('5.5 Pattern Points: Replaced by a Note')
d.p('The Isolation Forest plays a game of "20 random questions" to single a taxpayer out from their peer group: '
    '"more than 40 HS headings?", "IM7 share above 0.3?". A typical taxpayer needs many questions; an odd one needs '
    'few. It never sees outcomes, so it finds what is rare, not what is risky.')
d.figure(chart(21), 'Odd points are isolated in few cuts; the tested rule gave the top 20% up to 15 points')
d.p('A real example from March 2026, in the "Hides and leather, medium" group: 43 HS headings against a group norm '
    'of 1, 5 origins against 1, 4 stations against 1, never topped up, 1% amended against 33%. Scorecard: 0 points. '
    'Pattern check: most unusual in the group, 15 points. Next 6 months: 34 declarations, all 34 checked, 0 top-ups.')
d.figure(chart(23), 'Among low-scoring taxpayers, the unusual ones were hit no more often than the usual ones')
d.figure(chart(24), 'Lift by how many points the pattern check may add: 0 is best at every cut-off')
d.note('Defend it in one sentence', 'Unusual is not the same as risky: the pattern points pushed honest general '
       'merchants above taxpayers with real top-up records, so we kept the pattern as a note the officer can read.')
d.h2('5.6 Why All Eight Parameters, Not the Best Three')
d.p('A lean card of the three strongest parameters scored slightly higher at the top 1% (4.87 against 4.62) and '
    'slightly lower at 5% (4.26 against 4.49). Keeping all eight costs almost nothing in ranking and keeps every '
    'agreed parameter with data in the score and in the reasons officers read. The five weaker ones carry 4% each.')

# ================================================================================ PART 6
d.part('PART 6: THE CHALLENGER MODELS',
       'Other ways of ranking the same taxpayers, what each one is in plain words, how they did against the '
       'scorecard, and what happens next.')
d.h2('6.1 Why Test Challengers')
d.p('You can only call a model good next to its alternatives. The challengers include the candidates of the June '
    '2026 Scope, Architecture and Design document and the strongest ideas from desk research on customs and tax '
    'risk models (see the research report "Challenger models for customs risk").')
d.h2('6.2 Each Challenger in Plain Words')
d.table('The Challengers', ['Challenger', 'In plain words'], [
    ['Baseline', 'Rank on past top-up ratio alone.'],
    ['Learned weights (logistic regression)', 'Same 8 measures, but instead of officers choosing the weights, the computer finds the weights that best predicted past hits.'],
    ['Monotone boosting', 'Hundreds of tiny "if this measure is above X, add a little risk" rules added up. Monotone means a worse value can never lower risk. Additive means each measure\'s effect can still be read separately.'],
    ['Monotone boosting with size', 'The same, also told how big the taxpayer is. Kept as a warning case.'],
    ['Data-estimated shrinkage', 'The scorecard, but the small-count weighting strength is learned from the data and works both ways.'],
    ['Peer percentile', 'For each measure: how much worse than half of the taxpayers in the same HS section? Added up with the expert weights.'],
    ['Ensemble (Isolation Forest + PCA)', 'The design document\'s anomaly approach, given only "worse than peers" measures.'],
    ['K-Means distance', 'Groups taxpayers into 8 clusters; the further from the centre of your cluster, the riskier.'],
    ['Gaussian mixture', 'Fits a smooth "typical taxpayer" shape; the less likely you are under it, the riskier.'],
], [5, 12])
d.p('Fair play rules: models that learn from outcomes only train on earlier snapshots; all are tested on the four '
    'latest snapshots; "better" is only claimed when a bootstrap test (re-running the comparison on 300 resampled '
    'populations) says the difference is bigger than chance.')
d.h2('6.3 Results')
d.table('Challenger Results (average of 4 test snapshots)', ['Model', 'Lift top 5%', 'Hits in top 5%', 'Revenue in top 5%', 'Small traders in top 5%'], [
    ['Scorecard (release 1)', '4.37', '5,522', '45%', '53%'],
    ['Monotone boosting (same 8 inputs)', '4.75', '5,809', '43%', '53%'],
    ['Learned weights', '5.00', '5,070', '38%', '59%'],
    ['Monotone boosting with size', '6.30', '3,508', '19%', '83%'],
    ['Data-estimated shrinkage', '3.97', '2,238', '35%', '78%'],
    ['Peer percentile', '3.48', '4,228', '45%', '53%'],
    ['Ensemble IF + PCA', '2.13', '6,678', '50%', '42%'],
    ['K-Means distance', '2.49', '6,424', '45%', '37%'],
    ['Gaussian mixture', '1.20', '8,414', '57%', '28%'],
    ['Baseline', '2.58', '807', '13%', '94%'],
], [5.5, 2.6, 2.8, 3, 3.1])
d.figure(chart(34), 'Challengers and blends against the scorecard (dotted line)')
d.h2('6.4 What It Means')
d.bullets([
    '**The scorecard holds up.** Monotone boosting is a little better (more hits, same revenue, same kind of traders) in 3 '
    'of 4 tests and worse in 1. Not enough to replace a model officers can read in their own thresholds, but enough '
    'to test further in round 2.',
    '**The warning case** shows why lift alone misleads: boosting with size has the highest lift, but it filled the top '
    'with one-off importers and caught fewer hits and much less revenue.',
    '**The anomaly and clustering models lose on lift** but catch MORE revenue, because they pick big, high-volume '
    'traders. That is a different goal. Which goal the list should serve is a question for the Risk Officers (efficiency '
    'per check, or volume caught).',
    '**The learned weights** suggest that once the share topped up is known, amendments add little for this outcome. '
    'That is evidence for the ratings session, not an automatic change, because learned weights inherit selection bias.',
])
d.figure(chart(36), 'Weights chosen by officers (L x I) against weights learned from outcomes')
d.h2('6.5 Ensembles: Combining Models')
d.p('An ensemble combines several models instead of picking one. The simplest kind, used here, is a **blend**: each '
    'taxpayer gets the average of their rank positions in the member models. A taxpayer stays at the top only if '
    'several models agree. The idea is that models making different mistakes cover for each other: the Scope and '
    'Design candidates find big, high-volume traders, the scorecard finds frequent top-ups. A **stacked blend** goes '
    'one step further and learns from earlier snapshots how much each member should count.')
d.table('Blends Against the Scorecard (average of 4 test snapshots)', ['Model', 'Lift top 5%', 'Hits in top 5%', 'Revenue in top 5%', 'vs scorecard'], [
    ['Scorecard (release 1)', '4.37', '5,522', '45%', ''],
    ['Blend: all models', '4.57', '6,119', '46%', '2 better, 0 worse'],
    ['Blend: scorecard + boosting + learned weights', '4.80', '5,393', '42%', '3 better, 0 worse'],
    ['Blend: scorecard + Scope and Design candidates', '3.90', '6,680', '49%', '0 better, 2 worse'],
    ['Blend: scorecard + Gaussian mixture', '3.92', '6,673', '49%', '0 better, 2 worse'],
    ['Stacked blend (3 tests)', '3.95', '2,919', '21%', '1 better, 1 worse'],
], [6.5, 2.4, 2.6, 2.8, 2.7])
d.bullets([
    '**The blend of all models is the only model that improves all three measures together**: a little more lift, '
    '11% more hits and one more point of revenue, better in 2 of 4 tests and worse in none. Everyone in its top 5% '
    'also has 15 or more scorecard points, so the scorecard\'s reasons still explain them. It is the leading round 2 '
    'challenger (decision 52).',
    '**Why not adopt it now?** The gain is real but small and significant in only half the tests; the ranking would '
    'no longer follow the points officers see (a taxpayer with 55 points could rank above one with 60); and eight '
    'models would have to run and be maintained in production. A shadow run and a blind officer review come first.',
    '**Blends with the Scope and Design candidates** catch more hits and revenue but have lower lift: they trade '
    'efficiency for volume (decision 54). Which one URA wants is the open question OQ-1.',
    '**The stacked blend** is unstable with only three earlier windows to learn from (decision 53).',
])


# ================================================================================ PART 7
d.part('PART 7: RUNNING EVERYTHING',
       'Every command, in order, for Git Bash on Windows, with what each one produces and what to do when '
       'something goes wrong. Every run goes through one entry point: python main.py <command>.')
d.h2('7.1 One-time Setup')
d.p('Open Git Bash and go to the project folder. Install everything once (and again whenever requirements.txt '
    'changes). This also installs the project itself as a package called `ctrp`, so notebooks and scripts can '
    '`import ctrp` from anywhere. Then run the tests: they should all pass.')
d.code(['cd ~/Desktop/OCTOBER/ctrp', 'python -m pip install -r requirements.txt', 'python main.py test'])
d.p('To see every command: `python main.py --help`.')
d.table('All Commands', ['Command', 'What it does', 'Output'], [
    ['python main.py sql', 'Writes one Hue query per snapshot', 'sql/bt_<date>.sql, sql/live_<date>.sql'],
    ['python main.py check "data/*.csv"', 'Tests every download', 'PASS / CHECK report'],
    ['python main.py score data/live_2026-09-30.csv', 'Scores one extract (the production run)', 'results/CTRP_scores_<date>.xlsx and .csv'],
    ['python main.py backtest', 'Back-tests every data/bt_*.csv', 'results/CTRP_backtest.xlsx'],
    ['python main.py challengers', 'Compares challengers and blends (about 10 minutes)', 'results/CTRP_challengers.xlsx'],
    ['python main.py notebook', 'Rebuilds and runs the notebook (about 15 minutes)', 'notebook with outputs; results/charts/*.png'],
    ['python main.py docs', 'Rebuilds the decision record and this guide', 'docs/*.docx'],
    ['python main.py test', 'Runs the automatic tests (about 1 minute)', 'pass or fail'],
], [6, 6, 5])
d.h2('7.2 Make the Queries and Download the Extracts')
d.code(['python main.py sql'])
d.p('This writes `sql/bt_2023-09-30.sql` ... `sql/bt_2026-03-31.sql` and `sql/live_2026-09-30.sql`. For each one: '
    'open it, copy everything into a Hue editor, run it (it is one statement), download the result as CSV, and save '
    'it in `data/` with the SAME name (for example `data/bt_2026-03-31.csv`). To change the dates, edit '
    'BACKTEST_SNAPSHOTS and LIVE_SNAPSHOT at the top of `src/ctrp/extract.py` and run the command again.')
d.h2('7.3 Check the Downloads')
d.code(['python main.py check "data/*.csv"'])
d.p('Read the SUMMARY at the end: checks_failed should be 0 for every file. Look into any CHECK line before going on.')
d.h2('7.4 Score the Live Snapshot (production run)')
d.code(['python main.py score data/live_2026-09-30.csv'])
d.p('Writes `results/CTRP_scores_2026-09-30.xlsx` (the officers\' workbook) and a CSV copy, and prints the band counts '
    'with the model version and settings fingerprint.')
d.h2('7.5 Back-test and Challengers')
d.code(['python main.py backtest', 'python main.py challengers'])
d.p('The back-test writes the lift of the model and the baseline in every snapshot, and the hit rate by band. The '
    'challenger run writes the comparison of every challenger and blend, the learned weights and the stacked-blend weights.')
d.h2('7.6 The Notebook (all the analysis and charts)')
d.p('In VS Code: open `notebooks/CTRP_release1.ipynb`, choose the Python kernel (top right), click Run All. It takes '
    'about fifteen minutes; section 9 (challengers and blends) takes about ten of them. Every chart is also saved as a '
    'PNG in `results/charts/` (chart_01.png, chart_02.png, ...) ready for slides. From the command line instead:')
d.code(['python main.py notebook'])
d.p('The notebook is generated from `notebooks/build_notebook.py`. To change a cell permanently, change it there; '
    '`python main.py notebook` rebuilds the notebook and runs it.')
d.h2('7.7 Rebuild the Documents')
d.code(['python main.py docs'])
d.p('Run it after the notebook has saved the charts. Open the .docx in Word and accept "update the fields" (or press '
    'Ctrl+A then F9) to fill in the contents and the lists of tables and figures.')
d.h2('7.8 When Something Goes Wrong')
d.table('Common Problems', ['Message', 'Cause and fix'], [
    ['ModuleNotFoundError: No module named ...', 'A library is missing: run `python -m pip install -r requirements.txt`.'],
    ['ModuleNotFoundError: No module named ctrp (in the notebook)', 'Run the setup in 7.1, or open the notebook from the notebooks/ folder so it can find ../src.'],
    ['FileNotFoundError: data/...', 'The CSV is not in `data/` or has a different name. Check the name matches the query file.'],
    ['ValueError: more than one row for some TINs', 'The download is wrong (the query was changed or run twice). Re-run the query and download again.'],
    ['PermissionError when writing an .xlsx', 'The workbook is open in Excel. Close it and run again.'],
    ['check shows "rows not a round cut-off" as CHECK', 'Hue may have cut the download. Download again, making sure you take all rows.'],
    ['A test fails after you changed something', 'The change broke a promise the model makes (the test name says which). Fix it before scoring.'],
], [6.5, 10.5])

# ================================================================================ PART 8
d.part('PART 8: CHANGING THE MODEL SAFELY',
       'Where everything lives, the rules that keep changes safe and traceable, and step-by-step recipes for '
       'the changes you are most likely to make.')
d.h2('8.1 Map of the Project')
d.code([
    'ctrp/',
    '|-- README.md, LICENSE, .gitignore',
    '|-- pyproject.toml          project metadata and build configuration',
    '|-- requirements.txt        the environment (includes the package itself)',
    '|-- main.py                 entry point: python main.py <command>',
    '|-- src/ctrp/               the importable package',
    '|   |-- __init__.py         public API: score_snapshot, load_extract, backtest',
    '|   |-- core.py             THE MODEL: settings, four layers, reasons, back-test',
    '|   |-- utils.py            paths, reading an extract, lift and other measures',
    '|   |-- report.py           the officers\' Excel workbook',
    '|   |-- extract.py          Hue queries and the checks on each download',
    '|   |-- pipeline.py         score one file, back-test many',
    '|   |-- sql/features_outcomes.sql   the query, with @@DATE@@ placeholders',
    '|   +-- models/challengers.py       challengers and blends, compared fairly',
    '|-- tests/                  automatic tests on made-up data',
    '|-- notebooks/              CTRP_release1.ipynb and build_notebook.py',
    '|-- docs/                   DECISIONS.md, the Word documents, the research report, builders/',
    '|-- sql/                    generated queries; sql/analysis/ holds the Stage 1 checks',
    '|-- data/, results/         from Hue and outputs (contain TINs: never committed)',
    '+-- archive/                superseded scripts, kept for reference',
])
d.note('Why this layout?', ['It is the standard layout for Python projects. The model lives in one importable '
       'package (`src/ctrp`), separate from the things that use it (main.py, the notebook, the tests). Anyone who '
       'knows Python will know where to look, and nothing can accidentally import a half-finished script.'])
d.table('Main Functions in src/ctrp/core.py', ['Function', 'Job'], [
    ['derive(df)', 'Adds computed measures (PAR_048 over final tax, PAR_105, PAR_023, logs) and applies the small-count weighting.'],
    ['scale(x, zero_at, one_at)', 'The 0 to 1 ruler.'],
    ['layer2_scorecard(d)', 'Points per parameter per taxpayer.'],
    ['layer1_peers(d, log)', 'Main goods x size peer groups.'],
    ['layer3_pattern(d, peers, subtotal)', 'Isolation Forest percentile within each peer group (for the note).'],
    ['build_reasons, build_notes', 'The fixed sentences.'],
    ['score_snapshot(raw)', 'Runs everything; returns scores, reasons and parameter values.'],
    ['backtest(result, raw)', 'Lift of the model and the baseline against what happened next.'],
    ['load_extract(path) (in utils.py)', 'Reads a CSV, keeps TINs as text, refuses duplicate TINs.'],
], [6, 11])
d.h2('8.2 The Golden Rules')
d.numbered([
    'Change settings only in the SETTINGS block of `src/ctrp/core.py`, never further down.',
    'Raise MODEL_VERSION (for example 1.0.0-dev4 to 1.0.0-dev5) whenever a change can move a score.',
    'Run `python main.py test`. Every test must pass.',
    'Run `python main.py backtest` and compare with the previous version on lift, hits caught, revenue caught and small-trader share, in every snapshot.',
    'Record the decision in `docs/DECISIONS.md` with its evidence, then `python main.py docs`.',
    'Never put TINs, data or results in a shared repository (the .gitignore keeps them out).',
])
d.note('The fingerprint', 'Every output carries a 10-character settings fingerprint. It is computed from every '
       'setting, so if anyone changes a threshold, the fingerprint changes. Two workbooks with the same fingerprint '
       'were produced by exactly the same settings.')
d.h2('8.3 The Automatic Tests')
d.p('The tests in `tests/` run the model on made-up taxpayers (never real data) and check the promises it makes. If '
    'a change breaks one, the test says which.')
d.table('What the Tests Check', ['File', 'Promises checked'], [
    ['test_core.py', 'The ruler is 0 below the concern level and 1 at the maximum; band edges; the small-count weighting only lowers; weights add to 100 and missing parameters are reweighted; scoring is repeatable; the pattern check adds no points; every reason has points; the fingerprint changes with a setting'],
    ['test_utils.py', 'Lift of a perfect ranking beats random; lift of everyone is 1; TINs stay text; duplicate TINs are refused'],
    ['test_report.py', 'The workbook has the agreed sheets in the agreed order'],
    ['test_extract.py', 'Query dates are right and no placeholder is left; a clean download passes every check'],
    ['test_challengers.py', 'The comparison runs every model and blend'],
], [4, 13])
d.h2('8.4 Recipe: Change a Threshold')
d.p('Find the parameter in PARAMS (in `src/ctrp/core.py`) and change zero_at (concern level) or one_at (maximum). '
    'For example, to test a 35% maximum for PAR_045T:')
d.code(["dict(code='PAR_045T', col='top_up_entry_rate', zero_at=0.03, one_at=0.35, L=5, I=5, ..."])
d.p('Then raise MODEL_VERSION, run the tests and the back-test, and compare. The reason sentence updates itself '
    'because it reads the thresholds.')
d.h2('8.5 Recipe: Change a Weight')
d.p('Change L or I for the parameter. Weights are always L x I divided by the total, so changing one parameter '
    'changes everyone\'s share. A parameter with L of 2 or less is not scored at all (context only).')
d.h2('8.6 Recipe: Try the Officers\' Thresholds')
d.code(['from ctrp import core as M', "M.set_profile('officers_andrew')     # or 'officers_judith', 'adopted'",
        'result = M.score_snapshot(M.load_extract("data/bt_2026-03-31.csv"))'])
d.h2('8.7 Recipe: Add a New Parameter')
d.numbered([
    'Add the column to the final SELECT in `src/ctrp/sql/features_outcomes.sql` (build it in a new step if needed). Do not put semicolons in comments.',
    'Run `python main.py sql`, re-run the queries in Hue and download the CSVs again.',
    'If it is a rate between 0 and 1, add its column name to RATES in `src/ctrp/extract.py`; run `python main.py check`.',
    'Add a dict to PARAMS in `src/ctrp/core.py`: code, col, zero_at, one_at, L, I, fmt (\'pct\' or \'yesno\'), label, and a reason sentence using {v}, {z} and {o}.',
    'If it is a share of something other than declarations, add it to SHRINK_N with the column holding that count.',
    'Test it alone and inside the scorecard, as in notebook section 3.8 (lift at the top 5% against the baseline and the scorecard).',
    'Raise MODEL_VERSION, run the tests and the back-test, record the decision.',
])
d.h2('8.8 Recipe: Change the Bands')
d.p('Edit BANDS: each pair is (upper score, name). For example (15, \'VERY LOW\') means 0 to 15 is VERY LOW. The '
    'workbook colours and band summary follow automatically.')
d.h2('8.9 Recipe: Add a Challenger or a Blend')
d.p('In `src/ctrp/models/challengers.py`, write a function `score_mymodel(raw, d, train)` that returns one number per '
    'taxpayer (higher = riskier). `train` holds earlier snapshots as (raw, derived) pairs; use only those to learn. Add '
    'it to the CHALLENGERS dictionary. For a blend, add a line to BLENDS listing its members. Either way it is then '
    'measured exactly like the others.')

# ================================================================================ PART 9
d.part('PART 9: DEFENDING THE WORK',
       'The questions you are most likely to be asked, with short answers and where the evidence is.')
qa = [
    ['Why not a machine-learning model?', 'We tested several (Part 6). The best gained a little in 3 of 4 tests and lost in 1, and it learns from outcomes chosen by the selectivity system. The scorecard is explainable in the officers\' own thresholds. Boosting goes to round 2.'],
    ['You promised about 20 parameters; why 8?', '8 have data in the view, 2 more are built and wait for the next extract, and 11 need data that is not in the view (declaration versions, boxes 45 and 46, penalties, agent TIN). None was left out for any other reason.'],
    ['Why does a taxpayer topped up on 1 of 2 declarations score low?', 'Two declarations prove little (a coin tossed twice). The weighting spares them, and the LIM note tells the officer the score rests on little history.'],
    ['Why 40% and not the officers\' 10%?', 'At 10%, a third of regular traders hit full points and the list could not rank them. The concern level stays at their 3%.'],
    ['Isn\'t it just repeating the selectivity system?', 'Partly, possibly; all models trained or judged on checked declarations share this. It is why we want a random check share or audit outcomes, and why the expert scorecard (not fitted to past selections) is the safer release 1 choice.'],
    ['The design promised clustering and anomaly detection. Where are they?', 'Tested on real data: HDBSCAN left 77% of traders without a group, and anomaly points lowered lift because unusual is not risky. Both are recorded with evidence; the pattern check stays as a note.'],
    ['Is a lift of about 4.5 good?', 'It is well above the baseline (about 3.6 at the top 5%) and above the 3x minimum proposed in the design document for the top 10% (4.05), below its 5x target. Published customs figures score single declarations and are not comparable.'],
    ['Why is VERY HIGH hit less than HIGH recently?', 'Known and open. The dip is in scores 71 to 90 in the two latest snapshots. Stage 7 will study it before the bands are set.'],
    ['Why did the hit rate fall after March 2024?', 'Unknown; a question for the Risk team. Each snapshot is judged against its own hit rate, so it does not distort the results.'],
    ['Can importers game it?', 'The parameters come from customs\' own actions (top-ups, amendments, benchmarks), not from what importers report about themselves. Keep the reason codes internal.'],
    ['Why might a taxpayer change band between two runs?', 'Their 24-month window moves on, peers change and the population averages change. The fingerprint shows whether the settings changed too.'],
    ['What does provisional mean?', 'The thresholds, weights and bands are working values until the Risk Officers confirm them. Every workbook says so on the Read me sheet.'],
    ['Why not combine models (an ensemble)?', 'We tested five ways of combining them (Part 6.5). The blend of all models is the best all-round result and is the leading candidate for the next round; it was not adopted yet because the gain is small, significant in only half the tests, and the ranking would no longer follow the points officers see.'],
    ['Who decides thresholds and weights?', 'The Risk Officers, in a ratings session, using the evidence in this guide and the learned weights from Part 6 as input.'],
]
d.table('Questions and Answers', ['Question', 'Answer'], qa, [5.5, 11.5])

d.annex('Annex A: Settings Reference')
d.table('Settings in src/ctrp/core.py', ['Setting', 'Value', 'Meaning'], [
    ['MODEL_VERSION', '1.0.0-dev4', 'Raised whenever a change can move a score'],
    ['PARAMS', '8 parameters', 'Code, column, concern level, maximum, L, I, wording (Part 3)'],
    ['SHRINK_K', '10', 'Small-count weighting strength: w = n / (n + 10)'],
    ['SHRINK_N', 'PAR_076 uses items', 'Which count n each rate is weighted by (default: declarations)'],
    ['ADEQUATE_ENTRIES', '10', 'Below this: limited history, no peer group, no pattern note'],
    ['HS_SECTIONS', '21 WCO sections', 'Turns an HS chapter into a section name for peer groups'],
    ['MIN_GROUP_FOR_PATTERN', '30', 'Smaller peer groups are pooled into "Other goods, <size>"'],
    ['PATTERN_NOTE_PCT', '0.95', 'Pattern note for taxpayers more unusual than 95% of their group'],
    ['LOW_AGREE', 'see code', 'When the scorecard and pattern check are said to disagree'],
    ['BANDS', '15 / 35 / 50 / 80 / 100', 'Upper score of each band'],
    ['SEED', '42', 'Fixed randomness, so the same input always gives the same result'],
], [4.5, 3.5, 9])

d.save(OUT)
print('written', OUT)
