"""
Getting the data: write the Hue queries, then check what comes back.

What: (1) fills the date placeholders of src/ctrp/sql/features_outcomes.sql for each snapshot and
      writes one ready-to-run query per snapshot into sql/; (2) tests each downloaded CSV.
Why:  every extract must use identical SQL with only the dates changed, and a bad download (cut
      off, duplicated, wrong dates) must be caught before any modelling.

    python main.py sql                   -> sql/bt_<date>.sql and sql/live_<date>.sql
    python main.py check "data/*.csv"    -> PASS / CHECK per test, then a summary

Back-test snapshots every six months from Sep 2017 to Mar 2026 (18 dates), each with 24 months of
history for the features, counts per year over 36 months for recency weighting, and 6 months of
outcomes after it. The live snapshot has no outcome window yet. Sep 2017 is the earliest date
whose 36 months start after the start-up and suspect periods (stable data from Sep 2014).
"""
import glob
import re
from pathlib import Path

import pandas as pd

from ctrp import utils as U       # U.DATA_DIR is read when a function runs, so tests can point it elsewhere
from ctrp.utils import SQL_DIR, TEMPLATE_SQL, load_extract


def _every_six_months(first, last):
    return [d.strftime('%Y-%m-%d') for d in pd.date_range(first, last, freq='6ME')
            if d.month in (3, 9)]


BACKTEST_SNAPSHOTS = _every_six_months('2017-09-30', '2026-03-31')      # 18 dates
FIRST_SIX = BACKTEST_SNAPSHOTS[-6:]       # the six already pulled (Sep 2023 to Mar 2026)
LIVE_SNAPSHOT = '2026-09-30'
HISTORY_MONTHS = 24
YEARS_MONTHS = 36          # the y1/y2/y3 counts reach back 3 years (recency weighting)
OUTCOME_MONTHS = 6
PRIOR_MONTHS = 36          # look-back used only to tell whether a taxpayer is new

# ---- The data-scope switches (rules R13, R14, R15). apply_apc_483() applies them to the template. ----
# R13: APC 483 (destroyed or abandoned goods, dummy reconciliation entries) left out (DECISIONS 61).
#      It was kept in the version 1 and 2 extracts (DECISIONS 65). Version 3 extracts (Oct 2026 onwards)
#      are all re-pulled, so it is now left out everywhere.
EXCLUDE_APC_483 = True
APC_483_LINE = "    AND COALESCE(v.cpc_cd, '') <> '483'"     # the template line that applies R13
# R14: one declaration per entry (entry number + station + year), the latest declaration ID kept.
# Ethan's supervisor, 19 Oct 2026: some entries sit under more than one declaration ID. To be confirmed
# by the Risk Officers with the EDA issue workbook (issue E01).
LATEST_DECLARATION_PER_ENTRY = True
# R15: motor vehicles left out of CTRP (a separate MV model covers them). A declaration with any item in
# these HS headings is dropped as a whole, because tax and top-ups are recorded per declaration.
EXCLUDE_MOTOR_VEHICLES = True
# Chapter 87 headings: tractors, buses, cars, goods and special vehicles, chassis, bodies, parts, motorcycles
MOTOR_VEHICLE_HEADINGS = ['8701', '8702', '8703', '8704', '8705', '8706', '8707', '8708', '8711']


# =========================================================================================
# 1. Write the queries
# =========================================================================================
def ymd(ts):
    """Date -> 'YYYYMMDD', the format of assessment_dt_wid in the view."""
    return ts.strftime('%Y%m%d')


