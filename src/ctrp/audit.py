"""
Missed-revenue lists for the National Targeting Centre (NTC): declarations priced far below other importers
that were NOT topped up, with the top-up we estimate each should have raised, grouped by taxpayer.

What: reads the Hue results of sql/audit/audit_02_below_peers_since_july.sql and audit_03_totals_since_july.sql,
      the CET 2022 (June 2025) table, and the live scores workbook, and writes one Excel workbook.
Why:  a list NTC can check entry by entry. Their findings tell us how much of the estimate is real, which is
      a better test of the model than top-ups alone.

    python main.py audit            -> results/CTRP_missed_revenue_since_july_2026.xlsx

The estimate, per declaration:
    shortfall   = how much more the items priced under half the peer price would be worth at the peer middle price
                  (from the query; the smaller of the per-kg and per-unit figures)
    tax rate    = the items' own tax as a share of their value (tax_assessed / customs_value), capped at 100%
    estimate    = shortfall x tax rate
Items priced under 10% of peers are listed separately as "possible unit errors": a weight or quantity keyed in the
wrong unit is more likely than undervaluation that large. Entries whose underpriced items carry no tax at all (an
exemption APC, or a zero rate) are also listed separately as "exempt or zero-rated": at the peer price they would
still pay no tax, so they add nothing to the estimate; what NTC can check there is whether the exemption was valid.
All figures are estimates to be checked, not findings.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

from ctrp.utils import DATA_DIR, RESULTS_DIR

PERCENT_COLUMNS = {'Lowest item price as % of the peer price', 'Tax rate on the underpriced items (max 100%)'}
RATE_CAP = 1.0          # an items' tax can exceed its value only for a few excise goods; cap to avoid outliers
UNIT_CHECK = 0.10       # under 10% of the peer price: treat as a possible unit or keying error first


def load(audit_dir=None, cet_file=None, scores_file=None):
    """The two Hue downloads, the CET table, and each taxpayer's band from the live scores (if scored)."""
    a = Path(audit_dir or DATA_DIR / 'audit')
    d = pd.read_csv(a / 'below_peers_since_july.csv', dtype={'taxpayer_tin': str, 'instance_id': str,
                                                             'example_hs_code': str, 'entry_num': str,
                                                             'apcs_on_underpriced_items': str})
    totals = pd.read_csv(a / 'totals_since_july.csv')
    cet = pd.read_csv(cet_file or DATA_DIR / 'reference' / 'cet_2022_june2025.csv', dtype={'hs8': str})
    sf = Path(scores_file or RESULTS_DIR / 'CTRP_scores_2026-09-30.xlsx')
    bands = (pd.read_excel(sf, sheet_name='Scores', dtype={'TIN': str})
             .set_index('TIN')['History Risk Band'] if sf.exists() else pd.Series(dtype=str))
    return d, totals, cet, bands


def prepare(d, cet, bands):
    """Add the estimate, the unit-error and no-tax markers, the CET description and the band to each entry."""
    d = d.copy()
    d['rate'] = (d['tax_at_stake'] / d['shortfall_value'].replace(0, np.nan)).fillna(0)
    d['estimate'] = d['shortfall_value'] * d['rate'].clip(upper=RATE_CAP)
    d['unit_check'] = d['lowest_price_vs_peers'] < UNIT_CHECK
    # no tax on the underpriced items: exempt (APC) or zero-rated. Uses the item tax when the query supplies it
    # (audit_02 after 16 Oct 2026), otherwise tax at stake = 0, which is the same thing for these rows.
    item_tax = d['tax_on_underpriced_items'] if 'tax_on_underpriced_items' in d else d['tax_at_stake']
    d['no_tax'] = item_tax.fillna(0) <= 0
    if 'apcs_on_underpriced_items' not in d:
        d['apcs_on_underpriced_items'] = np.nan
    d['hs8'] = d['example_hs_code'].str[:8]
    c = cet.drop_duplicates('hs8').set_index('hs8')
    d['cet_description'] = d['hs8'].map(c['description'])
    d['cet_duty'] = d['hs8'].map(c['rate'])
    d['cet_unit'] = d['hs8'].map(c['unit'])
    d['hs_in_cet'] = np.where(d['hs8'].isin(c.index), 'Y', 'N')
    d['band'] = d['taxpayer_tin'].map(bands).fillna('Not on the live list')
    d['chapter'] = d['example_hs_code'].str[:2]
    return d


def _flags(r):
    """The warnings shown in the "Flags" column of one entry."""
    f = []
    if r['unit_check']:
        f.append('Possible unit error: price under 10% of peers')
    if r['hs_in_cet'] == 'N':
        f.append('HS code not in CET 2022 (June 2025)')
    return '; '.join(f)


