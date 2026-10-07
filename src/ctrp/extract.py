"""
Getting the data: write the Hue queries, then check what comes back.

What: (1) fills the date placeholders of src/ctrp/sql/features_outcomes.sql for each snapshot and
      writes one ready-to-run query per snapshot into sql/; (2) tests each downloaded CSV.
Why:  every extract must use identical SQL with only the dates changed, and a bad download (cut
      off, duplicated, wrong dates) must be caught before any modelling.

    python main.py sql                   -> sql/bt_<date>.sql and sql/live_<date>.sql
    python main.py check "data/*.csv"    -> PASS / CHECK per test, then a summary

Six back-test snapshots, six months apart, each with 24 months of history before it and 6 months
of outcomes after it. The live snapshot has no outcome window yet.
"""
import glob

import pandas as pd

from ctrp.utils import SQL_DIR, TEMPLATE_SQL

BACKTEST_SNAPSHOTS = ['2023-09-30', '2024-03-31', '2024-09-30', '2025-03-31', '2025-09-30', '2026-03-31']
LIVE_SNAPSHOT = '2026-09-30'
HISTORY_MONTHS = 24
OUTCOME_MONTHS = 6
PRIOR_MONTHS = 36          # look-back used only to tell whether a taxpayer is new


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
    prior_start = hist_start - pd.offsets.MonthEnd(PRIOR_MONTHS)
    out_end = s if live else s + pd.offsets.MonthEnd(OUTCOME_MONTHS)
    name = f"{'live' if live else 'bt'}_{snap}"
    sql = TEMPLATE_SQL.read_text()
    for k, v in {'@@SNAP_DATE@@': snap, '@@SNAP@@': ymd(s), '@@HIST_START@@': ymd(hist_start),
                 '@@OUT_END@@': ymd(out_end), '@@PRIOR_START@@': ymd(prior_start), '@@FILE@@': name}.items():
        sql = sql.replace(k, v)
    return name, sql, hist_start.date(), out_end.date()


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
        + (f' (hit rate {d["out_checked_hits"].sum() / d["out_checked"].sum():.2%})' if d['out_checked'].sum() else ''),
    ]
    miss = d.isna().mean()
    miss = miss[miss > 0].sort_values(ascending=False)

    print('=' * 80 + f'\n{path}\n' + '-' * 80)
    print('\n'.join(res))
    print('-' * 80 + '\n' + '\n'.join(out))
    if len(miss):
        print('-' * 80 + '\nblank share by column (blank is expected where noted in the query):')
        print(miss.round(4).to_string())
    return dict(file=path.split('\\')[-1].split('/')[-1], rows=n, declarations=int(decl),
                topped_up_pct=round(topped / decl * 100, 2), checks_failed=sum(r.startswith('CHECK') for r in res))


def check_files(pattern):
    files = sorted(set(glob.glob(pattern)))
    if not files:
        raise SystemExit(f'No files matched {pattern}. Example: python main.py check "data/*.csv"')
    summary = pd.DataFrame([check(f) for f in files])
    print('=' * 80 + '\nSUMMARY\n' + summary.to_string(index=False))
    return summary


# =========================================================================================
# 3. Split queries, for a snapshot whose full query will not finish in Hue
# =========================================================================================
# What: cut the full query into three smaller ones that together give exactly the same columns:
#         core       the version 1 features, PAR_076 (with the origin benchmark) and the outcomes
#         own_duty   own-price drop (PAR_067 stand-in), duty below HS peers, exemption APC use
#         split_new  same-day splitting and the new-trader flag
#       then glue the three CSVs back into one data/<name>.csv with the full query's columns.
# Why:  the full query makes Spark rebuild the cleaned item table about a dozen times in one go.
#       Three smaller queries each rebuild it a few times, so each finishes where the whole
#       one stalls. The pieces are cut out of the same template, so the SQL cannot drift apart.
SPLIT_DIR = SQL_DIR / 'split'
PART_TARGETS = {
    'own_duty': ['own_tp', 'duty_tp', 'apc_tp'],
    'split_new': ['split_tp', 'prior'],
}
NEW_TRADER_SQL = "CASE WHEN pr.tin IS NULL THEN 'Y' ELSE 'N' END AS new_trader"


def _strip_comments(text):
    import re
    return re.sub(r'--[^\n]*', '', text)


def _parse_template(sql):
    """Split the full query into (header comment, {cte name: text}, select list, from/join part)."""
    import re
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
    import re
    text = _strip_comments(sel).strip()[len('SELECT'):]
    items, depth, cur = [], 0, ''
    for ch in text:
        depth += (ch == '(') - (ch == ')')
        if ch == ',' and depth == 0:
            items.append(cur.strip()); cur = ''
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
    import re
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
    global FULL_COLUMNS
    if FULL_COLUMNS is None:
        _, _, sel, _ = _parse_template(TEMPLATE_SQL.read_text())
        FULL_COLUMNS = [a for a, _ in _select_items(sel)]
    return FULL_COLUMNS


