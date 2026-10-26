# How CTRP works

The Customs Taxpayer Risk Profiling model, explained from the ground up.

For a file-by-file reading guide with line numbers, see `docs/CODE_WALKTHROUGH.md`. To see every step on made-up
data, run `python notebooks/walkthrough_demo.py`.

Each section has two parts:

- **Simple version**: written for a 10-year-old. No prior knowledge assumed.
- **Technical version**: the real engineering and maths, with pointers to the code.

Every number here comes from the code (`src/ctrp/`) or from the decision log (`docs/DECISIONS.md`,
cited as "D" plus a number, e.g. D41). Model version `1.0.0-dev5`.

---

## Part 0. The words you need first

| Word | Simple version | Technical version |
|---|---|---|
| Taxpayer / TIN | A company that brings goods into Uganda. Its TIN is its ID number, like a student number. | A 10-digit Taxpayer Identification Number. Only IM4 (home use) and IM7 (into bond) importers are scored (D1, D2). |
| Declaration (entry) | The form a company fills in to say "I'm bringing in these goods, worth this much." | One customs declaration. One entry = entry number + station + year; only the latest declaration ID per entry is kept (rule R14, D109). |
| Item | One line on the form, such as "200 shirts." | One item row: HS code, origin, value, weight, procedure code (CPC/APC), tax. |
| HS code | A number for every kind of thing. Shirts get one number, cars another. | The Harmonised System tariff code. Chapter = first 2 digits, heading = first 4. Chapters group into 21 WCO sections (`core.HS_SECTIONS`). |
| Top-up | Customs checked and found the company paid too little tax, so the company had to pay more. | A declaration with `top_up_flg = Y` and final tax > original tax. Amount = final − original (D7). |
| Red / yellow lane | Red: customs opens the box and looks. Yellow: customs checks the papers. | Physical or documentary inspection. A **check** = a declaration that went red or yellow. A **hit** = a check that ended in a top-up. |
| Snapshot | A photo taken on one day: "what did we know about everyone on 31 March 2026?" | The scoring date. Features use the history before it. Outcomes use the 6 months after it. |
| Back-test | Pretend it's March 2026, make predictions, then look at what actually happened by September. | Score a past snapshot and compare with its closed 6-month outcome window. |

---

## Part 1. The big picture

### Simple version

Picture a school with 35,000 students and only a few teachers who can check homework. The teachers can't check
everyone. So they need a list: "Check these students first, because they're most likely to have made mistakes."

CTRP builds that list for customs. It looks at what each company did in the past and gives it a **score from
0 to 100**. A higher score means "more worth checking." It also writes down **why** in plain sentences, so an
officer never has to trust a mystery number.

There are two ways it looks at a company. We call them two **tracks**:

- **Track A (History)**: "Has this company been caught paying too little before?" Like a teacher remembering who
  copied homework last term.
- **Track B (Behaviour)**: "Does this company *act* strangely, even if it's never been caught?" Like a teacher
  noticing someone always hands in homework with suspiciously round answers, even though nobody has caught them
  cheating yet.

### Technical version

```
Data Lake view (vw_cstm_AEO_model, item-level rows)
   │  SQL: clean (R1–R15), one row per item, then per declaration, then per taxpayer
   ▼
Extract: one row per TIN, ~60 features + out_* outcome columns   (src/ctrp/sql/features_outcomes.sql)
   │
   ├── Track A  core.score_snapshot()
   │     L1 peer groups       HS section × size tier
   │     L2 scorecard         8 parameters → points → 0..100   (the score)
   │     L3 pattern check     Isolation Forest per peer group → a NOTE, no points
   │     L4 score and band    VERY LOW … VERY HIGH, reasons, notes
   │
   ├── Track B  discovery.score_snapshot_b()
   │     behaviour features → peer percentiles → monotone additive boosting
   │     → behaviour percentile, 2 reasons, Risky Behaviour Flag
   │
   └── report.two_tracks(): Overall Risk Band = higher of the two (Track B can lift to HIGH at most)
          ▼
   results/CTRP_scores_<date>.xlsx  (+ CSV of Track A scores)
```

Entry point for one run: `pipeline.score_file(path)`, or `python main.py score data/live_2026-09-30.csv`.

---

## Part 2. Getting the data ready (cleaning)

### Simple version

Before you can count anything, you have to make sure the list is right. Imagine your class list has some names
written twice, some crossed out, and some with spelling mistakes. If you count without fixing it, you get the
wrong answer.

