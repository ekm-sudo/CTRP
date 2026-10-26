"""
The one long run for Hue: every taxpayer's history since Sep 2014 in ONE query, by half-year.

What: one query that reads the view once and returns one row per taxpayer per half-year
      (periods ending 31 March and 30 September, Oct 2014 to Sep 2026) with counts that can be
      added up: declarations, top-ups, severe top-ups, amendments, tax reductions, amounts, red and
      yellow checks and the hits among them, IM7 declarations, months active.
      Python then builds any snapshot from it by adding up the right half-years: the 24 months
      before the date for the features, the 3 years for the yearly counts, the 6 months after for
      the outcomes.
Why:  the full feature query for ONE date already takes about 30 minutes in Hue, so 19 dates in one
      query cannot finish. Counts per half-year are cheap (one pass, no benchmarks) and add up
      exactly, so one run covers every date since 2017, and any later date, without new queries.
Limit: what cannot be added up is not in it: price benchmarks (PAR_076), the main-station share
      (PAR_023), goods and origins used, and the main HS chapter. Snapshots built from the long run
      score on the other six parameters (92% of the weight; the model reweights the rest, as it
      already does for any parameter it cannot compute). The full extracts stay the reference.

    python main.py sql --long-run      -> sql/long_run/long_run.sql (+ yearly pieces as a fallback)
    python main.py long-run            -> data/long_run/lr_<date>.csv for every snapshot date
"""
import re

import pandas as pd

from ctrp import extract as E
from ctrp.utils import DATA_DIR, SQL_DIR, TEMPLATE_SQL

LONG_DIR = SQL_DIR / 'long_run'
FIRST_DAY_AFTER = '20140930'     # stable data from Sep 2014 (start-up and suspect periods before it)
LAST_DAY = '20260930'
E_ADEQUATE = 10           # "limited history" below this many declarations (core.ADEQUATE_ENTRIES)
HUE_ROW_CAP = 100_000     # Hue stops a download at this many rows (seen on the first long run)

PANEL = """
-- ---------- one row per taxpayer per half-year -----------------------------------------
-- What: counts that add up exactly across half-years, so any snapshot can be built later.
-- Why:  one pass over the view, no benchmarks: light enough for one Hue run.
half AS (
  SELECT d.*,
         CASE WHEN CAST(substr(d.dt, 5, 2) AS INT) BETWEEN 4 AND 9
                   THEN concat(substr(d.dt, 1, 4), '-09-30')
              WHEN CAST(substr(d.dt, 5, 2) AS INT) >= 10
                   THEN concat(CAST(CAST(substr(d.dt, 1, 4) AS INT) + 1 AS STRING), '-03-31')
              ELSE concat(substr(d.dt, 1, 4), '-03-31') END                    AS period_end,
         CASE WHEN d.topped_up = 1 AND d.top_up >= 0.30 * d.final_tax THEN 1 ELSE 0 END AS severe
  FROM decl d
)

SELECT tin                                                               AS taxpayer_tin,
       period_end,
       COUNT(*)                                                          AS entries,
       SUM(n_items)                                                      AS items,
       COUNT(DISTINCT substr(dt, 1, 6))                                  AS months_active,
       SUM(value)                                                        AS customs_value_ugx,
       SUM(orig_tax)                                                     AS original_tax_ugx,
       SUM(top_up)                                                       AS top_up_ugx,
       SUM(topped_up)                                                    AS topped_up,
       SUM(severe)                                                       AS severe,
       SUM(CASE WHEN amended = 'Y' THEN 1 ELSE 0 END)                    AS amended,
       SUM(negative_top_up)                                              AS tax_reduced,
       SUM(CASE WHEN regime = 'IM7' THEN 1 ELSE 0 END)                   AS im7_entries,
       SUM(CASE WHEN red = 1 OR yellow = 1 THEN 1 ELSE 0 END)            AS checked,
       SUM(CASE WHEN (red = 1 OR yellow = 1) AND topped_up = 1 THEN 1 ELSE 0 END) AS checked_hits,
       SUM(CASE WHEN red = 1 THEN 1 ELSE 0 END)                          AS red,
       SUM(CASE WHEN yellow = 1 THEN 1 ELSE 0 END)                       AS yellow,
       MAX(CASE WHEN topped_up = 1 THEN dt END)                          AS last_top_up_dt,
       MIN(dt)                                                           AS first_dt
FROM half
GROUP BY tin, period_end
"""


