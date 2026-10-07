Customs Taxpayer Risk Profiling Model (CTRP), release 1

WHAT IT DOES
  Scores every IM4 and IM7 taxpayer on their last 24 months of declarations, highest risk first,
  with a band (VERY LOW to VERY HIGH) and the reasons for each score, in a fixed Excel layout.

START HERE
  1  README.txt            this file
  2  CTRP_release1.ipynb   the story of the model with charts: data, checks, features, peer groups,
                           pattern check, scores and back-test. Each code cell starts with What / Why.
  3  ctrp_model.py         the model. Read SETTINGS first, then score_snapshot() near the bottom.
  4  DECISIONS.md          every decision and the evidence behind it

FILES
  ctrp_model.py        the model: settings, the four layers, reasons, back-test. Used by everything.
  ctrp_report.py       writes the officers' Excel workbook (fixed layout)
  run_scoring.py       scores from the command line, the way production will
  templates\features_outcomes.sql   the feature + outcome query with date placeholders
  make_sql.py          writes one ready-to-run query per snapshot into sql\
  sql\                 the generated queries (run in Hue, one at a time)
  data\                the CSVs downloaded from Hue (not for sharing: contains TINs)
  results\             the scored workbooks (not for sharing: contains TINs)
  check_extract.py     checks each CSV before it is used
  00_eda_cleaning.sql, 03_high_volume_individuals.sql   Stage 1 checks and the Risk team analysis
  look_top_up_ratio.py Stage 2 follow-up on extreme top-up ratios

STEPS (Git Bash or PowerShell, in this folder)
  1  python -m pip install -r requirements.txt
  2  python make_sql.py                    (only when the snapshot dates change)
  3  Run each sql\*.sql in Hue, download as CSV into data\ with the same name
  4  python check_extract.py "data/*.csv"
  5  Notebook: open CTRP_release1.ipynb in VS Code, pick the Python kernel, Run All (about 5 minutes)
     Or command line:
       python run_scoring.py data/live_2026-09-30.csv          -> results/CTRP_scores_2026-09-30.xlsx
       python run_scoring.py --backtest "data/bt_*.csv"        -> results/CTRP_backtest.xlsx

BEFORE PUTTING THIS ON GITHUB
  Leave out data\, results\ and .env (they hold TINs or connection details). Add them to .gitignore.

Superseded (kept for reference only, not used): score_v2.py, ctrp_db.py (direct connection, parked)