The customs data had the same kinds of problems. Some items appeared up to 522 times. Some forms were cancelled.
Some forms were filed twice under different numbers. We wrote 15 rules to clean it, such as "count each item
once" and "ignore cancelled forms." We also removed cars and motorbikes. A separate model looks at those.

### Technical version

The rules live in the SQL (`src/ctrp/sql/features_outcomes.sql`, "cleaned item table"). The main ones:

| Rule | What | Why (evidence) |
|---|---|---|
| R1 | IM4 and IM7 only | Transit and export carry guarantees, not duty paid (D1) |
| R3 | Valid 10-digit TIN | D2 |
| R4 | Drop cancelled declarations | 14,065 cancelled (D4) |
| R5 | One row per item | The view joins each item to every inspection action, so items repeat up to 522 times (D5, D123) |
| — | Tax counted once per declaration | Tax is identical on every item of a declaration (D6) |
| — | Blank original tax = unchanged | Blank on ~37% of unflagged declarations (D9; an inference, flagged as such) |
| R13 | APC 483 out | Destroyed/abandoned goods and dummy reconciliations (D43, D61, D110) |
| R14 | Latest declaration ID per entry key | One entry can sit under several IDs (D109) |
| R15 | Motor vehicles out (HS 8701–8708, 8711) | A separate MV model covers them (D110, D112) |

After cleaning, about 33,000–35,000 taxpayers are scored per snapshot (D115).

---

## Part 3. Track A: the scorecard

This is the main model, and it makes the **History Risk Score**.

### 3.1 The eight parameters

#### Simple version

A scorecard works like a school report card. Instead of Maths and English, it grades 8 "subjects" about the
company's past. Each subject answers a question like "How often did this company have to pay extra tax?"

Some subjects count much more than others. If Maths counts 33% of your final grade and Art 4%, a bad Maths mark
hurts much more. Here the most important subject is "How often were you topped up?", at 33%.

#### Technical version

`core.PARAMS`. Each parameter is a rate over the taxpayer's history.

| Code | Measures | zero_at | one_at | L | I | L×I | Weight |
|---|---|---|---|---|---|---|---|
| PAR_045T | Share of declarations topped up | 3% | 40% | 5 | 5 | 25 | 32.9% |
| PAR_077 | Share with a severe top-up (≥30% of final tax) | 2% | 20% | 4 | 5 | 20 | 26.3% |
| PAR_045 | Share of declarations amended | 10% | 50% | 4 | 4 | 16 | 21.1% |
| PAR_048 | Top-ups as a share of final tax | 5% | 25% | 3 | 1 | 3 | 3.9% |
| PAR_076 | Declared price shortfall vs HS benchmark, share of value | 2% | 20% | 3 | 1 | 3 | 3.9% |
| PAR_066 | Share with tax reduced after assessment | 2% | 20% | 3 | 1 | 3 | 3.9% |
| PAR_105 | A top-up in the last 180 days (yes/no) | 0 | 1 | 3 | 1 | 3 | 3.9% |
| PAR_023 | Share cleared away from the main station | 30% | 70% | 3 | 1 | 3 | 3.9% |

**Weight = (L × I) / Σ(L × I)**. L is likelihood and I is impact, each rated 1 to 5. The total of L × I is 76.
Data Science set these working ratings from the back-test evidence (D41). They are still **provisional** until
the Risk Officers confirm them. They are **fixed**, not dynamic: nothing in the code learns or updates them. They
change only when someone edits `PARAMS`, and the settings fingerprint then changes too.

How PAR_045T gets 33 points: its L × I is 5 × 5 = 25, and 25 / 76 = 0.329, so it is worth up to 32.9 of the 100
points.

### 3.2 Turning a rate into points (the ramp)

#### Simple version

Think of a ramp. Below the bottom of the ramp you get 0 points: "nothing to worry about." At the top you get full
points: "as bad as it gets." In between, points go up steadily.

For "topped up," the bottom is 3% and the top is 40%. A company topped up on 2% of its forms gets 0. A company
topped up on 50% gets the full 33 points. A company at 20% sits about halfway up and gets about 15 points.

#### Technical version

`core.scale()`:

```
scaled = clip( (x − zero_at) / (one_at − zero_at), 0, 1 )
points = scaled × weight × 100
score  = round( Σ points )          → 0..100
```

Worked example. A taxpayer has 20% topped up, 5% severe, 15% amended, and zero on the other five parameters:

| | scaled | × weight | points |
|---|---|---|---|
| PAR_045T | (0.20−0.03)/0.37 = 0.459 | × 32.9 | 15.1 |
| PAR_077 | (0.05−0.02)/0.18 = 0.167 | × 26.3 | 4.4 |
| PAR_045 | (0.15−0.10)/0.40 = 0.125 | × 21.1 | 2.6 |
| **Score** | | | **22 → LOW** |

Missing values: if a parameter can't be computed for a taxpayer, the remaining weights are rescaled so they still
total 100, and a note (MIS) says so (`layer2_scorecard`).

Why 40% and not the officers' 10% for PAR_045T: at 10%, 35% of regular traders hit full points. The ramp then
stops separating them, and lift fell from 5.3 to 2.6 (D42).

### 3.3 Recent years count more (recency weighting)

#### Simple version

If you misbehaved three years ago but have been good since, a fair teacher cares more about this year. So this
year counts fully, last year counts half, and the year before that counts a quarter. A company that cleans up its
act can recover within about two years.

#### Technical version

`core.apply_recency()`, with `RECENCY_WEIGHTS = (1.0, 0.5, 0.25)`. This applies to the top-up, severe, amended and
tax-reduced rates, and to the top-up share of tax:

```
rate = (1·count_y1 + 0.5·count_y2 + 0.25·count_y3) / (1·decl_y1 + 0.5·decl_y2 + 0.25·decl_y3)
```

y1 is the latest 12 months. We tested this on 18 dates since Sep 2017. It beat "two equal years" on all 18
(AUC per check 0.817 vs 0.813), and it beat equal, gentler and steeper weightings (D92–D94).

### 3.4 Protecting small traders (credibility weighting)

#### Simple version

Say a new student hands in 2 homeworks and gets 1 wrong. That's "50% wrong," which sounds terrible. But with only
2 homeworks, it could just be bad luck. So when someone has done only a few, we don't fully trust their number. We
nudge it towards the class average.

There is one important rule: we only nudge **down**, never up. A new student with a perfect record is never
punished for what the rest of the class did.

#### Technical version

`core._shrink_small_counts()`, with `SHRINK_K = 10`:

```
w        = n / (n + K)                   n = declarations (items benchmarked for PAR_076)
prior    = declaration-weighted population average of the rate
adjusted = min( raw, w·raw + (1−w)·prior )          ← one-way: only ever lowers
```

Example: 1 top-up in 2 declarations is 50%. Suppose the prior is 5%. Then w = 2/12 = 0.167, and
adjusted = 0.167 × 50% + 0.833 × 5% = **12.5%**. The reason sentence still shows the raw 50%, so the officer sees
the truth.

Effect: small-history taxpayers in HIGH or VERY HIGH fell from 5,151 to 2,314 with the same top-1% lift (D31).
K = 0 loses 46% of hits. K is a policy dial between efficiency and volume (D68). Data-estimated two-way shrinkage
was tested and rejected: it moved small traders to the top and lost hits (D49).

### 3.5 Peer groups (Layer 1)

#### Simple version

It isn't fair to compare a giant fuel company with a tiny shop selling shoes. So we put companies into groups of
"similar kids": same kind of goods, same size. Examples: "big textile importers" or "small food importers."

#### Technical version

`core.peers_section_size()`. Peer group = **WCO HS section of the main chapter by value × size tercile** (small,
medium or large by 24-month customs value, ranked within the section). Only regular taxpayers with 10 or more
declarations get grouped. Groups with fewer than 30 members are pooled into "Other goods, <size>" and flagged NPE.
The result is about 48 named groups, with 2.5% pooled.

HDBSCAN clustering was tried and dropped. It left 77% of traders unclustered, because trade is a smooth continuum
and not separate clumps (D44, D45).

### 3.6 Pattern check (Layer 3): a note, not points

#### Simple version

Inside each group, we ask a computer to spot the "odd one out," like the one kid who brings 40 different snacks to
lunch. Being odd isn't the same as being bad, though. We tested it, and "odd" companies weren't caught more often.
So the computer only writes a note, "this one looks unusual, here's why," and adds **no** points.

#### Technical version

`core.layer3_pattern()`. One **Isolation Forest** per peer group (200 trees, seed 42), fitted on the 8 parameters
plus trading-structure features (`PEER_FEATURES`, `PATTERN_FEATURES`).

How an Isolation Forest works: it builds random trees that split the data at random points. Unusual taxpayers get
isolated in fewer splits, so a shorter average path length means more anomalous. `-score_samples` is turned into a
percentile within the group. At the 95th percentile or above, the taxpayer gets a PAT note that names the two
features where they sit furthest from the peer median.