def render(snap, live=False):
    """What: fill the template's @@...@@ placeholders for one snapshot.
    Why:  every extract uses identical SQL; only the dates change."""
    s = pd.Timestamp(snap)
    hist_start = s - pd.offsets.MonthEnd(HISTORY_MONTHS)
    hist3_start = s - pd.offsets.MonthEnd(YEARS_MONTHS)
    prior_start = hist_start - pd.offsets.MonthEnd(PRIOR_MONTHS)
    out_end = s if live else s + pd.offsets.MonthEnd(OUTCOME_MONTHS)
    name = f"{'live' if live else 'bt'}_{snap}"
    sql = apply_apc_483(TEMPLATE_SQL.read_text())
    placeholders = {
        '@@SNAP_DATE@@': snap,
        '@@SNAP@@': ymd(s),
        '@@HIST_START@@': ymd(hist_start),
        '@@HIST3_START@@': ymd(hist3_start),
        '@@OUT_END@@': ymd(out_end),
        '@@PRIOR_START@@': ymd(prior_start),
        '@@FILE@@': name,
    }
    for key, value in placeholders.items():
        sql = sql.replace(key, value)
    return name, sql, hist_start.date(), out_end.date()


def apply_apc_483(sql):
    """Apply the data-scope switches to the template: APC 483 (R13), latest declaration per entry (R14) and
    motor vehicles (R15). The name is kept because every query builder calls it."""
    # R15: the list of headings, quoted for SQL and plain for the header comment
    sql = sql.replace('@@MV_HEADINGS@@', ', '.join(f"'{h}'" for h in MOTOR_VEHICLE_HEADINGS))
    sql = sql.replace('@@MV_HEADINGS_TEXT@@', ', '.join(MOTOR_VEHICLE_HEADINGS))

    # R14 and R15: each is one template line, ending with a marker comment; drop it when switched off
    switched_off = []
    if not LATEST_DECLARATION_PER_ENTRY:
        switched_off.append('-- R14 latest declaration ID per entry')
    if not EXCLUDE_MOTOR_VEHICLES:
        switched_off.append('-- R15 no motor vehicle declarations')
    keep = [line for line in sql.splitlines() if not any(line.rstrip().endswith(m) for m in switched_off)]
    sql = '\n'.join(keep) + '\n'
    if EXCLUDE_APC_483:
        return sql

    # R13 switched off: drop the APC 483 line and the second line of its comment
    lines = sql.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.startswith(APC_483_LINE):
            continue
        if i > 0 and lines[i - 1].startswith(APC_483_LINE):
            continue                                   # the comment's second line
        out.append(line.replace('R13 APC 483 excluded', 'R13 APC 483 KEPT for now (DECISIONS 65)'))
    return '\n'.join(out) + '\n'


def write_queries():
    """Write one query per snapshot into sql/ and print the windows."""
    SQL_DIR.mkdir(exist_ok=True)
    jobs = [(s, False) for s in BACKTEST_SNAPSHOTS] + [(LIVE_SNAPSHOT, True)]
    for snap, live in jobs:
        name, sql, h, o = render(snap, live)
        (SQL_DIR / f'{name}.sql').write_text(sql)
        print(f'sql/{name}.sql   history {h} to {snap}   outcomes to {o}')
    print(f'\nEarliest data needed: {render(BACKTEST_SNAPSHOTS[0])[2]}')
    print('Run each query in Hue, download the result as CSV and save it in data/ with the same name.')


# =========================================================================================
# 2. Check the downloads
# =========================================================================================
RATES = ['par045_amended_entry_rate', 'par066_negative_top_up_rate', 'par077_severe_top_up_rate',
         'top_up_entry_rate', 'main_station_share', 'im7_share', 'consignee_is_self_share',
         'par076_low_price_item_rate', 'ctx_implausible_price_rate', 'ctx_unpaid_rate',
         'ctx_red_lane_rate', 'ctx_yellow_lane_rate', 'ctx_preferential_use_rate', 'chapter_value_share',
         'own_price_drop_share', 'low_duty_value_share', 'same_day_split_share', 'origin_benchmark_share']