def render_split(snap, live=False):
    """What: the three part queries for one snapshot, as {part: sql}, dates already filled."""
    name, full, _, out_end = render(snap, live)
    head, ctes, sel, frm = _parse_template(full)
    items = _select_items(sel)
    part_cols = {'own_duty': ['hs_codes_compared', 'own_price_drop_share', 'low_duty_value_share',
                              'duty_gap_share', 'exemption_apc_value_share', 'watchlist_apc_value_share',
                              'watchlist_apcs_used'],
                 'split_new': ['same_day_split_share', 'same_day_split_expected', 'same_day_split_excess',
                               'max_same_day_same_hs', 'new_trader']}
    moved = {c for cols in part_cols.values() for c in cols}
    expr = dict(items)
    note = lambda part, what: (f'-- PART "{part}" of a split extract ({what}).\n'
                               f'-- Run in Hue as ONE statement, download as CSV and save it as\n'
                               f'--   data/split/{part}_{name}.csv\n'
                               f'-- then, when all three parts are saved:  python main.py merge\n'
                               f'-- Cut by the code from the full query sql/{name}.sql: same cleaning rules,\n'
                               f'-- same dates, so the merged file matches what the full query gives.\n')
    out = {}

    # core: the full query without the moved columns and their joins
    joins = [l for l in frm.splitlines()
             if not any(f' {a} ' in l for a in ('ow', 'du', 'ap', 'sp', 'pr'))]
    keep = [e for a, e in items if a not in moved]
    out['core'] = (note('core', 'version 1 features, PAR_076 and outcomes') + '\n' + _with(ctes, ['tp', 'st', 'struct', 'dom', 'v76', 'outc']) +
                   '\n\nSELECT ' + ',\n       '.join(keep) + '\n' + '\n'.join(joins) + '\n')

    # the other two: one row per taxpayer in the history window, the moved columns only.
    # Their item scan stops at the snapshot date: outcomes are not needed here.
    base = ("base AS (\n  SELECT DISTINCT taxpayer_tin AS tin FROM hist_items\n)")
    alias = {'own_tp': 'ow', 'duty_tp': 'du', 'apc_tp': 'ap', 'split_tp': 'sp', 'prior': 'pr'}
    for part, targets in PART_TARGETS.items():
        w = _with(ctes, targets + ['hist_items'])
        w = w.replace(f"v.assessment_dt_wid <= '{ymd(pd.Timestamp(out_end))}'",
                      f"v.assessment_dt_wid <= '{ymd(pd.Timestamp(snap))}'")
        cols = ['b.tin AS taxpayer_tin'] + [expr[c] if c != 'new_trader' else NEW_TRADER_SQL
                                            for c in part_cols[part]]
        js = '\n'.join(f'LEFT JOIN {t} {alias[t]} ON {alias[t]}.tin = b.tin' for t in targets)
        out[part] = (note(part, ', '.join(part_cols[part])) + w + ',\n\n' + base +
                     '\n\nSELECT ' + ',\n       '.join(cols) + '\nFROM base b\n' + js + '\n')
    for k in out:
        if ';' in _strip_comments(out[k]) or ';' in out[k]:
            raise ValueError(f'{k}: a semicolon would break Hue\'s statement split')
    return name, out


def write_split_queries(snaps):
    """Write sql/split/<part>_<name>.sql for each snapshot asked for."""
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    for snap in snaps:
        live = snap == LIVE_SNAPSHOT
        if not live and snap not in BACKTEST_SNAPSHOTS:
            raise SystemExit(f'{snap} is not a snapshot date. Choose from {BACKTEST_SNAPSHOTS + [LIVE_SNAPSHOT]}')
        name, parts = render_split(snap, live)
        for part, sql in parts.items():
            (SPLIT_DIR / f'{part}_{name}.sql').write_text(sql)
            print(f'sql/split/{part}_{name}.sql')
    print('\nRun them ONE AT A TIME in Hue. Save each result as data/split/<same name>.csv,'
          '\nthen run:  python main.py merge')


def merge_split():
    """What: glue core + own_duty + split_new back into data/<name>.csv, in the full query's order.
    Why:  the rest of the project then reads one file per snapshot, exactly as if the full query
          had finished. An older file of the same name is moved to data/old/, never deleted."""
    from ctrp.utils import DATA_DIR, load_extract
    sdir = DATA_DIR / 'split'
    names = sorted({f.stem.split('_', 1)[1] for f in sdir.glob('core_*.csv')}) if sdir.exists() else []
    if not names:
        raise SystemExit('Nothing to merge: save the parts as data/split/core_<name>.csv and so on.')
    for name in names:
        files = {p: sdir / f'{p}_{name}.csv' for p in ['core', *PART_TARGETS]}
        missing = [str(f.name) for f in files.values() if not f.exists()]
        if missing:
            print(f'{name}: skipped, still missing {", ".join(missing)}')
            continue
        d = load_extract(files['core'])
        for p in PART_TARGETS:
            part = load_extract(files[p])
            extra = set(part['taxpayer_tin']) - set(d['taxpayer_tin'])
            if extra:
                raise SystemExit(f'{name}: {len(extra)} TINs in {p} are not in core. Were both run '
                                 f'for the same snapshot?')
            d = d.merge(part, on='taxpayer_tin', how='left')
        d = d[full_columns()]
        target = DATA_DIR / f'{name}.csv'
        if target.exists():
            (DATA_DIR / 'old').mkdir(exist_ok=True)
            target.replace(DATA_DIR / 'old' / target.name)
            print(f'moved the earlier {target.name} to data/old/')
        d.to_csv(target, index=False)
        print(f'written data/{name}.csv   {len(d):,} taxpayers, {d.shape[1]} columns')