def render(first_after=FIRST_DAY_AFTER, last=LAST_DAY, label='all'):
    """The long-run query for declarations after `first_after` up to `last` (yyyymmdd)."""
    _, ctes, _, _ = E._parse_template(E.apply_apc_483(TEMPLATE_SQL.read_text()))
    w = ',\n\n'.join(ctes[n] for n in ['raw', 'items', 'decl_all', 'decl'])
    w = w.replace("'@@HIST3_START@@'", f"'{first_after}'").replace("'@@OUT_END@@'", f"'{last}'")
    if '@@' in w:
        raise ValueError('a date placeholder was left unfilled: ' + re.findall(r'@@\w+@@', w)[0])
    head = (f'-- =====================================================================================\n'
            f'-- CTRP ONE LONG RUN ({label}): every taxpayer, one row per half-year, declarations after\n'
            f'-- {first_after} up to {last}. Same cleaning rules as the snapshot queries (taken from the\n'
            f'-- same template by the code). Run as ONE statement, stay on the tab, download as CSV and\n'
            f'-- save it in data/long_run/ under the name below. GENERATED by: python main.py sql --long-run\n'
            f'--   save as: data/long_run/long_run_{label}.csv\n'
            f'-- =====================================================================================\n')
    sql = head + 'WITH ' + w + ',\n' + PANEL
    if ';' in sql:
        raise ValueError("a semicolon would break Hue's statement split")
    return sql


def write_queries():
    """One query for everything, plus one per year in case Hue cuts the download or times out."""
    LONG_DIR.mkdir(parents=True, exist_ok=True)
    (LONG_DIR / 'long_run.sql').write_text(render())
    pieces = LONG_DIR / 'if_too_big'
    pieces.mkdir(exist_ok=True)
    years = list(range(2015, 2027))
    for y in years:                      # Oct (y-1) to Sep y: whole half-years, so pieces add up exactly
        (pieces / f'long_run_{y}.sql').write_text(render(f'{y - 1}0930', f'{y}0930', str(y)))
    print('written sql/long_run/long_run.sql  (the one long run)')
    print(f'written sql/long_run/if_too_big/long_run_2015.sql ... long_run_{years[-1]}.sql (one year each)')
    halves = LONG_DIR / 'if_still_too_big'
    halves.mkdir(exist_ok=True)
    for y in years:                      # half-year pieces, for a year whose piece still hits the cap
        (halves / f'long_run_{y}a.sql').write_text(render(f'{y - 1}0930', f'{y}0331', f'{y}a'))
        (halves / f'long_run_{y}b.sql').write_text(render(f'{y}0331', f'{y}0930', f'{y}b'))
    print('written sql/long_run/if_still_too_big/ (half-year pieces, for any year that still hits the cap)')
    print('Use the pieces if the long run times out, or the download stops at a round number of rows.')


# =========================================================================================
# Building snapshots from the long run
# =========================================================================================
def load():
    """Every long-run CSV in data/long_run/, glued together (pieces or the one file)."""
    files = sorted((DATA_DIR / 'long_run').glob('long_run_*.csv'))
    if not files:
        raise SystemExit('No files in data/long_run/. Save the long-run result there first.')
    parts = []
    for f in files:
        part = pd.read_csv(f, dtype={'taxpayer_tin': str, 'period_end': str,
                                     'last_top_up_dt': str, 'first_dt': str})
        if len(part) % HUE_ROW_CAP == 0:
            raise SystemExit(f'{f.name} has exactly {len(part):,} rows: Hue cut the download, so it is '
                             f'incomplete. Use the smaller pieces in sql/long_run/if_too_big/ instead.')
        parts.append(part)
    p = pd.concat(parts)
    p.columns = [c.split('.')[-1].lower() for c in p.columns]
    dup = p.duplicated(['taxpayer_tin', 'period_end'])
    if dup.any():                              # the same half-year saved twice: keep one copy
        p = p[~dup]
    return p


# The half-year counts that make the yearly columns y1_<name>, y2_<name>, y3_<name>
YEARLY_COUNTS = ['entries', 'topped_up', 'severe', 'amended', 'tax_reduced', 'top_up_ugx', 'original_tax_ugx']
# Outcome column of the extract: the half-year count it is built from
OUTCOMES = {'out_entries': 'entries', 'out_checked': 'checked', 'out_checked_hits': 'checked_hits',
            'out_topped_up_entries': 'topped_up', 'out_top_up': 'top_up_ugx', 'out_original_tax': 'original_tax_ugx'}


def _periods(snap, back_months, forward=False):
    """Half-year end dates: the half-years in the `back_months` before `snap`, or the one after it."""
    s = pd.Timestamp(snap)
    if forward:
        return [(s + pd.offsets.MonthEnd(6)).strftime('%Y-%m-%d')]
    return [(s - pd.offsets.MonthEnd(m)).strftime('%Y-%m-%d') for m in range(0, back_months, 6)]


