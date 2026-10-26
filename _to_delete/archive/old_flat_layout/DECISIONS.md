# Release 1: decision log

One line per decision, with the evidence behind it. Newest at the bottom of each stage.

## Plan

| Stage | What | Done when |
|---|---|---|
| 1 | EDA and cleaning rules | Every query in 00 has a result and every rule in the cleaning log has a decision |
| 2 | Extract features | 7 CSVs in data\, row counts checked |
| 3 | Feature EDA | Distribution and correlation of each parameter reviewed; scale points set |
| 4 | Scorecard only (Layer 2) | Back-tested across 6 snapshots against the past-top-up baseline |
| 5 | Peer groups (Layer 1) | Groups checked for whether they look like real kinds of trader |
| 6 | Pattern check (Layer 3) and full model | Full model back-tested; compared with stage 4 |
| 7 | Bands | Cut-points set against the score distribution and capacity |
| 8 | Review | Top 50 taxpayers reviewed with the Risk Officers |
| 9 | Write-up | Results and decisions recorded for the Design and Architecture Document |

## Stage 1: EDA and cleaning

| # | Decision | Evidence |
|---|---|---|
| 1 | Score regimes IM4 and IM7 only | D2: transit and export regimes carry guarantee or suspended amounts, not duty paid |
| 2 | Valid 10-digit TIN only | C2: all valid TINs are 10 digits; one 3-character TIN on 373 declarations |
| 3 | The missing-TIN gap does not affect the scored population | H3: IM4 and IM7 have no declarations without a TIN; the 480,000 are in IM8, PB4, PP4, SE1 |
| 4 | Exclude cancelled declarations | D1: 14,065 cancelled |
| 5 | Keep one row per item | B1, H1: 14,219 items repeated up to 522 times, copies identical |
| 6 | Tax amounts once per declaration | B2: identical on every item of a declaration |
| 7 | Top-up = flag Y and final > original; amount = final minus original | H2: top_up_amt equals the final tax on 99.5% of unflagged declarations |
| 8 | Negative top-up = final below original | H2 |
| 9 | Blank original tax treated as unchanged (filled with final) | H2: blank on about 37% of unflagged declarations; an inference, not stated in the data |
| 10 | Back-test snapshots Sep 2023 to Mar 2026; live Sep 2026 | A2: every month complete to Sep 2026; Oct 2026 partial |
| 11 | Lane flags tested with = 1 | E1: coded 1 or blank; one declaration can carry several lanes |
| 12 | Taxpayer names not used | C3, I1: addresses mixed in, typos, one name is a backtick |
| 13 | Preferential flag read as Y/N; the inf column dropped | E2: flag is Y or N (4% Y); inf is always blank |
| 14 | No currency conversion needed | F2: customs_value equals CIF in UGX for every currency |
| 15 | Fields complete enough to use as they are | F1: value, HS, origin and station never missing; weight and supplementary quantity missing on 0.01% |
| 16 | Price outliers judged within each HS code, not across all goods: below 1% of the HS median = entry error, kept out of PAR_076 | F3: UGX per kg runs from 69 to 17 million across all goods, mostly because commodities differ; a single cut would remove cheap bulk goods wrongly |
| 17 | top_up_amt confirmed as the final tax, not rounding | H2: on unflagged, unamended declarations it equals the final tax 99.8% of the time, median UGX 11.7 million; G1's top-up columns are therefore not used |
| 18 | Amended declarations whose tax rose without the top-up flag (about 3,000) are not counted as top-ups | H2: the flag is customs' own marking; to be tested as an alternative in stage 3 |

Stage 1 closed.

Open, for stage 3:
- Limited history. G2 (all regimes): 49,184 of 59,300 taxpayers (83%) have fewer than 10 declarations in 24 months. A rate built on 2 declarations swings from 0% to 50% on one event. How small counts are handled is decided in stage 3, once the IM4 and IM7 numbers are in front of us.
- Supplementary quantity is almost never missing. Check whether it holds a real quantity or a default (for example always 1) before relying on it for the per-unit price.

## Stage 2: extract features