def check(path):
    """What: run the PASS/CHECK tests on one CSV and print a summary.
    Why:  a bad download (cut off, duplicated, wrong dates) must be caught before modelling."""
    d = pd.read_csv(path, dtype={'taxpayer_tin': str})
    d.columns = [c.split('.')[-1].lower() for c in d.columns]      # Hue may prefix "table."
    res = []

    def test(name, ok, detail=''):
        res.append(('PASS ' if ok else 'CHECK') + f'  {name}' + (f'   ({detail})' if detail else ''))
        return ok

    n = len(d)
    test('rows not a round cut-off', n % 1000 != 0 or n < 1000, f'{n:,} rows')
    test('one row per TIN', not d['taxpayer_tin'].duplicated().any(),
         f"{d['taxpayer_tin'].duplicated().sum()} duplicated")
    valid = d['taxpayer_tin'].str.fullmatch(r'\d{10}').fillna(False)
    test('TINs are 10 digits', valid.all(), f'{(~valid).sum()} not')
    test('one snapshot date', d['snapshot_date'].nunique() == 1,
         ', '.join(map(str, d['snapshot_date'].unique()[:3])))
    bad = {c: int(((d[c] < 0) | (d[c] > 1)).sum()) for c in RATES if c in d}
    test('rates between 0 and 1', sum(bad.values()) == 0, ', '.join(f'{k}: {v}' for k, v in bad.items() if v))
    test('every taxpayer has 1+ entries', (d['entries_24m'] >= 1).all())
    test('no negative amounts',
         not (d[['total_customs_value', 'total_top_up', 'out_top_up']] < 0).any().any())
    test('hits never exceed checks', (d['out_checked_hits'] <= d['out_checked']).all())
    if 'y1_entries' in d:
        gap = (d['y1_entries'].fillna(0) + d['y2_entries'].fillna(0) - d['entries_24m']).abs()
        test('years 1 + 2 add up to the 24 months', (gap == 0).all(), f'{(gap > 0).sum()} differ')
    test('top-up ratio not absurd (under 10x original tax)',
         (d['par048_top_up_ratio'].dropna() < 10).all(),
         f"max {d['par048_top_up_ratio'].max():.2f}")

    decl = d['entries_24m'].sum()
    topped = (d['top_up_entry_rate'] * d['entries_24m']).sum()
    out = [
        f'declarations in history:         {decl:,.0f}',
        f'  of which topped up:            {topped:,.0f}  ({topped / decl:.1%})',
        f'taxpayers with <10 declarations: {(d["limited_history"] == "Y").mean():.1%}',
        f'taxpayers with zero original tax (PAR_048 blank): {d["par048_top_up_ratio"].isna().mean():.1%}',
        f'taxpayers with a PAR_076 value:  {d["par076_shortfall_share"].notna().mean():.1%}',
        f'outcome window: {d["out_entries"].sum():,.0f} declarations, '
        f'{d["out_checked"].sum():,.0f} checked, {d["out_checked_hits"].sum():,.0f} hits'
        + (f' (hit rate {d["out_checked_hits"].sum() / d["out_checked"].sum():.2%})'
           if d['out_checked'].sum() else ''),
    ]
    miss = d.isna().mean()
    miss = miss[miss > 0].sort_values(ascending=False)

    print('=' * 80 + f'\n{path}\n' + '-' * 80)
    print('\n'.join(res))
    print('-' * 80 + '\n' + '\n'.join(out))
    if len(miss):
        print('-' * 80 + '\nblank share by column (blank is expected where noted in the query):')
        print(miss.round(4).to_string())
    file_name = path.split('\\')[-1].split('/')[-1]          # works for Windows and Linux paths
    return dict(file=file_name, rows=n, declarations=int(decl), topped_up_pct=round(topped / decl * 100, 2),
                checks_failed=sum(r.startswith('CHECK') for r in res))


def check_files(pattern):
    """Check every CSV matching `pattern`, then print one summary line per file."""
    matched = sorted(set(glob.glob(pattern)))
    # only the extracts (bt_<date>.csv, live_<date>.csv) have one row per taxpayer; other CSVs in data/ are lists
    files = [f for f in matched if Path(f).name.startswith(('bt_', 'live_'))]
    skipped = [Path(f).name for f in matched if f not in files]
    if skipped:
        print('not extracts, skipped:', ', '.join(skipped))
    if not files:
        raise SystemExit(f'No extracts matched {pattern}. Example: python main.py check "data/*.csv"')
    summary = pd.DataFrame([check(f) for f in files])
    print('=' * 80 + '\nSUMMARY\n' + summary.to_string(index=False))
    return summary