# Entry columns: our name -> the label in the workbook, in the order shown
ENTRY_COLUMNS = {
    'taxpayer_tin': 'TIN', 'band': 'History Risk Band', 'station': 'Station', 'entry_year': 'Year',
    'entry_num': 'Entry number', 'instance_id': 'instance_id', 'assessed_on': 'Assessed on',
    'Checked': 'Checked (red or yellow)',
    'example_hs_code': 'HS code of an underpriced item',
    'apcs_on_underpriced_items': 'APC(s) on the underpriced items',
    'cet_description': 'CET description', 'cet_duty': 'CET duty rate', 'cet_unit': 'CET unit',
    'items_on_declaration': 'Items on declaration', 'items_below_peers': 'Underpriced items',
    'declaration_value': 'Customs value of the declaration, UGX',
    'value_of_items_below_peers': 'Declared value of underpriced items, UGX',
    'lowest_price_vs_peers': 'Lowest item price as % of the peer price',
    'fewest_importers_in_benchmark': 'Other importers in the price comparison',
    'shortfall_value': 'Potential undervaluation, UGX',
    'rate': 'Tax rate on the underpriced items (max 100%)',
    'estimate': 'Estimated missed top-up, UGX',
    'Flags': 'Flags',
}
BAND_ORDER = ['VERY HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY LOW', 'Not on the live list']
ESTIMATE = 'Estimated missed top-up, UGX'


def _entries(x):
    """One row per declaration, largest estimate first, with workbook labels."""
    e = x.sort_values('estimate', ascending=False).copy()
    e['rate'] = e['rate'].clip(upper=RATE_CAP)
    e['Flags'] = e.apply(_flags, axis=1)
    e['Checked'] = np.where(e['checked'] == 'Y', 'Yes, released without top-up', 'No')
    return e[list(ENTRY_COLUMNS)].rename(columns=ENTRY_COLUMNS)


def _count_per_taxpayer(rows, index):
    """How many of `rows` each taxpayer in `index` has (0 when none)."""
    return rows.groupby('taxpayer_tin').size().reindex(index).fillna(0).astype(int)


def _by_taxpayer(d, main, units, exempt):
    """One row per taxpayer on the main list, ranked by estimated missed top-up."""
    g = main.groupby('taxpayer_tin')
    tp = pd.DataFrame({
        'History Risk Band (30 Sep 2026)': g['band'].first(),
        'Underpriced declarations not topped up': g.size(),
        'Checked and released': g['checked'].apply(lambda s: int((s == 'Y').sum())),
        'Not checked': g['checked'].apply(lambda s: int((s == 'N').sum())),
        'Total customs value of these declarations, UGX': g['declaration_value'].sum(),
        'Declared value of underpriced items, UGX': g['value_of_items_below_peers'].sum(),
        'Potential undervaluation, UGX': g['shortfall_value'].sum(),
        ESTIMATE: g['estimate'].sum(),
        'Largest estimated missed top-up on one entry, UGX': g['estimate'].max(),
        'Stations': g['station'].apply(lambda s: ', '.join(s.value_counts().index[:3])),
    })
    tp['Entries with possible unit errors (separate sheet)'] = _count_per_taxpayer(units, tp.index)
    tp['Underpriced entries with no tax: exempt or zero-rated (separate sheet)'] = _count_per_taxpayer(exempt, tp.index)
    raised = d[d['topped_up'] == 'Y'].groupby('taxpayer_tin')['top_up_amount'].sum()
    tp['Top-ups already raised on underpriced entries since July, UGX'] = raised.reindex(tp.index).fillna(0)
    # the goods on each taxpayer's entry with the largest estimate
    top_hs = (main.sort_values('estimate', ascending=False)
              .drop_duplicates('taxpayer_tin').set_index('taxpayer_tin'))
    goods = top_hs['example_hs_code'] + ' ' + top_hs['cet_description'].fillna('')
    tp['Goods on the entry with the largest estimate (HS code, CET description)'] = goods.reindex(tp.index)
    tp = (tp.sort_values(ESTIMATE, ascending=False).reset_index()
          .rename(columns={'taxpayer_tin': 'TIN'}))
    tp.insert(0, 'Rank', range(1, len(tp) + 1))
    return tp


