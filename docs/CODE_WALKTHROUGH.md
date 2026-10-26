# CTRP code walkthrough: Track A and Track B

A guide for reading the code with a reviewer. It follows one production run from the data to the Overall Risk
Band, file by file, with line numbers (as of this commit). For the ideas behind the code in plain language, see
`docs/CTRP_How_It_Works.md`.

## 0. Before you start (5 minutes)

```bash
python -m pip install -r requirements.txt
python main.py test                         # 57 tests should pass
python notebooks/walkthrough_demo.py        # prints every step for one made-up taxpayer
```

The demo uses **made-up data** (`tests/conftest.py: make_extract`), so it runs anywhere and shows no real TINs.
Keep its output open beside the code. Every number it prints comes from the function named in its heading.

## 1. The whole run on one page

```
python main.py score data/live_2026-09-30.csv
  └─ pipeline.score_file()                       src/ctrp/pipeline.py:25
       ├─ utils.load_extract()                   one row per TIN, TINs kept as text
       ├─ core.score_snapshot()                  TRACK A        src/ctrp/core.py:511
       │    Step 1 derive()                      :243  (apply_recency :218, _shrink_small_counts :265)
       │    Step 2 layer2_scorecard()            :353  (scale :285)
       │    Step 3 layer1_peers()                :315  (peers_section_size :319)
       │    Step 4 layer3_pattern()              :386  (note only, no points)
       │    Step 5 score, band_of :290, build_reasons :448, build_notes :469, rank
       ├─ pipeline.training_extracts()           earlier snapshots whose 6-month outcome had closed
       ├─ discovery.score_snapshot_b()           TRACK B        src/ctrp/discovery.py:232
       │    fit_models() :217  → prepare() :167 → build_features() :120 → peer_percentiles() :154
       │                       → _train_rows() :198 → _boosting_model() :208
       │    score, contributions, reasons, Risky Behaviour Flag
       └─ report.write_workbook()                src/ctrp/report.py:107
            └─ two_tracks() :94                  Overall Risk Band
```

Where the input comes from: `src/ctrp/sql/features_outcomes.sql` builds one row per taxpayer. It cleans item rows
(line 43), builds one row per declaration (87), then the scorecard rates (123), the yearly counts for recency
(163), the trading structure (212), the PAR_076 price benchmark (240), the Track B behaviour features (314–428),
and the 6-month outcomes used only for back-testing (440).

## 2. Track A: `src/ctrp/core.py`

Read it in this order.

| # | Where | What to look at | Question it answers |
|---|---|---|---|
| 1 | Docstring, lines 1–30 | The four layers and the five steps | What happens, in what order |
| 2 | `PARAMS`, line 71 | Each parameter: column, `zero_at`, `one_at`, L, I, reason sentence. The comment above it works out every weight. | What is scored, and how much it counts |
| 3 | `SHRINK_K` 114, `RECENCY_WEIGHTS` 123, `BANDS` 176 | The three other numbers that shape a score | How small traders, old years and bands are handled |
| 4 | `config_fingerprint`, 210 | A SHA-256 of every setting, stamped on each output | How to tell two runs used the same settings |
| 5 | `score_snapshot`, 511 | Steps 1 to 5, each marked in the code | The whole of Track A in about 60 lines |
| 6 | `apply_recency`, 218 | `(1·y1 + 0.5·y2 + 0.25·y3) / (same for declarations)` | Why recent years matter more |
| 7 | `_shrink_small_counts`, 265 | `min(raw, w·raw + (1−w)·prior)` with `w = n/(n+10)` | Why 1 top-up in 2 declarations isn't 50% risk |
| 8 | `layer2_scorecard`, 353 | Ramp, then weights re-spread over the available parameters, then points | Where every point comes from |
| 9 | `peers_section_size`, 319 | HS section × size tercile, groups under 30 pooled | Who a taxpayer is compared with |
| 10 | `layer3_pattern`, 386 | One Isolation Forest per peer group. Returns percentile, the low-agreement flag and the evidence text. | Why "unusual" is a note, not points |
| 11 | `build_reasons` 448, `build_notes` 469 | A fixed sentence per parameter, filled with the **raw** value | Why the same facts always give the same words |
| 12 | `backtest`, 595 | Top x% vs everyone, and vs "past top-ups only" | How the model was judged |

