"""
Version 3: redo the analysis with the entry key (R14), motor vehicles removed (R15) and APC 483 removed (R13).

What: three helpers for the redo.
        archive()          moves every version 2 download out of the way (data/archive_v2/) and copies the
                           version 2 results (results/archive_v2/), so old and new files never mix. Nothing is
                           deleted.
        write_run_order()  writes sql/V3_RUN_ORDER.txt: the Hue queries to run, in order, and where to save them.
        compare()          after the rebuild, puts the headline numbers of version 2 and version 3 side by side
                           (results/CTRP_v3_against_v2.xlsx), so the effect of the three rules can be seen.
Why:  every query now carries the three rules, so every download must be pulled again; the old results stay
      as the reference to compare against.

    python main.py v3 --archive       (once, before saving any new download)
    python main.py v3 --run-order     (the checklist)
    python main.py v3 --rebuild       (after the downloads: every result again, then the comparison)
"""
import shutil
from pathlib import Path

import pandas as pd

from ctrp.utils import DATA_DIR, RESULTS_DIR, SQL_DIR

ROOT = DATA_DIR.parent
ARCH_DATA = DATA_DIR / 'archive_v2'
ARCH_RES = RESULTS_DIR / 'archive_v2'
MOVE = ['bt_*.csv', 'live_*.csv', 'long_run/*.csv', 'long_run_addon/*.csv', 'audit/*.csv', 'split/*.csv',
        'evidence/*.csv', 'python_features/*.csv', 'eda_issues/*.csv']


def archive():
    """Move version 2 downloads to data/archive_v2/ and copy version 2 results to results/archive_v2/."""
    if ARCH_DATA.exists() and any(ARCH_DATA.rglob('*.csv')):
        raise SystemExit('data/archive_v2/ already holds files: the archive was made before. Nothing moved.')
    moved = 0
    for pat in MOVE:
        for f in sorted(DATA_DIR.glob(pat)):
            dst = ARCH_DATA / f.relative_to(DATA_DIR)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dst))
            moved += 1
    v2 = ROOT / 'data' / 'v2 extracts'
    if v2.exists():
        shutil.move(str(v2), str(ARCH_DATA / 'v2 extracts'))
        moved += 1
    ARCH_RES.mkdir(parents=True, exist_ok=True)
    copied = 0
    for f in sorted(RESULTS_DIR.glob('*.xlsx')) + sorted(RESULTS_DIR.glob('*.csv')):
        shutil.copy2(f, ARCH_RES / f.name)
        copied += 1
    print(f'{moved} downloads moved to data/archive_v2/, {copied} results copied to results/archive_v2/')


RUN_ORDER = """CTRP version 3: Hue queries to run, in order
==============================================================================
Every query now carries three rules: one declaration per entry (entry number + station + year, latest
declaration ID), no motor vehicle declarations (HS 8701 to 8708, 8711), no APC 483.
Before saving anything:  python main.py v3 --archive   (moves the version 2 files away, deletes nothing)
Run ONE query at a time, as ONE statement. Download as CSV, save under the name shown, tick the box.

STEP 1  the long run: 18 test dates since 2017 (headline performance, bands)       12 queries
------------------------------------------------------------------------------
{long_run}
STEP 2  the full extracts: all features, Track A and Track B, on 6 dates + live     7 queries
        (about 30 minutes each; if one times out: python main.py sql --split <date>)
------------------------------------------------------------------------------
{full}
STEP 3  the NTC missed-revenue workbook                                             2 queries
------------------------------------------------------------------------------
[ ] sql/audit/audit_02_below_peers_since_july.sql   save as data/audit/below_peers_since_july.csv
[ ] sql/audit/audit_03_totals_since_july.sql        save as data/audit/totals_since_july.csv

Then:  python main.py v3 --rebuild     (every result again, and results/CTRP_v3_against_v2.xlsx)

LATER, when needed
------------------------------------------------------------------------------
EDA issue workbooks for the officers (13):  sql/eda_issues/E01 ... E13 -> data/eda_issues/E01.csv ...
                                            then: python main.py issues
Candidate parameters, add-on (11):          sql/long_run_addon/addon_2016 ... 2026 -> data/long_run_addon/
                                            then: python main.py candidates
Python feature notebook (7):                sql/python_features/raw_items_1 ... 6, prior_tins -> data/python_features/
"""


def _checklist_line(query, save_as):
    return f'[ ] {query}'.ljust(52) + f'save as {save_as}'


