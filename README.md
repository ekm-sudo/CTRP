# Customs Taxpayer Risk Profiling Model (CTRP)

Release 1, model version `1.0.0-dev4`. Data Science Section, ITID, Uganda Revenue Authority.

## What it does

Scores every IM4 and IM7 importer on their last 24 months of declarations, highest risk first. Each taxpayer
gets a score (0 to 100), a band (VERY LOW to VERY HIGH), up to three reasons in fixed wording, and notes on how
much weight the score can bear. The output is an Excel workbook with a fixed layout.

## Start here

1. `docs/CTRP_Model_Guide.docx`: plain-language guide. What the model does, how every step works, how to run
   it, how to change it, and how to answer the questions people will ask.
2. `docs/CTRP_Decision_Record.docx`: the formal record of every decision and its evidence.
3. `notebooks/CTRP_release1.ipynb`: the analysis with charts. Each code cell starts with What / Why.
4. `src/ctrp/core.py`: the model. Read SETTINGS first, then `score_snapshot()`.
5. `docs/DECISIONS.md`: the running decision log.

## Set up (once)

Git Bash, in the project folder:

```bash
cd ~/Desktop/OCTOBER/ctrp
python -m pip install -r requirements.txt     # the libraries; the ctrp package is found in src/ automatically
python main.py test                           # all tests should pass
```

## Run

| Command | What it does | Output |
|---|---|---|
| `python main.py sql` | Writes one Hue query per snapshot | `sql/bt_<date>.sql`, `sql/live_<date>.sql` |
| `python main.py sql --split <date> ...` | Cuts a snapshot's query into three smaller ones, for when the full one will not finish | `sql/split/core_...`, `own_duty_...`, `split_new_...` |
| `python main.py merge` | Glues the three saved parts back into one extract (an older file of that name goes to `data/old/`) | `data/<name>.csv` |
| `python main.py check "data/*.csv"` | Tests every download from Hue | PASS / CHECK report |
| `python main.py score data/live_2026-09-30.csv` | Scores one extract | `results/CTRP_scores_<date>.xlsx` |
| `python main.py backtest` | Back-tests every `data/bt_*.csv` | `results/CTRP_backtest.xlsx` |
| `python main.py challengers` | Compares challengers and ensembles (about 10 min) | `results/CTRP_challengers.xlsx` |
| `python main.py notebook` | Rebuilds and runs the notebook (about 15 min) | notebook with outputs, `results/charts/*.png` |
| `python main.py docs` | Rebuilds the two Word documents (after the notebook) | `docs/*.docx` |
| `python main.py test` | Runs the automatic tests | pass / fail |

After running a query in Hue, download the result as CSV and save it in `data/` with the same name as the
query (for example `data/bt_2026-03-31.csv`).

## Project layout

```text
ctrp/
├── .gitignore
├── LICENSE
├── README.md
├── pyproject.toml            # project metadata and build configuration
├── requirements.txt          # the environment (includes the package itself)
├── main.py                   # entry point: python main.py <command>
├── src/
│   └── ctrp/                 # the importable package
│       ├── __init__.py       # public API: score_snapshot, load_extract, backtest
│       ├── core.py           # THE MODEL: settings, four layers, reasons, back-test
│       ├── utils.py          # paths, reading an extract, lift and other measures
│       ├── report.py         # the officers' Excel workbook
│       ├── extract.py        # Hue queries and the checks on each download
│       ├── pipeline.py       # score one file, back-test many
│       ├── sql/
│       │   └── features_outcomes.sql   # the feature and outcome query (date placeholders)
│       └── models/
│           ├── __init__.py
│           └── challengers.py          # challengers and ensembles, compared fairly
├── tests/                    # automatic tests (made-up data, never real TINs)
├── notebooks/                # the analysis notebook and the script that builds it
├── docs/                     # decision log, Word documents, research report, document builders
├── sql/                      # generated queries (sql/) and Stage 1 analysis queries (sql/analysis/)
├── data/                     # CSVs from Hue (never committed)
├── results/                  # workbooks and charts (never committed)
└── archive/                  # superseded scripts kept for reference
```

## Rules for changing the model

1. Change settings only in the SETTINGS block of `src/ctrp/core.py`.
2. Raise `MODEL_VERSION` whenever a change can move a score.
3. Run `python main.py test` and `python main.py backtest`; compare lift, hits caught, revenue caught and the
   share of small traders with the previous version, in every snapshot.
4. Record the decision with its evidence in `docs/DECISIONS.md`, then `python main.py docs`.
5. Never commit `data/` or `results/`: they contain TINs.