# =========================================================================================
# 3. Split queries, for a snapshot whose full query will not finish in Hue
# =========================================================================================
# What: cut the full query into four smaller ones that together give exactly the same columns:
#         core       declaration features (top-ups, amendments, stations, lanes) and the outcomes
#         items      goods, origins and main chapter, and PAR_076 prices (with the origin benchmark)
#         own_duty   own-price drop (PAR_067 stand-in), duty below HS peers, exemption APC use
#         split_new  same-day splitting and the new-trader flag
#       then glue the four CSVs back into one data/<name>.csv with the full query's columns.
# Why:  Hue drops a query that runs for about 30 minutes. The full query makes Spark rebuild the
#       cleaned item table about a dozen times; each part rebuilds it two to four times, so each
#       one finishes well inside the limit. The parts are cut by code out of the same template,
#       so the SQL cannot drift apart from the full query.
SPLIT_DIR = SQL_DIR / 'split'
PARTS = ['core', 'items', 'own_duty', 'split_new', 'years']
ALIAS_PART = {'tp': 'core', 'st': 'core', 'o': 'core', 's': 'items', 'dm': 'items', 'v': 'items',
              'ow': 'own_duty', 'du': 'own_duty', 'ap': 'own_duty', 'sp': 'split_new', 'pr': 'split_new',
              'yr': 'years'}
PART_NOTE = {'core': 'declaration features and outcomes', 'items': 'goods, origins and PAR_076 prices',
             'own_duty': 'own-price drop, duty below peers, exemption APC use',
             'split_new': 'same-day splitting and new traders',
             'years': 'counts per year over 3 years, for recency weighting'}
MAIN_PARTS = PARTS[:4]     # an extract needs these four; "years" can be added to an existing file


def _strip_comments(text):
    return re.sub(r'--[^\n]*', '', text)


def _parse_template(sql):
    """Split the full query into (header comment, {cte name: text}, select list, from/join part)."""
    head, rest = sql.split('\nWITH ', 1)
    body, final = re.split(r'\n-- -+ final row per taxpayer -+\n', rest, maxsplit=1)
    ctes, name, buf, pending = {}, None, [], []
    for line in body.splitlines():
        m = re.match(r'^(\w+)\s+AS\s+\(', line)
        if m:
            if name:
                ctes[name] = '\n'.join(buf).rstrip().rstrip(',')
            while pending and not pending[0].strip():
                pending.pop(0)
            name, buf, pending = m.group(1), pending + [line], []
        elif line.startswith('--') or not line.strip():
            pending.append(line)                    # comments belong to the next CTE
        else:
            buf += pending + [line]
            pending = []
    ctes[name] = '\n'.join(buf).rstrip().rstrip(',')
    sel, frm = final.split('\nFROM tp\n', 1)
    return head, ctes, sel, 'FROM tp\n' + frm


def _select_items(sel):
    """'SELECT a AS x, b.y, ...' -> [(alias, expression text)], splitting on top-level commas."""
    text = _strip_comments(sel).strip()[len('SELECT'):]
    items, depth, cur = [], 0, ''
    for ch in text:
        depth += (ch == '(') - (ch == ')')
        if ch == ',' and depth == 0:
            items.append(cur.strip())
            cur = ''
        else:
            cur += ch
    items.append(cur.strip())
    out = []
    for it in items:
        m = re.search(r'\bAS\s+(\w+)\s*$', it, flags=re.I)
        out.append((m.group(1) if m else it.split('.')[-1].strip(), ' '.join(it.split())))
    return out