Why no points: adding pattern points lowered lift at every cap (0 pts: 4.62/4.49/4.05 at top 1/5/10%; 15 pts:
4.09/4.34/3.88). The "unusual" taxpayers were mostly general merchants with many products, not later top-ups.
Unusual taxpayers under 15 points had a 2.4% hit rate against 2.8% for usual ones (D46).

**LAG note**: the score and the pattern disagree (score in the bottom 25% but pattern above 95%, or score in the
top 10% but pattern below 10%). This is worth a human look either way.

### 3.7 Bands, reasons and notes (Layer 4)

#### Simple version

The final score is turned into a colour-coded label, like grades A to E:

| Score | Band | Meaning |
|---|---|---|
| 0–15 | VERY LOW | No routine attention |
| 16–35 | LOW | No routine attention; visible in monitoring |
| 36–50 | MEDIUM | Reviewed where capacity allows |
| 51–80 | HIGH | Prioritised for review |
| 81–100 | VERY HIGH | Prioritised for review and escalation |

Every company also gets up to three reasons, written as fixed sentences. Two companies with the same facts get
exactly the same words, so it's fair.

#### Technical version

`core.BANDS`, `build_reasons()`, `build_notes()`. Reasons are ordered by points, then by code, and the template
is filled with the **raw** value. Notes carry no points:

| Note | Meaning |
|---|---|
| PAT | Unusual pattern |
| LIM | Fewer than 10 declarations |
| NPE | No close peer group |
| LAG | History and pattern disagree |
| MIS | Some parameters missing |

Every output carries `MODEL_VERSION` and a 10-character SHA-256 **fingerprint** of all settings. The same
fingerprint means the same settings (`config_fingerprint`).

Live Sep 2026 counts (D96, before the version 3 rebuild): VERY LOW 46,838, LOW 8,264, MEDIUM 1,326, HIGH 869,
VERY HIGH 204. The band cut-offs are still open (Stage 7), because they depend on officer capacity (OQ-8).

---

## Part 4. Track B: behavioural risk (discovery)

### 4.1 Why Track B exists

#### Simple version

Track A has a blind spot. It only catches companies that **have been caught before**. Imagine a teacher who only
watches kids who were in trouble last year. A kid who has been cheating quietly and never got caught would never
be on the list.

We checked, and that's exactly what happened. Every single company in Track A's top 5% had been caught before.
Companies with a clean record made up 69% of all companies, and they caused 9% of the later problems. Track A was
almost no better than guessing at finding those (D59).

So Track B ignores "were you caught before?" completely. It only looks at **how a company behaves**. Are its
prices strangely low compared with others selling the same thing? Does it keep changing its forms? Did it
suddenly start importing a lot more?

#### Technical version

Rule 1 of Track B (`discovery.py` header): **no input that records what customs did**. That means no top-ups, no
tax reductions and no lanes. Otherwise Track B would just copy the current selection process. Track B is judged on
taxpayers with **no top-up history** (`no_history()`), split into two segments: regular (10 or more declarations)
and small (under 10).

### 4.2 The behaviour features

`discovery.FEATURES`. Each feature has a direction (+1 = higher is riskier):

| Group | Features |
|---|---|
| Declaration behaviour | amended rate, unpaid tax rate, implausibly low (keying-error) price rate |
| Valuation | shortfall vs HS benchmark, items priced below half the benchmark, price deviation from other importers, price drop vs own history |
| Classification and duty | duty rate below HS peers, duty gap, value under exemption APCs, value under watch-list APCs, preferential treatment claimed |
| Trading pattern | sudden surge in declarations, station spread, same-day splitting above the norm (bulk goods excluded, D38), newness |

`goods_spread` (many kinds of goods per declaration) is computed but **dropped** from the model. It described
general merchants, not risk, and at one point it drove 506 of 510 flags (D99, `DROPPED`).

Rates get the same one-way credibility weighting as Track A, with K = 10.

### 4.3 Peer percentiles

#### Simple version

For each behaviour, we line up all the similar companies and ask: "Where does this one stand?" If its prices are
lower than 97 out of 100 similar companies, it's at the 97th percentile. That's easy to explain. "Your prices are
lower than 97% of companies like you" is a sentence anyone understands.

#### Technical version

`peer_percentiles()`. Each feature is multiplied by its direction, then ranked as a percentile within the
**HS section × size tier** group (`section_size_groups()`, all taxpayers, not just regular ones). Missing values
are set to 0.5, meaning no evidence either way. Percentiles make features with very different units comparable,
and they are robust to outliers.