def _summary(totals, nt, main, units, exempt, ratio):
    """The headline figures: all declarations, the main list, and the separate lists."""
    tot = totals.set_index('checked')
    checked = main['checked'] == 'Y'
    not_checked = main['checked'] == 'N'
    s = [('Period', f"{int(totals['first_day'].min())} to {int(totals['last_day'].max())} (IM4 and IM7)"),
         ('All declarations', int(tot['declarations'].sum())),
         ('Of which checked (red or yellow)', int(tot.loc['Y', 'declarations'])),
         ('Final tax on all declarations, UGX', tot['final_tax'].sum()),
         ('Top-ups raised on all declarations, UGX', tot['top_up_amount'].sum()),
         ('', ''),
         ('Underpriced declarations not topped up (items under half the peer price)', len(main)),
         ('  of which checked and released', int(checked.sum())),
         ('  of which not checked', int(not_checked.sum())),
         ('Taxpayers', main['taxpayer_tin'].nunique()),
         ('Estimated missed top-up (tax on the potential undervaluation), UGX', main['estimate'].sum()),
         ('  on checked and released declarations, UGX', main.loc[checked, 'estimate'].sum()),
         ('  on declarations not checked, UGX', main.loc[not_checked, 'estimate'].sum()),
         ('On underpriced entries officers did top up, the top-up raised as a share of our estimate', ratio),
         ('Cautious estimate of missed top-ups (estimate x that share), UGX', main['estimate'].sum() * ratio),
         ('', ''),
         ('Separate: entries priced under 10% of peers (possible unit errors)', len(units)),
         ('  their estimate if the price were real, UGX', units['estimate'].sum()),
         ('Separate: underpriced entries with no tax on those items (exempt or zero-rated)', len(exempt)),
         ('  taxpayers', exempt['taxpayer_tin'].nunique()),
         ('  their potential undervaluation (no tax at stake while the exemption holds), UGX',
          exempt['shortfall_value'].sum()),
         ('Entries whose HS code is not in CET 2022 (June 2025)', int((nt['hs_in_cet'] == 'N').sum()))]
    return pd.DataFrame(s, columns=['Measure', 'Value'])


def _breakdowns(main):
    """The main list by station, by History Risk Band and by HS chapter."""
    by_station = (main.groupby('station')
                  .agg(declarations=('instance_id', 'size'), estimate=('estimate', 'sum'))
                  .sort_values('estimate', ascending=False).head(15).reset_index()
                  .rename(columns={'station': 'Station', 'declarations': 'Declarations', 'estimate': ESTIMATE}))
    by_band = (main.groupby('band')
               .agg(taxpayers=('taxpayer_tin', 'nunique'), declarations=('instance_id', 'size'),
                    estimate=('estimate', 'sum'))
               .reset_index()
               .rename(columns={'band': 'History Risk Band', 'taxpayers': 'Taxpayers',
                                'declarations': 'Declarations', 'estimate': ESTIMATE}))
    by_band['o'] = by_band['History Risk Band'].map({b: i for i, b in enumerate(BAND_ORDER)})
    by_band = by_band.sort_values('o').drop(columns='o')

    def first_description(s):
        return s.dropna().iloc[0] if s.notna().any() else ''
    by_chapter = (main.groupby('chapter')
                  .agg(declarations=('instance_id', 'size'), estimate=('estimate', 'sum'),
                       example=('cet_description', first_description))
                  .sort_values('estimate', ascending=False).head(15).reset_index()
                  .rename(columns={'chapter': 'HS chapter', 'declarations': 'Declarations', 'estimate': ESTIMATE,
                                   'example': 'Example (CET)'}))
    return by_station, by_band, by_chapter


def _calibration(done):
    """Underpriced entries officers DID top up: our estimate beside the top-up actually raised."""
    calib = done.sort_values('top_up_amount', ascending=False)[
        ['taxpayer_tin', 'station', 'entry_year', 'entry_num', 'assessed_on', 'example_hs_code', 'estimate',
         'top_up_amount']]
    calib.columns = ['TIN', 'Station', 'Year', 'Entry number', 'Assessed on', 'HS code',
                     'Our estimated top-up, UGX', 'Top-up officers actually raised, UGX']
    return calib


def build(d, totals):
    """Split the declarations into the main list and the separate lists, and build every table."""
    nt = d[d['topped_up'] == 'N'].copy()                     # not topped up
    main = nt[~nt['unit_check'] & ~nt['no_tax']]             # the main list
    units = nt[nt['unit_check']]                             # possible unit errors
    exempt = nt[~nt['unit_check'] & nt['no_tax']]            # exempt or zero-rated
    done = d[(d['topped_up'] == 'Y') & ~d['unit_check'] & ~d['no_tax']]     # topped up: tests the estimate
    # the top-up officers raised as a share of our estimate, on the entries they did top up
    ratio = done['top_up_amount'].sum() / done['estimate'].sum() if done['estimate'].sum() else np.nan

    by_station, by_band, by_chapter = _breakdowns(main)
    return dict(summary=_summary(totals, nt, main, units, exempt, ratio), by_band=by_band,
                by_station=by_station, by_chapter=by_chapter, taxpayers=_by_taxpayer(d, main, units, exempt),
                entries=_entries(main), units=_entries(units), exempt=_entries(exempt), calib=_calibration(done),
                ratio=ratio)