def write_run_order():
    """Write sql/V3_RUN_ORDER.txt: the checklist of Hue queries for version 3."""
    lr = '\n'.join(_checklist_line(f'sql/long_run/if_too_big/long_run_{y}.sql', f'data/long_run/long_run_{y}.csv')
                   for y in range(2015, 2027))
    full = '\n'.join(_checklist_line(f'sql/{f.name}', f'data/{f.stem}.csv')
                     for f in sorted(SQL_DIR.glob('bt_*.sql')) if f.stem >= 'bt_2023-09-30')
    full += '\n' + _checklist_line('sql/live_2026-09-30.sql', 'data/live_2026-09-30.csv')
    out = SQL_DIR / 'V3_RUN_ORDER.txt'
    out.write_text(RUN_ORDER.format(long_run=lr, full=full))
    print(f'written {out}')
    return out


# =========================================================================================
# Version 2 against version 3
# =========================================================================================
BANDS = ['VERY HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY LOW']
LINE_MEASURES = ['Share of taxpayers above it', 'Precision (hits per check)', 'Recall (share of all hits)',
                 'Share of top-up money']
MISSED_REVENUE_MEASURES = ['Underpriced declarations not topped up (items under half the peer price)', 'Taxpayers',
                           'Estimated missed top-up (tax on the potential undervaluation), UGX',
                           'Cautious estimate of missed top-ups (estimate x that share), UGX']


def _headline(folder):
    """The headline numbers of one version, read from the workbooks in `folder`."""
    rows = {}
    p = folder / 'CTRP_performance_since_2017.xlsx'
    if p.exists():
        x = pd.ExcelFile(p)
        m = x.parse('Measures')
        rows['AUC per check, average of the dates'] = m['Per check: ROC AUC'].mean()
        rows['AUC per check, lowest date'] = m['Per check: ROC AUC'].min()
        rows['Hit rate per check, everyone'] = m['Per check: hit rate, everyone'].mean()
        lines = x.parse('Lines (average)').set_index('Line')
        for line in ['Top 5%', 'HIGH and above']:
            for c in LINE_MEASURES:
                rows[f'{line}: {c}'] = lines.loc[line, c]
        bands = x.parse('Hit rate by band').set_index('Band')
        for b in BANDS:
            if b in bands.index:
                rows[f'Checked taxpayers with a top-up, {b}'] = bands.loc[b].mean()
    p = folder / 'CTRP_scores_2026-09-30.xlsx'
    if p.exists():
        s = pd.read_excel(p, sheet_name='Scores')
        rows['Taxpayers scored (live, Sep 2026)'] = len(s)
        share = s['History Risk Band'].value_counts(normalize=True)
        for b in BANDS:
            rows[f'Live list: share {b}'] = share.get(b, 0.0)
    p = folder / 'CTRP_missed_revenue_since_july_2026.xlsx'
    if p.exists():
        summary = pd.read_excel(p, sheet_name='Summary', header=1).dropna(subset=['Measure'])
        s = summary.set_index('Measure')['Value']
        for k in MISSED_REVENUE_MEASURES:
            if k in s:
                rows[f'Missed revenue: {k}'] = pd.to_numeric(s[k], errors='coerce')
    return pd.Series(rows, dtype=float)


def _number_format(measure):
    """Excel format for one measure: money and counts as whole numbers, shares as percents."""
    if 'UGX' in measure or 'Taxpayers' in measure or 'declarations' in measure:
        return '#,##0'
    if ('share' in measure.lower() or 'Precision' in measure or 'Recall' in measure or 'Hit rate' in measure
            or 'with a top-up' in measure):
        return '0.0%'
    return '0.000'


def compare(out=None):
    """Write results/CTRP_v3_against_v2.xlsx: version 2 and version 3 headline numbers side by side."""
    v2, v3 = _headline(ARCH_RES), _headline(RESULTS_DIR)
    t = pd.DataFrame({'Version 2 (before)': v2, 'Version 3 (entry key, no vehicles, no APC 483)': v3})
    t['Change'] = t.iloc[:, 1] - t.iloc[:, 0]
    out = Path(out or RESULTS_DIR / 'CTRP_v3_against_v2.xlsx')
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        table = t.reset_index().rename(columns={'index': 'Measure'})
        table.to_excel(w, sheet_name='Version 2 against 3', index=False)
        ws = w.book['Version 2 against 3']
        ws.column_dimensions['A'].width = 78
        for col in 'BCD':
            ws.column_dimensions[col].width = 24
        for row in ws.iter_rows(min_row=2):
            fmt = _number_format(str(row[0].value))
            for c in row[1:]:
                c.number_format = fmt
    with pd.option_context('display.float_format', lambda v: f'{v:,.3f}', 'display.width', 220):
        print(t.to_string())
    print(f'written {out}')
    return t