### 4.4 The model: monotone, additive gradient boosting

#### Simple version

Now a computer learns from the past. We show it old snapshots: "Here's how companies behaved in 2023, and here's
who got caught in the next 6 months." It learns which behaviours matter most.

We gave it two strict rules so it can't do anything silly:

1. **Only upwards.** If a company's behaviour gets more suspicious, its score can only go up, never down. The
   computer is not allowed to learn "very low prices mean safe."
2. **One at a time.** The computer learns a separate curve for each behaviour and adds them up. So we can always
   say exactly how much each behaviour added. It's like a receipt: shirts 5,000, shoes 3,000, total 8,000.

#### Technical version

`discovery._boosting_model()`:

```python
HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, min_samples_leaf=300,
                               random_state=42,
                               monotonic_cst=[1]*n,                  # rule 1: risk only rises
                               interaction_cst=[[i] for i in range(n)])  # rule 2: no interactions
```

**Gradient boosting** builds many small decision trees one after another. Each new tree corrects the errors of the
ones before it. With `interaction_cst` putting every feature in its own group, each tree uses one feature only. The
model is therefore a **generalised additive model**:

```
logit(P(hit)) = f1(x1) + f2(x2) + … + fn(xn)
```

Each fi is non-decreasing (`monotonic_cst`). `min_samples_leaf=300` stops the model fitting tiny noisy pockets.

**Training target, hits per check.** `_rows()` turns each checked taxpayer into two weighted rows: a "hit" row
with weight = hits, and a "no hit" row with weight = checks − hits. The model then learns *P(a check finds a
top-up)*. A taxpayer checked 50 times does not count 50 times more by accident.

**No look-ahead.** One model is trained per segment (regular and small), only on earlier snapshots whose 6-month
outcome window had closed (`pipeline.training_extracts()`: snapshot ≤ scoring date − 6 months), and only on
no-history taxpayers.

### 4.5 Reasons, the flag and the Overall Risk Band

#### Simple version

Each company gets a behaviour percentile and two reasons, such as "Value below the HS benchmark: higher than 96%
of similar importers." The top 5% of clean-record regular companies, and the top 1% of clean-record small ones, get
a **Risky Behaviour Flag**.

Then the two tracks are combined. The final colour, the **Overall Risk Band**, takes whichever track says
"riskier." This does not mean Track B is the worse track. It means a clean history can't hide worrying behaviour.
There is one safety rule. Because Track B is new and hasn't been checked by officers yet, it can push a company up to HIGH but
never to VERY HIGH.

#### Technical version

Contributions (`score_snapshot_b`): for each feature c,

```
contribution_c = decision_function(x) − decision_function(x with c set to 0.5)
```

Because the model is additive, this is exact. It is the gap between feature c's curve at the taxpayer's percentile
and its curve at the peer median. The two largest positive contributions become the reasons.

`DISCOVERY_SHARE = {'regular': 0.05, 'small': 0.01}` are working values until the officers give their capacity.
`report.two_tracks()` sets `overall_band` and `driven_by` ("Compliance history" or "Trading behaviour"). Live Sep
2026: 510 flagged (120 regular, 390 small) (D74).

### 4.6 How good is Track B?

#### Simple version

It's better than guessing and better than Track A at finding these "never caught" companies, but only modestly.
There's a deeper problem. If a company undervalues goods and customs never catches it, our data never records a
"hit." So we can't fully grade Track B using past catches. That's why officers will do a **blind test**. They'll
look at 50 companies without knowing which 25 the model picked, and we'll see if they find more problems in the
model's 25.

#### Technical version

AUC per check within no-history taxpayers, 5 test dates (D95, D99):

| Segment | Track B (boosting) | Track A on the same group | Chance |
|---|---|---|---|
| Regular | 0.605 | 0.557 | 0.50 |
| Small | 0.583 | 0.536 | 0.50 |

The blind review design: 25 flagged and 25 random unflagged no-history taxpayers, shuffled under codes R01–R50,
with the key kept by Data Science (D86, `main.py blind-pack`). Track B passes if the flagged group draws clearly
more "Act" verdicts. **It has not yet been run**, and that is why the HIGH cap exists.

---

## Part 5. How we measured performance, and why these measures

### Simple version

To grade a "who to check" list, we use the back-test from Part 0. We pretend it's an old date, make the list, then
peek at what happened in the next 6 months. A good list puts the companies that really got caught near the top.

We used several grades, because any single grade can trick you:

- **Hit rate**: of the checks done on companies at the top of our list, how many found a problem?
- **Lift**: how much better is our top group than average? A lift of 4 means "4 times better than picking at
  random."