def _with(ctes, targets):
    """The WITH block holding `targets` and every CTE they use, in template order."""
    need, todo = set(), list(targets)
    while todo:
        t = todo.pop()
        if t in need:
            continue
        need.add(t)
        code = _strip_comments(ctes[t].split('(', 1)[1])
        todo += [n for n in ctes if n != t and re.search(rf'\b{n}\b', code)]
    return 'WITH ' + ',\n\n'.join(ctes[n] for n in ctes if n in need)


FULL_COLUMNS = None   # filled on first use: the full query's column order


def full_columns():
    """The full query's column names, in order."""
    global FULL_COLUMNS
    if FULL_COLUMNS is None:
        _, _, sel, _ = _parse_template(TEMPLATE_SQL.read_text())
        FULL_COLUMNS = [a for a, _ in _select_items(sel)]
    return FULL_COLUMNS


def _part_of(expr):
    """Which part a SELECT column belongs to, from the table alias it reads (tp., v., sp. ...)."""
    found = {ALIAS_PART[a] for a in re.findall(r'\b([a-z]+)\.[a-z_]', expr) if a in ALIAS_PART}
    if len(found) > 1:
        raise ValueError(f'column reads from two parts: {expr}')
    return found.pop() if found else 'core'


def split_columns():
    """{part: [column, ...]} in the full query's order (taxpayer_tin is in every part)."""
    _, _, sel, _ = _parse_template(TEMPLATE_SQL.read_text())
    out = {p: [] for p in PARTS}
    for alias, expr in _select_items(sel):
        out[_part_of(expr)].append(alias)
    for p in PARTS[1:]:
        out[p] = ['taxpayer_tin'] + out[p]
    return out


def render_split(snap, live=False):
    """What: the part queries for one snapshot, as {part: sql}, dates already filled."""
    name, full, _, out_end = render(snap, live)
    _, ctes, sel, frm = _parse_template(full)
    items = _select_items(sel)
    # {alias: (cte name, the LEFT JOIN line)} from the full query's FROM part
    joins = {(m.group(2) or m.group(1)): (m.group(1), line) for line in frm.splitlines()
             for m in [re.match(r'LEFT JOIN (\w+)(?:\s+(?!ON\b)(\w+))?\s+ON', line)] if m}
    # The item scan starts 3 years back only for the yearly counts; the other parts need 24 months
    s3 = pd.Timestamp(snap)
    from_3_years = f"v.assessment_dt_wid >  '{ymd(s3 - pd.offsets.MonthEnd(YEARS_MONTHS))}'"
    from_24_months = f"v.assessment_dt_wid >  '{ymd(s3 - pd.offsets.MonthEnd(HISTORY_MONTHS))}'"
    out = {}
    for part in PARTS:
        cols = [e for a, e in items if _part_of(e) == part]
        aliases = [a for a, p in ALIAS_PART.items() if p == part and a in joins]
        head = (f'-- PART "{part}" of a split extract ({PART_NOTE[part]}).\n'
                f'-- Run in Hue as ONE statement, download as CSV and save it as\n'
                f'--   data/split/{part}_{name}.csv\n'
                f'-- then, when all four parts are saved:  python main.py merge\n'
                f'-- Cut by the code from the full query sql/{name}.sql: same cleaning rules,\n'
                f'-- same dates, so the merged file matches what the full query gives.\n\n')
        if part == 'core':
            w = _with(ctes, ['tp'] + [joins[a][0] for a in aliases])
            w = w.replace(from_3_years, from_24_months)
            body = ('\n\nSELECT ' + ',\n       '.join(cols) + '\nFROM tp\n'
                    + '\n'.join(joins[a][1] for a in aliases) + '\n')
        else:
            # one row per taxpayer in the history window; the item scan stops at the snapshot
            # date, because outcomes are not needed here
            w = _with(ctes, [joins[a][0] for a in aliases] + ['hist_items'])
            w = w.replace(f"v.assessment_dt_wid <= '{ymd(pd.Timestamp(out_end))}'",
                          f"v.assessment_dt_wid <= '{ymd(pd.Timestamp(snap))}'")
            if part != 'years':     # only the yearly counts need the third year of items
                w = w.replace(from_3_years, from_24_months)
            w += ',\n\nbase AS (\n  SELECT DISTINCT taxpayer_tin AS tin FROM hist_items\n)'
            body = ('\n\nSELECT ' + ',\n       '.join(['b.tin AS taxpayer_tin'] + cols) + '\nFROM base b\n'
                    + '\n'.join(f'LEFT JOIN {joins[a][0]} {a} ON {a}.tin = b.tin' for a in aliases) + '\n')
        out[part] = head + w + body
        if ';' in out[part]:
            raise ValueError(f'{part}: a semicolon would break Hue\'s statement split')
    return name, out