COLUMN_GUIDE = [
    ('Underpriced item',
     'An item declared at under half of the middle price other importers declare for the same HS code (and origin).'),
    ('Underpriced declarations not topped up',
     'Declarations since 1 July 2026 with at least one underpriced item, where no top-up was raised.'),
    ('Checked and released', 'The declaration went to the red or yellow lane and was released without a top-up.'),
    ('Not checked', 'The declaration did not go to red or yellow.'),
    ('Total customs value of these declarations, UGX', 'Customs value of the whole declarations, all items.'),
    ('Declared value of underpriced items, UGX', 'What the taxpayer declared for the underpriced items only.'),
    ('Potential undervaluation, UGX',
     'How much more the underpriced items would be worth at the peer middle price: peer price x quantity, '
     'minus the declared value.'),
    ('Estimated missed top-up, UGX',
     'The extra tax the entry would have paid at the peer price: potential undervaluation x the items\' own tax '
     'rate. What we think the top-up should have been.'),
    ('Largest estimated missed top-up on one entry, UGX',
     'The single entry with the biggest estimate for this taxpayer: where to start checking.'),
    ('Entries with possible unit errors (separate sheet)',
     'Number of this taxpayer\'s entries with an item priced under 10% of peers. Listed on the "Possible unit '
     'errors" sheet, not in the totals.'),
    ('Underpriced entries with no tax: exempt or zero-rated (separate sheet)',
     'Number of this taxpayer\'s underpriced entries where those items paid no tax (an exemption APC or a zero '
     'rate). Listed on the "Exempt or zero-rated" sheet, not in the totals.'),
    ('APC(s) on the underpriced items',
     'The Additional Procedure Code(s) declared on the underpriced items. 000 = no exemption claimed; any other '
     'code claims an exemption or rebate.'),
    ('Top-ups already raised on underpriced entries since July, UGX',
     'Top-ups officers did raise on this taxpayer\'s underpriced entries.'),
    ('Lowest item price as % of the peer price',
     'The cheapest underpriced item on the entry, as a share of the peer middle price. 20% means one fifth of '
     'what others declare.'),
    ('Other importers in the price comparison',
     'How many different importers set the peer price. More importers, firmer benchmark.'),
    ('Tax rate on the underpriced items (max 100%)',
     'Tax assessed on the items divided by their declared value (duty, VAT and other taxes together).'),
    ('HS code of an underpriced item', 'One of the underpriced items on the entry; the CET columns describe it.'),
    ('CET description, duty rate, unit',
     'From the EAC CET 2022 (June 2025 update) for that HS code. SI = sensitive item rate.'),
    ('Flags', 'Possible unit error (price under 10% of peers) or HS code not found in CET 2022.'),
]