- **AUC**: pick one check that found a problem and one that didn't. How often did the problem one have the higher
  score? 50% is coin-flipping. 100% is perfect.
- **Money found**: how much of the extra tax was found among the companies we flagged?

We **didn't** trust "accuracy" (how many we got right). Here's why. If only 8 in 100 checks find a problem, a lazy
list that says "nobody is a problem" is 92% accurate and completely useless.

### Technical version

| Measure | Definition | Why we use it |
|---|---|---|
| **AUC per check** (headline, D84, D88) | ROC AUC where every red or yellow check is a case (hit or not) carrying its taxpayer's score. Implemented by duplicating each taxpayer into a hit row and a miss row, weighted by counts (`performance.per_check`). | Matches how officers judge selectivity (hits per check). A per-taxpayer label "≥1 top-up" rewards being checked often, so it partly measures how often customs looked. AUC is threshold-free and insensitive to the base rate. |
| Precision and recall at a line | Above a line (top 1/5/10/20%, VERY HIGH, HIGH+, MEDIUM+): hits ÷ checks, and share of all hits | Precision and recall only mean something once you fix who gets checked. HIGH+ is the line to quote once capacity is confirmed (D88). |
| Lift at top x% | hit rate of the top x% ÷ hit rate of everyone in that snapshot | Officer-friendly. Measured against each snapshot's own base rate, because the base rate fell from ~12% to ~7% after Mar 2024 (D21, D22). |
| Share of top-up money, revenue per check | top-up UGX caught above the line; UGX per check | Lift alone can be gamed (see "boosting + size" below). Revenue alone just rewards size: "largest importers" catch 53% of money at lift 0.52 (D56). |
| Small-trader share in the top group | % of the top 5% with under 10 declarations | Guards against filling the list with one-off importers (D48). |
| Paired bootstrap CI | 300 resamples of the difference in top-5% lift vs the scorecard, 90% interval | "Better" only counts when the interval excludes zero (`utils.paired_diff_ci`). |
| Hit rate by band | per band | Bands must be ordered: VERY HIGH 73% of checked taxpayers with a top-up vs VERY LOW 25% (D83). |

**Validation protocol (no cheating).**

1. **Out-of-time testing.** Supervised challengers train only on snapshots whose outcomes closed before the test
   date (forward chaining). Tests: Sep 2024, Mar 2025, Sep 2025, Mar 2026.
2. **18 test dates since Sep 2017** for Track A, using the long-run extract (D87, D91).
3. **The same population, measures and splits for every model** (`models/challengers.compare`).

**Selection bias, the honest caveat.** A hit can only happen where customs checked, and customs chose whom to
check. Outcomes therefore reflect past selectivity. This favours top-up-history features by construction, and it
cannot see undervaluation that was never caught (D33, D77). Random checks would fix this, but the view has no field
for why a declaration went red or yellow (D97).

### Track A results

- **AUC per check, 18 dates (Sep 2017 to Mar 2026): 0.74–0.86**, at or above 0.80 on 15 of 18. The one dip is
  Mar 2025 (0.74), when the hit rate per check halved (D91).
- **Version 3 data** (no motor vehicles, entry key, no APC 483): 0.780 / 0.797 / 0.837 on Mar 2025 / Sep 2025 /
  Mar 2026 (D115).
- **HIGH and above**: precision 50–63% up to Mar 2024, 27–30% in 2024–25, 42% in Mar 2026 (D91).
- **Feature contribution** (D99): alone, PAR_045T has AUC 0.81 and PAR_045 0.80. PAR_045T is the backbone.
  Dropping it costs 0.019 AUC. The small five add little against top-ups, but they cover risks that top-ups cannot
  see.
- **Stability** (D68): moving any main weight by ±50% keeps 95–98% of the same top 5%.
- **Sanity check** (D98): 87% of Authorised Economic Operators (AEOs, traders customs already trusts) sit in
  VERY LOW and only 1 in HIGH. The model agrees with the AEO programme.

---

## Part 6. The other models we tried (challengers)

### Simple version

We didn't just build one model and hope. We held a competition. About ten other ways of making the list each got
the same test. Some were "smart" computer methods. Some were very simple rules. A few were a little better at some
things, but none was clearly and reliably better and also easy to explain. So the scorecard stayed the champion.
The best runners-up are being watched in a "shadow run," which means running quietly in the background to see if
they keep winning.

### Technical version

Round 1 averages over 4 out-of-time tests (D47–D54). "vs SC" = number of tests where the 90% CI showed better or
worse at the top 5%.