## 3. Track B: `src/ctrp/discovery.py`

The file reads top to bottom in the order the code runs. Sections 1 to 5 are production. Section 6 is the
back-test only.

| Section | Lines | What to look at |
|---|---|---|
| Docstring | 1–40 | Three honesty rules (no customs actions as inputs, train only on the past, every feature has a risk direction) and the two model rules |
| 1. Settings | 46–90 | `FEATURES` (column, direction, count it rests on, label), `DROPPED`, `SEGMENTS`, `DISCOVERY_SHARE` |
| 1b. Who it is for | 96–104 | `no_history()`: no top-up in 24 months. `in_scope(raw, segment)` adds the segment. |
| 2. Features | 109–140 | `build_features()`: surge, station spread, newness, plus the extract's behaviour columns, credibility-weighted |
| 3. Peer percentiles | 145–180 | `peer_percentiles()`: rank within HS section × size tier, missing = 0.5. `model_columns()`: the features every snapshot has |
| 4. The model | 184–227 | `_rows()`: two weighted rows per checked taxpayer, so it learns **hits per check**. `_boosting_model()`: the two rules. `fit_models()`: one model per segment. |
| 5. Production | 232–271 | `score_snapshot_b()`: score, exact per-feature contribution, top 5% / 1% flagged, two reasons |
| 6. Back-test | 275–end | `evaluate()`: train on snapshots 0..t−1, test on t, against a no-learning composite, learned weights, Track A and single features. `compare_without()`: the same test with one feature removed. |

Then `src/ctrp/report.py:94`, `two_tracks()`, which joins the two tracks into the Overall Risk Band.

## 4. Questions a reviewer is likely to ask

**Are likelihood (L) and impact (I) dynamic?**
No. They are fixed numbers in `PARAMS` (`core.py:71`). Data Science set them from the back-test evidence (D41),
and they stay **provisional** until the Risk Officers confirm them. Nothing in the code learns or updates them.
Changing one means editing `PARAMS`, raising `MODEL_VERSION` and re-running the back-test. The settings
fingerprint changes automatically, so any output shows which settings produced it. A learned version exists as a
challenger ("Learned weights", `models/challengers.py`). It wasn't adopted, because weights learned from past
checks copy whom customs chose to check (D51).

**Where does "33 points" come from?**
It's the most points PAR_045T (share of declarations topped up) can give:

```
L × I for each parameter: 5×5 = 25, 4×5 = 20, 4×4 = 16, and 3×1 = 3 for each of the other five
total                   : 25 + 20 + 16 + 5×3 = 76
PAR_045T weight         : 25 / 76 = 0.329  →  32.9 of the 100 points
```

A taxpayer gets all 32.9 only at or above the maximum level (40% topped up). Below that they get a share of it:
`(rate − 3%) / (40% − 3%) × 32.9`. At 20% topped up that's 0.459 × 32.9 = 15.1 points. Run the demo to see this
table for one taxpayer.

**What are the two strict rules for Track B's boosting?** (`discovery.py:208`)

1. `monotonic_cst=[1]*n`, **monotone**. Each feature can only push the score up as it gets worse. The model can
   never learn "very low prices = safe."
2. `interaction_cst=[[i] for i in range(n)]`, **additive**. Each feature is learned on its own curve, and the
   curves are added. That's why `score_snapshot_b()` can give each behaviour's exact share of the score (score
   minus the score with that feature at the peer median) and turn the two largest into reasons.

A third safeguard: `min_samples_leaf=300` stops the model learning from small, noisy pockets.

**"The Overall Risk Band is the worse of the two." What does that mean?**
It does **not** mean Track B is the worse track. It means the Overall Risk Band takes the **riskier** of the two
results (`report.py:94`):