| # | Decision or finding | Evidence |
|---|---|---|
| 19 | Six back-test extracts accepted: one row per TIN, valid TINs, rates in range, hits never above checks | check_extract.py: all tests PASS except the top-up ratio (below) |
| 20 | Population grows steadily: 49,699 to 58,161 taxpayers, 968,000 to 1.2 million declarations per 24-month window | check_extract.py summary |
| 21 | The top-up share and the hit rate fall over time, with a step down after March 2024: hit rate 12.8% and 11.4% in the first two outcome windows, then 7.0% to 7.5% in the last four | check_extract.py; to be raised with the Risk team (what changed around October 2024?) |
| 22 | Lift is measured against each snapshot's own hit rate, not a fixed one, so the fall in base rate does not distort the comparison | follows from 21; score_v2.py already does this |
| 23 | 86% to 87% of IM4 and IM7 taxpayers have fewer than 10 declarations | carried to stage 3 |

| 24 | Extreme top-up ratios are real, not errors: they come from a tiny original tax (UGX 29 behind the 4,399) on taxpayers with 1 to 3 declarations | look_top_up_ratio.py: 2,318 taxpayers above 1, 117 above 10 (Mar 2026); one regular importer (171 declarations) mostly zero-rated |
| 25 | Live extract accepted: 57,501 taxpayers, 1.29 million declarations, 5.4% topped up, no outcome window | check_extract.py |

Stage 2 closed.

## Outputs (agreed format)

| # | Decision | Why |
|---|---|---|
| 26 | One model file (ctrp_model.py) used by the notebook, the command line and production | The same input always gives the same scores, whichever way it is run |
| 27 | Officers' output is an Excel workbook with fixed sheets: Read me, Scores, Reasons, Parameter values, Band summary, Reason codes, Run info | Officers learn it once; any two runs can be compared |
| 28 | Every reason comes from a fixed sentence per code, ordered by points then code; notes (LIM, NPE, LAG, MIS) carry no points | Two taxpayers with the same facts get the same words |
| 29 | Each output carries the model version and a fingerprint of all settings | Any score can be traced to the settings that produced it |

## Stage 3: feature exploration (in progress)

| # | Decision or finding | Evidence |
|---|---|---|
| 30 | Consignee features dropped | In IM4 and IM7 the consignee is always the taxpayer: no variation |
| 31 | Credibility weighting at 10: each parameter = n/(n+10) x own value + 10/(n+10) x population average, n = declarations (items for PAR_076). Everyone is still scored | Small-history taxpayers in HIGH or VERY HIGH fall from 5,151 to 2,314 (Mar 2026) with the same top-1% lift (4.1). Agreed with Ethan; 10 to be re-checked once thresholds are set |
| 32 | PAR_048 measured as top-ups over FINAL tax; officers' 6% and 33% become 5.7% and 24.8% | Over original tax a declared tax of UGX 29 gave 4,399; a few outliers should not set the scale for everyone. Agreed with Ethan |
| 33 | PAR_077 / PAR_048 overlap: score one, show the other as information with no points; which one is decided by back-test | Correlation 0.76. Agreed with Ethan |
| 34 | Thresholds: test the officers' thresholds against the provisional ones, and keep testing until settled | Agreed with Ethan. Officers' workbook received: profiles 'officers_judith' and 'officers_andrew' built into ctrp_model.py |
| 35 | Weighting can only lower a value, never raise it | Two-way weighting gave clean small traders points for the population's behaviour; one-way spares them without inventing risk |
| 37 | PAR_045 stays as amendments | Ethan's decision |
| 38 | Splitting protected for bulk goods: HS chapters 25 and 27 and fuel EPCs 4080/7180 excluded; every other HS code measured against how often all importers repeat it on the same day (excess over the norm) | Ethan: construction and fuel legitimately arrive as many same-day declarations |
| 39 | Duty rate compared only on items with no exemption claimed (APC 000); exemption use and use of the memo's watch-list APCs (404, 409, 417, 451, 455, 457, 476, 479, 481, 482, 484) measured separately | AC-Trade memo CUS/T/9.5.5 (19 Nov 2025): an APC claims a rebate or exemption, so a low rate under one is expected; the memo marks the watch-list "look out for possible abuse" |
| 36 | Feature query version 2: price against own history, duty rate against HS peers, same-day splitting, new traders, per-origin price benchmark, price deviation (Feature Document 3.1, 3.4, 3.5) | Agreed with Ethan (items 1 to 7). Needs all seven extracts re-run |