| Model | What it is | Lift 1/5/10% | Hits top 5% | Money top 5% | Small in top 5% | vs SC |
|---|---|---|---|---|---|---|
| Baseline | Rank on past top-up ratio | 1.93 / 2.58 / 2.71 | 807 | 13% | 94% | 0 better / 2 worse |
| **Scorecard (champion)** | Part 3 | **4.30 / 4.37 / 3.86** | **5,522** | **45%** | 53% | — |
| Learned weights | Logistic regression on the 8 scaled parameters | 4.11 / 5.00 / 4.49 | 5,070 | 38% | 59% | 3 / 0 |
| Data-set shrinkage | Empirical-Bayes beta-binomial K | 4.88 / 3.97 / 3.50 | 2,238 | 35% | 78% | 0 / 1 |
| Monotone boosting | Same 8 inputs, monotone GBM | 5.71 / 4.75 / 4.13 | 5,809 | 43% | 53% | 3 / 1 |
| Boosting + size | Adds size features (warning case) | 7.33 / 6.30 / 5.85 | 3,508 | 19% | 83% | 4 / 0 |
| Peer percentile | Unsupervised, one-sided | 3.65 / 3.48 / 2.62 | 4,228 | 45% | 53% | 0 / 4 |
| IF + PCA ensemble | Isolation Forest + PCA reconstruction error | 3.49 / 2.13 / 1.26 | 6,678 | 50% | 42% | 0 / 4 |
| K-Means distance | Distance to nearest centroid | 3.41 / 2.49 / 1.46 | 6,424 | 45% | 37% | 0 / 4 |
| Gaussian mixture | Low likelihood = risky | 3.38 / 1.20 / 1.15 | 8,414 | 57% | 28% | 0 / 4 |
| Blend: all models | Average rank position | 4.53 / 4.57 / 3.94 | 6,119 | 46% | 52% | 2 / 0 |
| Stacked blend | Logistic regression on member ranks | 2.17 / 3.95 / 3.92 | 2,919 | 21% | 72% | 1 / 1 |

Round 2 (D66, D67): tuning boosting adds almost nothing (4.84 vs 4.75). "Boosting on top of the scorecard" leads
with lift 4.80 vs 4.37 and 6.5% more hits, better in 3 of 4 tests, worse in none. It goes to a shadow run and is
not adopted.

NTC's own rules (D104): the Business Risk scorecard has AUC 0.80 vs Track A 0.82, and is lower on all 18 dates.

**Why the scorecard won**, even though some challengers score higher on one measure:

1. **Explainable in the officers' own language.** Every point traces to one parameter and one sentence, with
   officer-sourced thresholds.
2. **Gains elsewhere weren't consistent.** Boosting was better in 3 of 4 tests and worse in 1.
3. **Learned weights inherit selection bias.** They learn "who customs checked" as much as "who is risky" (D51).
4. **Lift can be gamed.** "Boosting + size" hits lift 6.3 by filling the list with one-off importers. It finds
   fewer hits and a third less money. That's why lift is never reported alone (D48).
5. **Unsupervised methods find big or different traders, not risky ones.** They catch revenue only through many
   more checks on large importers. The Gaussian mixture used more than half of all checks for UGX 0.25M per check,
   against the scorecard's UGX 1.18M (D56).

---

## Part 7. Deploying to the Data Lake, Power BI and an API by Friday

### Simple version

Right now the model works like a recipe someone cooks by hand. Someone downloads the data, runs the program on a
laptop and gets an Excel file. You want a restaurant kitchen instead, where meals come out automatically and
anyone can order: Power BI, other systems through an API, and so on. Most of the cooking (the model) is ready. The
kitchen (the automatic pipeline, the shared table, the ordering window) still has to be built. A few ingredients
also still need the head chef's approval.

### Technical version: what exists vs what's missing

**Exists and works:**

- The feature SQL (`src/ctrp/sql/features_outcomes.sql`).
- The scoring code (`core.score_snapshot`, `discovery.score_snapshot_b`, `pipeline.score_file`).
- `datalake.py`, which pulls a query from the Spark Thrift Server over ODBC into a CSV (jump server only, port 2304).
- A fixed-layout Excel workbook, plus a CSV of the Track A scores.

**Not in the repo yet** (needed for your plan):