- If Track B flags a taxpayer and their History band is below HIGH, the Overall band becomes HIGH.
- Otherwise, the History band stands.

The reason is that a clean history shouldn't cancel strong evidence from behaviour. Track B can lift a taxpayer to
HIGH but never to VERY HIGH, because officers haven't yet reviewed Track B's list (D74).

How to improve the combination:

1. **Run the blind review** (D86) before trusting the flag further. If flagged taxpayers draw clearly more "Act"
   verdicts, allow VERY HIGH for flags with strong evidence.
2. **Show both bands side by side** in Power BI (History band and Risky Behaviour Flag), and use the Overall band
   only as a sort key, so officers see *why* someone is HIGH.
3. **Require two independent signals** before a flag lifts a band, and cap any one feature's share. In an early
   run, one feature drove 506 of 510 flags (D99). That feature is now dropped, but the rule would stop it
   happening again.
4. **Size the list to capacity.** `DISCOVERY_SHARE` (5% regular, 1% small) is a working value until officers say
   how many they can review.

How to improve Track B itself:

1. **More test dates.** See the next question.
2. **Use the full behaviour features on every training date.** `model_columns()` keeps only features present in
   **every** training snapshot. If any training extract is version 1, the version 2 features (duty against peers,
   exemptions, price against own history, splitting, newness) are dropped from the model entirely. All dates need
   version 2/3 extracts.
3. **Better outcomes.** A top-up can't show undervaluation that customs never caught. Seizures and penalties,
   post-clearance audit findings, NTC missed-revenue results and the officers' review verdicts would all be better
   labels (data request, D106).
4. **Save the trained model** (joblib, with version and training dates) instead of retraining on every run.

**Why only 5 test dates for Track B, when Track A has 18?**

- Track B needs the **full extracts**, the item-level behaviour features. Those are built per item (prices against
  peers, duty, exemptions), so they can't be added up from the half-year "long run" that gave Track A its 18 dates
  (D87).
- Each full extract is about a 30-minute query that Hue often drops, so only 7 back-test dates have one: Sep 2022,
  then every six months from Sep 2023 to Mar 2026.
- Track B learns from the past, so the earliest snapshots can only be used for training. `evaluate()` uses
  `test_from=2`: the first two dates train, and the remaining 5 are tested, each with a model trained only on the
  dates before it. That's where the 5 comes from.
- Track A learns nothing from outcomes, so it can be tested on every date the long run supplies.

More full extracts for older dates (`sql/V3_RUN_ORDER.txt`, or `python main.py pull` on the jump server) would
give more test dates.

## 5. What changed in this cleanup (and what did not)

Scores, bands, reasons, flags and every back-test number are unchanged. This was checked by scoring four made-up
snapshots before and after the change and comparing every output table exactly (Track A scores, reasons and
parameters, the Track A back-test, Track B scores and flags, the Track B back-test, `compare_without`). The
settings fingerprint is unchanged (`4c0b660488`), and all 57 tests pass.

- `core.py`: the docstring lists the five steps in run order. `score_snapshot()` marks each step. The weights
  comment works out L × I and the 32.9. `layer2_scorecard()` has a worked example. `layer3_pattern()` returns its
  evidence instead of storing it on the function (`layer3_pattern.evidence`).
- `discovery.py`: reordered to follow a run (settings, features, percentiles, model, production, back-test). The
  hidden global `SEGMENT` switch is gone: the segment is passed as an argument. `DROPPED` is no longer
  overwritten by `compare_without()`; `evaluate()` takes `dropped=` instead. `evaluate()` returns the learned
  weights instead of storing them on the function. The repeated "which columns" code is one function,
  `model_columns()`. The two model rules are stated in the docstring.
- New: `notebooks/walkthrough_demo.py` (step-by-step printout) and this guide.
- Callers updated: `main.py` (discovery command), `tests/test_trackb.py`, `notebooks/build_notebook.py`.