READ_ME = [
    'Missed revenue since 1 July 2026: declarations with items priced far below what other importers declare for '
    'the same goods, that were not topped up.',
    'Prepared by Data Science (ITID) for the National Targeting Centre to check. Every figure is an estimate to be '
    'verified, not a finding. Contains TINs: internal use only.',
    '',
    'How an entry gets on the list',
    '1. Every IM4 and IM7 item since 1 July 2026 is compared with the middle price per kg (and per unit, where a '
    'quantity is declared) of all importers of the same HS code and origin over the 24 months before July (same HS '
    'code from all origins where fewer than 5 importers bring it from that origin). An HS code needs 5 or more '
    'importers to have a benchmark.',
    '2. An item counts when its price is under half of that middle price (on both kg and unit where both exist). '
    'Fuel (chapter 27) is left out.',
    '3. The declaration is listed if it has at least one such item and was not topped up.',
    '',
    'The estimate',
    'Potential undervaluation = how much more those items would be worth at the peer middle price. Estimated '
    'missed top-up = potential undervaluation x the items\' own tax rate (tax assessed / customs value, capped at '
    '100%): the extra tax the entry would have paid at the peer price.',
    'This assumes the right value is the middle price of other importers. The customs value must follow the '
    'valuation methods in order, so the true figure for any entry may be lower or higher.',
    'The tax rate includes VAT. A VAT-registered importer may later claim import VAT back as input tax, so for them '
    'the net loss is lower than the estimate.',
    'On underpriced entries that officers did top up, the top-up raised was about {ratio:.0%} of our estimate '
    '(sheet "Test of the estimate"). The Summary shows both the estimate and that more cautious figure.',
    '',
    'Sheets',
    'Summary: totals, by band, by station, by HS chapter.',
    'By taxpayer: one row per taxpayer, ranked by estimated missed top-up.',
    'Entries: every listed declaration with its entry number, the CET description, and flags.',
    'Possible unit errors: entries with an item priced under 10% of peers. A weight or quantity keyed in the wrong '
    'unit is the likely cause; confirm the units before treating them as undervaluation.',
    'Exempt or zero-rated: underpriced entries where those items paid no tax at all (an exemption APC or a zero '
    'rate). At the peer price they would still pay no tax, so they are not in the estimate. Check whether the '
    'exemption was valid: if it was not, the tax lost is the full tax on the full value, more than any figure here.',
    'Test of the estimate: underpriced entries that officers DID top up, with our estimated top-up beside the '
    'top-up actually raised. It shows how close our estimate comes to what officers raise (about {ratio:.0%} '
    'overall), which gives the cautious figure in the Summary.',
    'Column guide: what every column means.',
    '',
    'Checked and released: many listed entries went to red or yellow and were released without a top-up. These '
    'deserve particular attention.',
    'HS codes are checked against the EAC CET 2022 (June 2025 update). A code not found may be outdated (for '
    'example 0805.20, split in 2022) or keyed wrongly.',
]

SUMMARY_TITLES = ('Summary', 'By History Risk Band', 'Top stations', 'Top HS chapters')
HEADER_FILL = PatternFill('solid', start_color='102A83')


def _style_header(cell):
    cell.font = Font(bold=True, color='FFFFFF')
    cell.fill = HEADER_FILL


def _format_sheet(ws):
    """White-on-blue header, column widths from the content, money and percent formats."""
    for c in ws[1]:
        _style_header(c)
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for col in ws.columns:
        letter = col[0].column_letter
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
        ws.column_dimensions[letter].width = min(max(10, width + 2), 60 if ws.title != 'Read me' else 160)
        hdr = str(col[0].value or '')
        for c in col[1:]:
            if isinstance(c.value, (int, float)):
                if 'UGX' in hdr:
                    c.number_format = '#,##0'
                elif hdr in PERCENT_COLUMNS:
                    c.number_format = '0%'
    ws.freeze_panes = 'A2' if ws.title not in ('Read me', 'Summary') else None


def _format_summary(ws):
    """The Summary sheet stacks four tables: amounts get thousands, shares get percent, titles get the header style."""
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, float) and c.value > 1000:
                c.number_format = '#,##0'
            elif isinstance(c.value, float) and c.value < 1:
                c.number_format = '0%'
            if isinstance(c.value, str) and c.value in SUMMARY_TITLES:
                _style_header(c)


def write(res, out):
    """Write the workbook: Read me, Summary (four tables stacked), the lists, and the column guide."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        read_me = [line.format(ratio=res['ratio']) for line in READ_ME]
        pd.DataFrame({'Read me': read_me}).to_excel(w, sheet_name='Read me', index=False)
        r = 0
        for title, df in zip(SUMMARY_TITLES, [res['summary'], res['by_band'], res['by_station'], res['by_chapter']]):
            pd.DataFrame({title: []}).to_excel(w, sheet_name='Summary', startrow=r, index=False)
            df.to_excel(w, sheet_name='Summary', startrow=r + 1, index=False)
            r += len(df) + 4
        res['taxpayers'].to_excel(w, sheet_name='By taxpayer', index=False)
        res['entries'].to_excel(w, sheet_name='Entries', index=False)
        res['units'].to_excel(w, sheet_name='Possible unit errors', index=False)
        res['exempt'].to_excel(w, sheet_name='Exempt or zero-rated', index=False)
        res['calib'].to_excel(w, sheet_name='Test of the estimate', index=False)
        guide = pd.DataFrame(COLUMN_GUIDE, columns=['Column', 'What it means'])
        guide.to_excel(w, sheet_name='Column guide', index=False)
        for ws in w.book.worksheets:
            _format_sheet(ws)
        _format_summary(w.book['Summary'])
    return out


def run(out=None):
    """Load the downloads, build every table and write the workbook."""
    d, totals, cet, bands = load()
    res = build(prepare(d, cet, bands), totals)
    return write(res, out or RESULTS_DIR / 'CTRP_missed_revenue_since_july_2026.xlsx'), res