def write_split_queries(snaps, parts=None, folder=None, quiet=False):
    """Write sql/split/<part>_<name>.sql for each snapshot asked for (all parts, or only `parts`)."""
    folder = folder or SPLIT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for snap in snaps:
        live = snap == LIVE_SNAPSHOT
        if not live and snap not in BACKTEST_SNAPSHOTS:
            raise SystemExit(f'{snap} is not a snapshot date. Choose from {BACKTEST_SNAPSHOTS + [LIVE_SNAPSHOT]}')
        name, qs = render_split(snap, live)
        for part, sql in qs.items():
            if parts and part not in parts:
                continue
            (folder / f'{part}_{name}.sql').write_text(sql)
            written.append(f'{part}_{name}')
    if quiet:
        return written
    for w in written:
        print(f'sql/split/{w}.sql')
    print('\nRun them ONE AT A TIME in Hue. Save each result as data/split/<same name>.csv,'
          '\nthen run:  python main.py merge')
    return written


def merge_split():
    """What: glue the four parts back into data/<name>.csv, in the full query's order.
    Why:  the rest of the project then reads one file per snapshot, exactly as if the full query
          had finished. An older file of the same name is moved to data/old/, never deleted."""
    sdir = U.DATA_DIR / 'split'
    names = sorted({f.stem.split('_', 1)[1] for pat in ('core_*.csv', 'years_*.csv')
                    for f in sdir.glob(pat)}) if sdir.exists() else []
    if not names:
        raise SystemExit('Nothing to merge: save the parts as data/split/core_<name>.csv and so on.')
    for name in names:
        files = {p: sdir / f'{p}_{name}.csv' for p in PARTS}
        missing = [str(files[p].name) for p in MAIN_PARTS if not files[p].exists()]
        if missing:
            if files['years'].exists() and (U.DATA_DIR / f'{name}.csv').exists():
                add_years(name, files['years'])
            else:
                print(f'{name}: skipped, still missing {", ".join(missing)}')
            continue
        d = load_extract(files['core'])
        for p in PARTS[1:]:
            if not files[p].exists():
                print(f'{name}: no years part yet, merged without the y1/y2/y3 columns')
                continue
            part = load_extract(files[p])
            extra = set(part['taxpayer_tin']) - set(d['taxpayer_tin'])
            if extra:
                raise SystemExit(f'{name}: {len(extra)} TINs in {p} are not in core. Were both run '
                                 f'for the same snapshot?')
            d = d.merge(part, on='taxpayer_tin', how='left')
        d = d[[c for c in full_columns() if c in d]]
        target = U.DATA_DIR / f'{name}.csv'
        if target.exists():
            (U.DATA_DIR / 'old').mkdir(exist_ok=True)
            target.replace(U.DATA_DIR / 'old' / target.name)
            print(f'moved the earlier {target.name} to data/old/')
        d.to_csv(target, index=False)
        print(f'written data/{name}.csv   {len(d):,} taxpayers, {d.shape[1]} columns')


