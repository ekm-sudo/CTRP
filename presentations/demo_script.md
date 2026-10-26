# CTRP live demo: script for the review with Stella

Before the meeting (in Git Bash, from the ctrp folder), run these once so every file is fresh:

    python main.py score data/live_2026-09-30.csv --evidence data/evidence/review_2026-09-30_v2.csv
    python main.py performance

Keep these files open in Excel, minimised: CTRP_scores_2026-09-30.xlsx, CTRP_performance_since_2017.xlsx, CTRP_aeo_check_2026-09-30.xlsx.

## In the meeting (about 10 minutes)

1. **Score the live list (about 2 minutes).**
   `python main.py score data/live_2026-09-30.csv --evidence data/evidence/review_2026-09-30_v2.csv`
   Point at: the band counts printed, model version 1.0.0-dev5 and the settings fingerprint. "Same fingerprint, same settings: any score can be traced."

2. **Open CTRP_scores_2026-09-30.xlsx.**
   - Read me: what every column means.
   - Scores: sort by History Risk Score; read Reason 1 for a HIGH taxpayer aloud. Show Overall Risk Band and "Overall band set by".
   - Parameter values: the raw rate behind each point.

3. **Risk behaviour flags, then Entry evidence.** Pick one flagged taxpayer; show the entry, station, year and price against peers. Say: "A low price is a reason to look, not proof."

4. **Open CTRP_performance_since_2017.xlsx.** Measures sheet: AUC per check for each of the 18 dates. Recency sheets: the weighting test.

5. **Open CTRP_aeo_check_2026-09-30.xlsx.** Bands sheet: AEO members against everyone else.

6. **Open docs/DECISIONS.md.** Scroll to any decision (for example 42, the 40% maximum) and show the evidence beside it.

## Do not run live

- `python main.py performance --long-run` (over 15 minutes).
- `python main.py long-run` (rebuilds every snapshot).
- Anything in Hue.

## If something fails

Open the workbooks you produced before the meeting; everything on the slides is already in them.