1. **No API.** There is no FastAPI or Flask code, and nothing in `requirements.txt` for serving.
2. **No write-back to the Data Lake.** Output goes to local `results/*.xlsx` and `*.csv` only.
3. **The CSV for Power BI lacks Track B and the Overall Risk Band.** `pipeline.score_file` writes
   `res.scores.to_csv(...)`, which is Track A only. `overall_band`, `discovery_percentile`, the flag and the
   behaviour reasons exist only inside the workbook (`report.two_tracks`).
4. **Track B retrains on every run.** It reads `data/bt_*.csv` from local disk at scoring time. Production needs
   either a saved, versioned model artefact or those training extracts available on the server.
5. **The feature query is heavy.** It takes about 30 minutes per date in Hue and must run as a scheduled Spark job.

**Recommended architecture:**

```
[Scheduled job, e.g. monthly]                       [Consumers]
 Spark SQL feature query ──► features table          Power BI ──(DirectQuery/Import)──┐
        │                                                                              │
 Python scoring job (core + discovery)                                                 ▼
        │                                                         ctrp.taxpayer_risk_scores  (Data Lake table)
        └──► writes ctrp.taxpayer_risk_scores ──────────────────►  ctrp.taxpayer_risk_reasons
             (partitioned by snapshot_date, model_version,          ▲
              fingerprint)                                           │
                                                      REST API (read-only): GET /taxpayers/{tin}/risk
                                                                            GET /scores?band=HIGH&snapshot=...
```

**Score in batch and serve by lookup.** Don't score on each API request. A score depends on peer groups,
percentiles and population averages computed across **all** taxpayers at once. Scoring one taxpayer on its own
gives a different, inconsistent answer. The API should read the stored table, so Power BI and the API always show
the same number.

**Suggested flat table for Power BI and the API** (one row per TIN per snapshot): `snapshot_date`, `taxpayer_tin`,
`rank`, `history_risk_score`, `history_risk_band`, `overall_risk_band`, `overall_band_set_by`,
`behaviour_percentile`, `risky_behaviour_flag`, `segment`, `reason_1..3`, `behaviour_reason_1..2`, `notes`,
`note_codes`, `peer_group_name`, the flags (limited history, no close peers, unusual pattern, disagree),
`declarations_24m`, `customs_value_24m`, `points_PAR_*`, `model_version`, `settings_fingerprint`. A second long
table holds the reasons. Keep the column names stable, as D64 already requires.

**Risks to raise before Friday:**

| Item | Status | Source |
|---|---|---|
| Weights and thresholds | **Provisional**, pending Risk Officers | `core.py` SETTINGS header, D41 |
| Version 3 rebuild | Only 3 of 7 full extracts redone | D114, D115 |
| Band cut-offs and list sizes | Open, waiting on officer capacity | Stage 7, OQ-8, `DISCOVERY_SHARE` |
| Track B | Blind review not yet run; capped at HIGH | D86, D74 |
| Cleaning rule R14 | "Highest ID = latest" still to be confirmed by officers | D109, E01 |
| Data protection | Outputs hold TINs. The table and API need access control and audit logging. | README rule 5 |
| Version label | README says `1.0.0-dev4`, code says `1.0.0-dev5` | `README.md`, `core.MODEL_VERSION` |

A realistic Friday target: a **pilot** release. Track A drives the dashboard. Track B is shown as "Risky
Behaviour Flag: for review." Both are labelled with the model version and fingerprint, and the dashboard carries a
note that the settings are provisional.

---

## Part 8. One-page recap

### Simple version

We clean the data. For each company, we count how often it was caught paying too little, how often it changed its
forms, and a few other things, with recent years counting more and tiny records nudged towards average. Those
become points out of 100 and a coloured band, with reasons in plain words. Separately, Track B looks only at
behaviour, to find companies that were never caught but act strangely. The final band takes whichever track says
"riskier." We
graded everything by pretending it was the past and checking what really happened. We held a competition against
about ten other methods. The scorecard won because it is nearly as good as the best and anyone can understand it.

### Technical version

A transparent, expert-weighted, piecewise-linear scorecard over recency-weighted and one-way credibility-shrunk
behavioural rates. It is complemented by an anomaly note (Isolation Forest per HS section × size peer group) and a
discovery track: monotone, interaction-free gradient boosting on peer percentiles, trained out-of-time on hits per
check among taxpayers with no top-up history. Evaluation uses AUC per check as the headline, with precision and
recall at operational lines, money captured, revenue per check and small-trader share. It is tested out-of-time on
18 dates (Track A) and 5 dates (Track B) with paired bootstrap comparisons. The known limitation is
selection-biased outcomes, to be addressed by the blind officer review and, later, by random-check or audit
outcomes.