def snapshot(panel, snap, live=False):
    """One snapshot in the extract's column names, from the half-year counts.
    Columns the long run cannot give (benchmarks, stations, goods) are left blank."""
    s = pd.Timestamp(snap)
    h24 = panel[panel['period_end'].isin(_periods(snap, 24))]
    g = h24.groupby('taxpayer_tin')
    sm = g[['entries', 'items', 'months_active', 'customs_value_ugx', 'original_tax_ugx', 'top_up_ugx',
            'topped_up', 'severe', 'amended', 'tax_reduced', 'im7_entries', 'red', 'yellow']].sum()
    last = pd.to_datetime(g['last_top_up_dt'].max(), format='%Y%m%d', errors='coerce')
    n = sm['entries']
    d = pd.DataFrame({
        'taxpayer_tin': sm.index, 'snapshot_date': snap,
        'limited_history': (n < E_ADEQUATE).map({True: 'Y', False: 'N'}),
        'entries_24m': n, 'active_months': sm['months_active'], 'avg_items_per_entry': sm['items'] / n,
        'total_customs_value': sm['customs_value_ugx'], 'total_original_tax': sm['original_tax_ugx'],
        'total_top_up': sm['top_up_ugx'],
        'par045_amended_entry_rate': sm['amended'] / n,
        'par048_top_up_ratio': sm['top_up_ugx'] / sm['original_tax_ugx'].where(sm['original_tax_ugx'] != 0),
        'par066_negative_top_up_rate': sm['tax_reduced'] / n,
        'par077_severe_top_up_rate': sm['severe'] / n,
        'par105_days_since_last_top_up': (s - last).dt.days,
        'top_up_entry_rate': sm['topped_up'] / n,
        'im7_share': sm['im7_entries'] / n,
        'ctx_red_lane_rate': sm['red'] / n, 'ctx_yellow_lane_rate': sm['yellow'] / n,
    }).reset_index(drop=True)
    # the yearly counts (y1 = latest 12 months) for recency weighting
    for k, back in ((1, 0), (2, 12), (3, 24)):
        year_end = (s - pd.offsets.MonthEnd(back)).strftime('%Y-%m-%d') if back else snap
        y = panel[panel['period_end'].isin(_periods(year_end, 12))].groupby('taxpayer_tin')[YEARLY_COUNTS].sum()
        for c in YEARLY_COUNTS:
            d[f'y{k}_{c}'] = d['taxpayer_tin'].map(y[c]).fillna(0)
    h36 = panel[panel['period_end'].isin(_periods(snap, 36))]
    last36 = pd.to_datetime(h36.groupby('taxpayer_tin')['last_top_up_dt'].max(), format='%Y%m%d', errors='coerce')
    d['days_since_last_top_up_36m'] = d['taxpayer_tin'].map((s - last36).dt.days)
    # outcomes: the 6 months after (none for the live date)
    out = panel[panel['period_end'].isin([] if live else _periods(snap, 0, forward=True))]
    o = out.groupby('taxpayer_tin')[list(OUTCOMES.values())].sum()
    for c, src in OUTCOMES.items():
        d[c] = d['taxpayer_tin'].map(o[src]).fillna(0)
    for c in E.full_columns():                 # what the long run cannot give stays blank
        if c not in d:
            d[c] = float('nan')
    return d[[c for c in E.full_columns() if c in d]]


def write_snapshots():
    """data/long_run/lr_<date>.csv for every back-test date the long run covers, and the live date."""
    panel = load()
    have = set(panel['period_end'])
    done = []
    for snap in E.BACKTEST_SNAPSHOTS + [E.LIVE_SNAPSHOT]:
        live = snap == E.LIVE_SNAPSHOT
        need = set(_periods(snap, 24)) | (set() if live else set(_periods(snap, 0, forward=True)))
        if not need <= have:
            print(f'{snap}: skipped, the long run does not cover {", ".join(sorted(need - have))}')
            continue
        d = snapshot(panel, snap, live)
        name = f"lr_{'live_' if live else ''}{snap}"
        d.to_csv(DATA_DIR / 'long_run' / f'{name}.csv', index=False)
        done.append(name)
        print(f'written data/long_run/{name}.csv   {len(d):,} taxpayers')
    return done


def add_years_to_extracts():
    """What: copy the yearly counts (y1_/y2_/y3_) from the long-run snapshots into the full extracts
          in data/ (bt_<date>.csv and live_<date>.csv) that lack them.
    Why:  the model weights recent years (core.RECENCY_WEIGHTS) and needs these counts; the long run
          already has them for every date, so no extra Hue queries are needed. The older file is
          moved to data/old/, never deleted."""
    ycols = [c for c in E.full_columns() if re.match(r'y[123]_', c)] + ['days_since_last_top_up_36m']
    done = []
    for f in sorted(DATA_DIR.glob('bt_*.csv')) + sorted(DATA_DIR.glob('live_*.csv')):
        lr = DATA_DIR / 'long_run' / ('lr_' + f.stem.replace('bt_', '') + '.csv')     # lr_<date> or lr_live_<date>
        if not lr.exists():
            continue
        d = pd.read_csv(f, dtype={'taxpayer_tin': str})
        if all(c in d for c in ycols):
            continue
        y = pd.read_csv(lr, dtype={'taxpayer_tin': str}, usecols=['taxpayer_tin'] + ycols)
        d = d.drop(columns=[c for c in ycols if c in d]).merge(y, on='taxpayer_tin', how='left')
        (DATA_DIR / 'old').mkdir(exist_ok=True)
        f.replace(DATA_DIR / 'old' / f.name)
        d.to_csv(f, index=False)
        done.append(f.name)
        found = d['y1_entries'].notna().mean()
        print(f'{f.name}: yearly counts added from {lr.name} ({found:.1%} of taxpayers found)')
    return done

