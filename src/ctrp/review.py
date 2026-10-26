"""
The Risk Officers' review pack for Track B: who is on the discovery list, and the entries behind it.

What: takes the discovery list from a scored workbook and writes one light Hue query that pulls,
      for each listed taxpayer, the declarations priced furthest below other importers of the same
      tariff line and origin, with station, year and entry number so an officer can open them.
Why:  Track B cannot be proven with top-up outcomes (customs never caught what it finds), so the
      officers' verdict on real entries is how it is validated (DECISIONS 60). The query only
      reads the listed taxpayers and the tariff lines they used, so it stays well inside Hue's limit.

    python main.py review results/CTRP_scores_2026-09-30.xlsx     -> sql/review/review_<date>.sql
"""
import pandas as pd

from ctrp import extract as E
from ctrp.discovery import no_history
from ctrp.report import PCTL
from ctrp.utils import DATA_DIR, SQL_DIR, load_extract

TEMPLATE = E.TEMPLATE_SQL.parent / 'review_evidence.sql'
REVIEW_DIR = SQL_DIR / 'review'          # holds TINs: excluded from git (.gitignore)


def _flag_sheet(workbook):
    """The Track B sheet: 'Risky behaviour flags' (from Oct 2026); older workbooks say 'Risk behaviour flags'."""
    names = pd.ExcelFile(workbook).sheet_names
    return 'Risky behaviour flags' if 'Risky behaviour flags' in names else 'Risk behaviour flags'


def _fill_template(snap, tins, per_taxpayer):
    """The review query with the snapshot dates, the TINs and the entries per taxpayer filled in."""
    s = pd.Timestamp(snap)
    hist_start = s - pd.offsets.MonthEnd(E.HISTORY_MONTHS)
    sql = TEMPLATE.read_text()
    for k, v in {'@@SNAP_DATE@@': snap, '@@SNAP@@': E.ymd(s), '@@HIST_START@@': E.ymd(hist_start),
                 '@@PER_TAXPAYER@@': str(per_taxpayer),
                 '@@TINS@@': ', '.join(f"'{t}'" for t in tins)}.items():
        sql = sql.replace(k, v)
    return sql


def pick(workbook, regular=50, small=50):
    """The top of the discovery list in each segment (the officers' review sample)."""
    d = pd.read_excel(workbook, sheet_name=_flag_sheet(workbook), dtype={'TIN': str})
    d = d.sort_values(PCTL, ascending=False)
    return pd.concat([d[d['Segment'] == 'Regular'].head(regular), d[d['Segment'] == 'Small trader'].head(small)])


def write_review_sql(workbook, regular=50, small=50, per_taxpayer=5):
    sample = pick(workbook, regular, small)
    if sample.empty:
        raise SystemExit(f'{workbook} has no behaviour flags (the behaviour view was not run for it).')
    snap = str(sample['Snapshot'].iloc[0])[:10]
    sql = _fill_template(snap, sample['TIN'], per_taxpayer)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f'review_{snap}.sql'
    out.write_text(sql)
    sample[['Segment', 'TIN', PCTL, 'Behaviour reason 1',
            'Behaviour reason 2']].to_csv(REVIEW_DIR / f'review_{snap}_list.csv', index=False)
    print(f'{len(sample)} taxpayers ({(sample.Segment == "Regular").sum()} regular, '
          f'{(sample.Segment == "Small trader").sum()} small traders), up to {per_taxpayer} entries each')
    print(f'written {out}  and the list beside it. Run the query in Hue, download the result as CSV.')
    return out


# =========================================================================================
# The blind review: flagged taxpayers mixed with similar unflagged ones (DECISIONS 86)
# =========================================================================================
# What: N flagged taxpayers (the top of the list, split between regular and small traders) and
#       N unflagged ones picked at random from the same segments, all with no top-up history.
#       Each gets a code (R01, R02 ...) in shuffled order. Officers see only the codes, TINs and
#       entries; the key saying who was flagged stays with Data Science until the verdicts are in.
# Why:  if officers knew who was flagged, they would look harder at those and find more, and the
#       test would prove nothing. Mixed and blind, more "would act" verdicts for the flagged group
#       than for the others is evidence that Track B finds real risk. The seed is fixed, so the
#       same workbook always gives the same sample.
BLIND_SEED = 42