Open, with the evidence (notebook section 3, run on model 1.0.0-dev2):
- Small counts. 87% of taxpayers have fewer than 10 declarations but carry 9% of declarations, 4% of tax and 14% of later hits. On provisional settings they fill 84% of the HIGH band. Half of them import mainly vehicles.
- PAR_048 over original tax explodes on tiny denominators; over final tax it is bounded and the officers' thresholds convert exactly (6% -> 5.7%, 33% -> 24.8%).
- PAR_077 and PAR_048 correlate at 0.76: the same behaviour counted twice.
- Scale points: on provisional settings, 56% of regular taxpayers are above concern on PAR_076 and PAR_045; thresholds look too low for those two.
- Provisional back-test: the model beats ranking on past top-ups at the top 1% and in the two latest snapshots, but not consistently at 5% and 10%.

## Stage 4: scorecard alone (in progress, Hue down so on the existing extracts)

Findings (6 snapshots, lift = later hit rate of the top group / everyone's; baseline = rank on past top-up ratio):
- Alone, the officers' PAR_045 rule (share of declarations topped up) is the strongest signal: lift 4.5 / 4.7 / 6.1 at top 1 / 5 / 10%, beating the baseline in all six snapshots.
- PAR_077 alone is strong at the top 1% (6.0). PAR_048 alone is weak (2.7), and dropping it from the scorecard costs little, so PAR_077 is the one to score (question 3).
- PAR_076 (1.3 to 1.7), PAR_105 (about 1), PAR_023 (below 1) and PAR_066 add no signal for this outcome. Removing each of PAR_076, PAR_105 and PAR_023 improves the scorecard.
- Caution: the outcome is a later top-up, so top-up measures are favoured by construction. Undervaluation that customs does not catch never shows as a hit, so a low lift for PAR_076 does not prove it is useless.
- A maximum set too low destroys ranking: with the officers' 10% as the maximum for the top-up share, 35% of regular traders score full points and lift falls to 2.6. With 40% it is 5.3.
- With that scale, weighting at 5 or 10 beats no weighting at the top 1% and 5%.
- The pattern check slightly lowers lift on current settings (3.30 against 3.39 at 5%); revisit after the peer groups are fixed (stage 5).
- Best lean scorecard tested: top-up share (3% to 40%) + PAR_077 + PAR_045 (amendments), weighting 10: lift 4.9 / 4.3 / 4.2, beating the baseline in 6 / 4 / 3 of 6 snapshots, against 4.0 / 3.4 / 2.9 for the current seven-parameter scorecard.

Decisions (agreed with Ethan unless stated):

| # | Decision | Evidence |
|---|---|---|
| 40 | PAR_048 uses Andrew's band (5% to 25% of final tax), PAR_105 the officers' yes/no (top-up within 180 days) | Same ranking quality as the provisional values; officer-sourced |
| 41 | Every agreed parameter with data is scored; weights set from the evidence (Data Science working ratings, to be confirmed with the officers): PAR_045T 33%, PAR_077 26%, PAR_045 21%, PAR_048, PAR_076, PAR_066, PAR_105, PAR_023 4% each | All eight with evidence-based weights: lift 4.6 / 4.5 / 4.1, beats baseline 6 / 4 / 4 of 6. The three-parameter lean card: 4.9 / 4.3 / 4.2 and 6 / 4 / 3. Scoring all of them costs nothing and keeps every agreed parameter in the score |
| 42 | PAR_045T = the officers' PAR_045 business rule (share of declarations topped up): concern 3% (officers), maximum 40% (not 10%) | At a 10% maximum, 35% of regular traders score full points and the scale stops ranking. To be explained to the officers |
| 43 | APC 483 excluded from the features | CPC memo: destroyed or abandoned declarations and dummy reconciliation entries. To be confirmed with the Risk Officers |
| 44 | Peer groups = main goods (HS section) x size tier, not HDBSCAN | HDBSCAN left 77% of regular traders without peers; section x size gives 48 named groups (e.g. "Textiles, large") with 2.5% pooled. Ranking quality about the same |

## Stage 5 and 6: peer groups and pattern check

- Pattern check on either grouping slightly LOWERS lift: scorecard alone 4.62 / 4.49 / 4.05; with pattern points (HDBSCAN) 4.41 / 4.44 / 3.96; (section x size) 4.09 / 4.34 / 3.88. Decision pending: keep 15 points, reduce, or show the pattern as a flag with no points until an outcome that can see non-top-up risk is available.
- Why HDBSCAN left 77% unclustered (notebook 4.2): trade is a smooth continuum, not separate types; the count features (HS headings, origins, CPCs, stations) create piles of taxpayers on identical values, and those piles become the only "groups" (all six are single-product traders, mostly vehicles, one of fuel); nine dimensions thin out density. Lowering the settings only moves noise from 77% to about 70%.
- What the pattern check reacts to (notebook 5.3): the most unusual 10% use 7.7 times as many HS headings, 3.7 times as many items per declaration and twice the origins of the usual half: general merchants and consolidators.
- Does it find extra risk (notebook 5.4, average of 6 snapshots)? Regular taxpayers under 15 scorecard points: hit rate 2.4% if unusual, 2.8% if usual. 15+ points: 24.7% unusual, 23.0% usual. It does not find top-up risk the scorecard misses.
- Lift by pattern cap (top 1 / 5 / 10%): 0 points 4.62 / 4.49 / 4.05; 5 points 4.44 / 4.45 / 3.99; 10 points 4.32 / 4.41 / 3.92; 15 points 4.09 / 4.34 / 3.88.
- Recommendation: flag only (0 points), shown as a note. Awaiting Ethan's decision.

## Stage 7: bands (open)

- Hit rate climbs VERY LOW to HIGH in every snapshot. VERY HIGH is above HIGH in the four earlier snapshots but below it in Sep 2025 (19% vs 36%) and Mar 2026 (31% vs 41%); also with the pattern check at 0 points. To be examined when setting the cut-offs.
- Live (Sep 2026) has fewer HIGH and VERY HIGH taxpayers (793 and 272) than Mar 2026 (1,774 and 431), in line with the lower top-up share in the live window (5.4% against 6.5%).

## The 20 agreed parameters: where each one stands

| Parameter | Status | Why |
|---|---|---|
| PAR_045 Declarations amended | Scored | |
| PAR_045 officers' rule (share topped up), code PAR_045T | Scored | |
| PAR_077 Severe top-ups | Scored | |
| PAR_048 Top-ups over tax | Scored | |
| PAR_076 Value below benchmark | Scored | Interim benchmark: the tariff specification benchmarks are not in the view |
| PAR_066 Negative top-ups | Scored | |
| PAR_105 Recent top-ups | Scored | |
| PAR_023 Station movement | Scored | |
| PAR_067 Unit value reduced | Built, awaiting Hue | Stand-in: price against own history (versions not in the view) |
| PAR_053 Tax forgone through exemptions | Built, awaiting Hue | Measured as exemption APC use and watch-list APC use |
| PAR_012 Original vs final declaration | Data not available | Needs earlier versions of each declaration; the view holds only the final state |
| PAR_015 Undervaluation risk (box 45) | Data not available | Adjustment rate (box 45) not in the view |
| PAR_016 Misclassification | Data not available | Needs HS changes between versions or the misdeclaration flag; neither in the view |
| PAR_039 Number of penalties | Data not available | Penalties / seizure report not in the view |
| PAR_040 Value of penalties | Data not available | Penalties and statistical value (box 46) not in the view |
| PAR_051 Preferential declarations amended | Data not available (use rate shown) | Amendment needs versions; preferential use is shown as information |
| PAR_054 Procedure codes amended | Data not available | Needs procedure code changes between versions |
| PAR_075 Customs vs statistical value | Data not available | Statistical value (box 46) not in the view |
| PAR_096 HS changes that lowered duty | Data not available | Needs HS changes between versions |
| PAR_078 Agent enhanced duty | Data not available | Agent TIN not in the view; belongs to the agent model |
| PAR_173 Agents with risky clients | Data not available | Agent TIN not in the view; belongs to the agent model |

Summary: 8 scored now (counting the officers' PAR_045 rule), 2 more built and awaiting Hue, 11 blocked only because the data is not in the view. Additional risk indicators built beyond the 20: duty below HS peers, watch-list APC use, splitting beyond the norm, new traders, price deviation.