def add_years(name, years_csv):
    """What: add the y1/y2/y3 columns to an extract already in data/ (the six pulled before them).
    Why:  only the small "years" part has to be run for those dates, not all five parts again.
          The older file is moved to data/old/, never deleted."""
    target = U.DATA_DIR / f'{name}.csv'
    d, y = load_extract(target), load_extract(years_csv)
    if all(c in d for c in y.columns):
        print(f'{name}: y1/y2/y3 columns already in data/{name}.csv, nothing to do')
        return
    extra = set(y['taxpayer_tin']) - set(d['taxpayer_tin'])
    if extra:
        raise SystemExit(f'{name}: {len(extra)} TINs in the years part are not in data/{name}.csv. '
                         f'Was it run for the same snapshot?')
    d = d.drop(columns=[c for c in y.columns if c != 'taxpayer_tin' and c in d])
    d = d.merge(y, on='taxpayer_tin', how='left')
    (U.DATA_DIR / 'old').mkdir(exist_ok=True)
    target.replace(U.DATA_DIR / 'old' / target.name)
    d.to_csv(target, index=False)
    print(f'written data/{name}.csv   y1/y2/y3 columns added ({len(d):,} taxpayers); '
          f'the earlier file is in data/old/')


# =========================================================================================
# 4. The Hue plan since 2017: every query in run order, with a checklist
# =========================================================================================
# What: writes sql/hue_plan/ with numbered queries and sql/hue_plan/CHECKLIST.txt.
#   Step 1  the "years" part for the six dates already pulled (6 small queries): enough to test
#           recency weighting straight away on the data we have.
#   Step 2  one date per year going back, Sep 2022 to Sep 2017 (5 parts each): every run adds a
#           year to the validation record, newest first, so the record grows without gaps.
#   Step 3  the March dates, Mar 2023 to Mar 2018 (5 parts each): doubles the number of tests.
# Why:  Hue drops a query after about 30 minutes, so the history since 2017 has to come in
#       pieces that each finish. Numbered files mean nothing is run twice or forgotten.
PLAN_DIR = SQL_DIR / 'hue_plan'


def hue_plan():
    sept = [d for d in BACKTEST_SNAPSHOTS if d.endswith('09-30') and d not in FIRST_SIX][::-1]
    march = [d for d in BACKTEST_SNAPSHOTS if d.endswith('03-31') and d not in FIRST_SIX][::-1]
    return ([('1', d, ['years']) for d in FIRST_SIX] + [('2', d, PARTS) for d in sept]
            + [('3', d, PARTS) for d in march])


def write_hue_plan():
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    for f in PLAN_DIR.glob('*.sql'):
        f.unlink()
    lines, n = [], 0
    heads = {'1': 'STEP 1  the yearly counts for the six dates we already have (small queries)',
             '2': 'STEP 2  one date per year going back, newest first (5 parts per date)',
             '3': 'STEP 3  the March dates, newest first (5 parts per date)'}
    step = None
    for st, snap, parts in hue_plan():
        if st != step:
            lines += ['', heads[st], '-' * 78]
            step = st
        name, qs = render_split(snap)
        for part in parts:
            n += 1
            fname = f'{n:02d}_{part}_{name}.sql'
            (PLAN_DIR / fname).write_text(qs[part])
            lines.append(f'[ ] {fname:<40} save as data/split/{part}_{name}.csv')
        if st != '1':
            lines.append(f'    then: python main.py merge   (makes data/{name}.csv)')
    lines[0:0] = ['CTRP: Hue queries for the history since 2017, in run order', '=' * 78,
                  'Run ONE query at a time, as ONE statement (Ctrl+Enter). Stay on the tab until it',
                  'finishes, download the result as CSV and save it under the name shown.',
                  'Tick the box when the file is saved. A query that times out: just run it again.',
                  'After step 1: python main.py merge  (adds the yearly counts to the six files).',
                  f'{n} queries in all.']
    (PLAN_DIR / 'CHECKLIST.txt').write_text('\n'.join(lines) + '\n')
    print(f'{n} queries written to sql/hue_plan/, with sql/hue_plan/CHECKLIST.txt')
    return n