def pick_blind(workbook, extract_csv, n=25):
    """The blind sample: n flagged and n comparison taxpayers, shuffled, each with a code."""
    flags = pd.read_excel(workbook, sheet_name=_flag_sheet(workbook), dtype={'TIN': str})
    scores = pd.read_excel(workbook, sheet_name='Scores', dtype={'TIN': str})
    scores = scores.rename(columns={'Risk Behaviour Flag': 'Risky Behaviour Flag'})   # workbooks before Oct 2026
    raw = load_extract(extract_csv)
    clean = set(raw.loc[no_history(raw), 'taxpayer_tin'])
    small_col = 'Limited history (under 10 declarations)'
    n_reg = min(n // 2, (flags['Segment'] == 'Regular').sum())
    take = {'Regular': n_reg, 'Small trader': n - n_reg}
    flags = flags.sort_values(PCTL, ascending=False)
    pool = scores[(scores['Risky Behaviour Flag'] == 'N') & scores['TIN'].isin(clean)].copy()
    pool['Segment'] = pool[small_col].map({'Y': 'Small trader', 'N': 'Regular'})
    rows = []
    for seg, k in take.items():
        rows.append(flags[flags['Segment'] == seg].head(k).assign(Group='Flagged'))
        rows.append(pool[pool['Segment'] == seg].sample(k, random_state=BLIND_SEED).assign(Group='Comparison'))
    out = pd.concat(rows)[['TIN', 'Segment', 'Group']].sample(frac=1, random_state=BLIND_SEED)
    out.insert(0, 'Code', [f'R{i:02d}' for i in range(1, len(out) + 1)])
    return out.reset_index(drop=True)


def write_blind_review_sql(workbook, n=25, per_taxpayer=5, extract_csv=None):
    snap = str(pd.read_excel(workbook, sheet_name=_flag_sheet(workbook))['Snapshot'].iloc[0])[:10]
    extract_csv = extract_csv or next(f for f in (DATA_DIR / f'live_{snap}.csv', DATA_DIR / f'bt_{snap}.csv')
                                      if f.exists())
    sample = pick_blind(workbook, extract_csv, n)
    sql = _fill_template(snap, sample['TIN'], per_taxpayer)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f'blind_{snap}.sql'
    out.write_text(sql)
    sample.to_csv(REVIEW_DIR / f'blind_{snap}_KEY.csv', index=False)
    print(f'{len(sample)} taxpayers: {n} flagged and {n} comparison, mixed under codes R01 to R{len(sample):02d}')
    print(f'written {out}  (run it in Hue and download the CSV)')
    print(f'written {REVIEW_DIR / f"blind_{snap}_KEY.csv"}  (who was flagged: do NOT give this to the officers)')
    return out


def write_blind_pack(evidence_csv, key_csv, out_path):
    """What: the workbook the officers fill in: codes, TINs, entries, and a verdict column.
    Why:  it carries no flag, percentile or reason, so the review stays blind."""
    key = pd.read_csv(key_csv, dtype={'TIN': str})
    ev = load_evidence(evidence_csv)
    ev = key[['Code', 'TIN']].merge(ev, on='TIN', how='inner').sort_values(['Code', 'Evidence order'])
    n_ev = ev.groupby('Code').size()
    tp = key[['Code', 'TIN']].copy()
    tp['Entries to look at'] = tp['Code'].map(n_ev).fillna(0).astype(int)
    tp['Verdict (Act / Do not act / Not sure)'] = ''
    tp['What you found'] = ''
    how = pd.DataFrame({'How to review': [
        'Each code is one importer. Some were picked by the model, some were not; this pack does not say which.',
        'Look at the entries listed for each code (Entries sheet), and anything else you would normally check.',
        'An entry is listed when its declared price is below what other importers declare for the same tariff '
        'line and origin. A low price is a reason to look, not proof: the customs value follows the valuation '
        'methods in order.',
        '"Check units": the price is under 5% of peers; check the weight, quantity and value were keyed '
        'correctly first.',
        '"Strength" says how far below peers the price is; "Weak" (80-100% of peers) is hardly evidence on '
        'its own.',
        '"Same goods as": the same goods, value and weight appear on another entry listed; count the gap once.',
        'A code with no entries listed: no declaration was priced below peers. Give a verdict on what you can see.',
        'For each code, write Act, Do not act or Not sure in the Taxpayers sheet, and a short note.']})
    with pd.ExcelWriter(out_path) as w:
        how.to_excel(w, sheet_name='How to review', index=False)
        tp.to_excel(w, sheet_name='Taxpayers', index=False)
        ev.drop(columns=['TIN']).to_excel(w, sheet_name='Entries', index=False)
    no_entries = (tp['Entries to look at'] == 0).sum()
    print(f'written {out_path}: {len(tp)} codes, {len(ev)} entries ({no_entries} codes with none)')
    return out_path


# =========================================================================================
# Reading the result back: the Entry evidence sheet of the workbook
# =========================================================================================
EXCLUDED_CHAPTERS = {'27': 'fuel: priced per litre with specific duties, so a price per kg misleads'}
UNIT_CHECK_BELOW = 0.05     # under 5% of peers: often a weight or quantity keyed in the wrong unit
EVIDENCE_COLUMNS = {
    'taxpayer_tin': 'TIN', 'station': 'Station', 'entry_year': 'Year', 'entry_num': 'Entry number',
    'assessed_on': 'Assessed on', 'hsc_cd': 'HS code', 'origin': 'Origin', 'apc': 'APC',
    'customs_value': 'Customs value UGX', 'net_weight': 'Net weight kg',
    'declared_ugx_per_kg': 'Declared UGX per kg', 'peers_median_ugx_per_kg': 'Peers median UGX per kg',
    'benchmark_basis': 'Benchmark basis', 'importers_in_benchmark': 'Importers in benchmark',
    'price_vs_peers': 'Declared price as share of peers', 'value_gap_ugx': 'Possible value gap UGX',
    'supplementary_qnty': 'Quantity (units)', 'declared_ugx_per_unit': 'Declared UGX per unit',
    'peers_median_ugx_per_unit': 'Peers median UGX per unit', 'unit_vs_peers': 'Declared unit price as share of peers',
    'duty_rate': 'Duty rate', 'peers_median_duty_rate': 'Peers median duty rate',
}


def load_evidence(csv):
    """What: the review query's CSV, cleaned for officers.
    Why:  fuel (HS 27) is priced per litre with specific duties, so its price per kg against peers
          is not evidence of undervaluation; and a price under 5% of peers is more often a unit
          keyed wrongly than a real price, so it is marked for checking rather than hidden."""
    e = pd.read_csv(csv, dtype={'taxpayer_tin': str, 'hsc_cd': str, 'apc': str, 'entry_year': str})
    e = e[~e['hsc_cd'].str[:2].isin(EXCLUDED_CHAPTERS)].copy()
    for c in ('supplementary_qnty', 'declared_ugx_per_unit', 'peers_median_ugx_per_unit'):
        if c not in e:                       # older packs had no per-unit columns
            e[c] = float('nan')
    e['unit_vs_peers'] = e['declared_ugx_per_unit'] / e['peers_median_ugx_per_unit']
    # Under 5% of peers on either measure: check the weight, the quantity and the value first
    e['Check units'] = ((e['price_vs_peers'] < UNIT_CHECK_BELOW) |
                        (e['unit_vs_peers'] < UNIT_CHECK_BELOW)).map({True: 'Y', False: ''})
    e = e.sort_values(['taxpayer_tin', 'value_gap_ugx'], ascending=[True, False])
    e['Evidence order'] = e.groupby('taxpayer_tin').cumcount() + 1
    # How far below peers, in words: a price at 90% of peers is hardly evidence at all
    r = e['price_vs_peers']
    strength = ['Strong: under half of peers', 'Some: 50-80% of peers', 'Weak: 80-100% of peers']
    e['Strength'] = pd.cut(r, [-1, 0.5, 0.8, 99], labels=strength).astype(str)
    # The same goods declared twice (same HS code, value and weight, e.g. an S- and a C-series entry
    # days apart): say so, so the gap is not counted twice
    key = [e['taxpayer_tin'], e['hsc_cd'], e['customs_value'].round(-3), e['net_weight']]
    first = e.groupby(key)['entry_num'].transform('first')
    e['Same goods as'] = (first.where(first != e['entry_num'], '')
                          .map(lambda x: f'entry {x}' if x else ''))
    out = e.rename(columns=EVIDENCE_COLUMNS)
    return out[list(EVIDENCE_COLUMNS.values()) + ['Strength', 'Check units', 'Same goods as', 'Evidence order']]
