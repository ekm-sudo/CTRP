"""
Write a scored snapshot to the officers' Excel workbook.

What: one workbook per run, always the same sheets, columns and wording.
Why:  officers learn to read it once, and any run can be compared with any other.

Sheets
  Read me          what the file is and how to read a score
  Scores           one row per taxpayer, highest risk first: score, band, top 3 reasons, notes
  Reasons          every reason for every taxpayer, one per row (for filtering and audit)
  Parameter values the raw value and points of every parameter, per taxpayer
  Band summary     how many taxpayers fall in each band, and what they declare
  Reason codes     every code that can appear, with its fixed wording
  Run info         model version, settings fingerprint, snapshot, run time, settings used
"""
from datetime import datetime

import numpy as np
import pandas as pd

from ctrp import core as M

FONT = 'Bookman Old Style'
# One hue, light to dark, so the band order reads without a legend (white text on the darker two)
BAND_FILL = {'VERY LOW': ('#CDE2FB', '#0B0B0B'), 'LOW': ('#9EC5F4', '#0B0B0B'), 'MEDIUM': ('#5598E7', '#0B0B0B'),
             'HIGH': ('#1C5CAB', '#FFFFFF'), 'VERY HIGH': ('#0D366B', '#FFFFFF')}
BAND_MEANING = {'VERY LOW': 'No routine attention.', 'LOW': 'No routine attention; visible in monitoring.',
                'MEDIUM': 'Reviewed where capacity allows.', 'HIGH': 'Prioritised for review.',
                'VERY HIGH': 'Prioritised for review and escalation.'}
NUM = {'int': '#,##0', 'money': '#,##0', 'pts': '0.0', 'pct': '0.0%', 'val': '0.000'}

ORDER = [b for _, b in M.BANDS]
LIMITED = f'Limited history (under {M.ADEQUATE_ENTRIES} declarations)'
PCTL = 'Behaviour risk percentile (against similar importers)'

# Column names in the workbook (code name -> the name officers see)
SCORES_COLUMNS = {
    'rank': 'Rank', 'taxpayer_tin': 'TIN', 'score': 'History Risk Score', 'band': 'History Risk Band',
    'reason_1': 'Reason 1', 'reason_2': 'Reason 2', 'reason_3': 'Reason 3', 'notes': 'Notes',
    'scorecard_points': 'Scorecard points', 'flag_unusual_pattern': 'Unusual pattern',
    'params_scored': 'Parameters scored', 'declarations_24m': 'Declarations (24 months)',
    'customs_value_24m': 'Customs value UGX (24 months)', 'peer_group_name': 'Peer group',
    'flag_limited_history': LIMITED, 'flag_no_close_peers': 'No close peers',
    'flag_low_agreement': 'History and pattern disagree', 'snapshot_date': 'Snapshot'}
TRACK_B_COLUMNS = {
    'overall_band': 'Overall Risk Band', 'driven_by': 'Overall band set by',
    'discovery_percentile': PCTL, 'on_discovery_list': 'Risky Behaviour Flag',
    'discovery_reason_1': 'Behaviour reason 1', 'discovery_reason_2': 'Behaviour reason 2'}
REASONS_COLUMNS = {
    'taxpayer_tin': 'TIN', 'score': 'History Risk Score', 'band': 'History Risk Band', 'order': 'Order',
    'code': 'Code', 'label': 'Parameter', 'reason': 'Reason', 'value': 'Taxpayer value',
    'minimum_risk_level': 'Minimum risk level', 'maximum_level': 'Maximum level', 'points': 'Points'}
EVIDENCE_FORMATS = {
    'Customs value UGX': 'money', 'Declared UGX per kg': 'money', 'Peers median UGX per kg': 'money',
    'Declared price as share of peers': 'pct', 'Possible value gap UGX': 'money', 'Duty rate': 'pct',
    'Peers median duty rate': 'pct', 'Net weight kg': 'money'}
EVIDENCE_WIDTHS = [13, 8, 7, 11, 11, 13, 7, 6, 16, 15, 15, 12, 18, 9, 9, 16, 9, 9, 8, 7]


def _colour_bands(writer, ws, col, n_rows):
    """Colour every band name in column `col` with its band colour."""
    for band, (bg, fg) in BAND_FILL.items():
        ws.conditional_format(1, col, n_rows, col, {
            'type': 'cell', 'criteria': '==', 'value': f'"{band}"',
            'format': writer.book.add_format({'bg_color': bg, 'font_color': fg, 'bold': True})})


def _sheet(writer, name, df, widths, wrap=(), formats=None, band_col=None):
    """What: write one sheet with the house look (font, header colour, filters, band colours).
    Why:  formats are set per column, not per cell, so 60,000 rows write in seconds."""
    wb = writer.book
    df.to_excel(writer, sheet_name=name, index=False, startrow=1, header=False)
    ws = writer.sheets[name]
    hdr = wb.add_format({'font_name': FONT, 'font_size': 9, 'bold': True, 'bg_color': '#C1E4F5',
                         'border': 1, 'border_color': '#83CAEB', 'text_wrap': True, 'valign': 'top'})
    for j, c in enumerate(df.columns):
        ws.write(0, j, c, hdr)
    formats = formats or {}
    for j, c in enumerate(df.columns):
        props = {'font_name': FONT, 'font_size': 9, 'valign': 'top'}
        if c in wrap:
            props['text_wrap'] = True
        if c in formats:
            props['num_format'] = NUM.get(formats[c], formats[c])
        ws.set_column(j, j, widths[j] if j < len(widths) else 12, wb.add_format(props))
    ws.freeze_panes(1, 0)
    if len(df):
        ws.autofilter(0, 0, len(df), len(df.columns) - 1)
    if band_col in df.columns:
        _colour_bands(writer, ws, list(df.columns).index(band_col), len(df))
    return ws


def two_tracks(s, tb):
    """What: join Track B onto the Track A scores and set the overall band.
    Why:  the overall band is the HIGHER of the two tracks, so a clean history cannot average away
          strong evidence from behaviour. Until the Risk Officers' review confirms Track B, a
          discovery listing lifts a taxpayer to HIGH at most (DECISIONS 60 and 74)."""
    s = s.merge(tb, on='taxpayer_tin', how='left')
    rank = s['band'].map(ORDER.index)
    lift = (s['on_discovery_list'] == 'Y') & (rank < ORDER.index('HIGH'))
    s['overall_band'] = np.where(lift, 'HIGH', s['band'])
    s['driven_by'] = np.where(lift, 'Trading behaviour', 'Compliance history')
    return s


def write_workbook(result, path, source_file='', evidence=None):
    """What: write every sheet for one Result from core.score_snapshot()."""
    s = result.scores
    tb = getattr(result, 'track_b', None)
    if tb is not None:
        s = two_tracks(s, tb)
    run_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    with pd.ExcelWriter(path, engine='xlsxwriter') as w:
        # ---- Read me: what the file is and how to read a score ----
        readme = pd.DataFrame({'Item': [
            'What this is', 'Snapshot', 'Model', 'How to read a score', 'Bands', 'Reasons', 'Notes',
            'Two views of risk', 'Status of the settings', 'Sheets'], 'Detail': [
            'Customs Taxpayer Risk Profiling Model: every IM4 and IM7 taxpayer with declarations in the last 24 '
            'months, highest risk first. The top-up, severe top-up, amendment and tax-reduction rates use the last '
            '3 years, the latest year counting fully, the year before half and the one before that a quarter, so '
            'recent behaviour counts most. The declaration and value columns show the last 24 months.',
            f'{result.snapshot} (declarations up to and including this date).',
            f'Version {result.version}, settings fingerprint {result.fingerprint}. The same fingerprint '
            'means the same settings.',
            'History Risk Score 0 to 100, from the agreed risk parameters applied to the taxpayer\'s own '
            'compliance history (the scorecard). Every point is traceable to a reason on this file. How '
            'unusual the taxpayer\'s trading pattern is among their peers is shown as a note and adds no points.',
            ' | '.join(f'{name}: {lo}-{hi}' for (lo, hi, name) in _band_ranges()),
            'Reason 1 to 3 on the Scores sheet are the three largest contributors. All of them are on the '
            'Reasons sheet. The wording of each code is fixed (see Reason codes).',
            'Notes carry no points. They flag an unusual trading pattern, and tell you how much weight the '
            'score can bear (little history, no close peers, parameters missing, or the parameters and the '
            'pattern check disagreeing).',
            ('Compliance history: the History Risk Score and History Risk Band above, from the taxpayer\'s own '
             'record. Trading behaviour: prices, amendments and how and what the taxpayer trades, compared with '
             'similar importers, to find risk that has not yet shown up in their record. A taxpayer whose '
             'behaviour stands out most gets a Risky Behaviour Flag. The Overall Risk Band is the higher of the two; '
             'a Risky Behaviour Flag raises a taxpayer to HIGH at most until the flags are confirmed by review. '
             'Taxpayers with fewer than 10 declarations are also ranked on their own (Small traders sheet).')
            if tb is not None else 'The trading behaviour view was not run for this snapshot.',
            'PROVISIONAL. Thresholds and weights are working values until the Risk Officers confirm them.',
            'Scores, ' + ('Risky behaviour flags, Small traders, ' if tb is not None else '') +
            ('Entry evidence, ' if evidence is not None else '') +
            'Reasons, Parameter values, Band summary, Reason codes, Run info.']})
        _sheet(w, 'Read me', readme, [24, 120], wrap=['Detail'])

        # ---- Scores: one row per taxpayer, highest risk first ----
        sc = s.rename(columns=SCORES_COLUMNS)
        cols = ['Rank', 'TIN', 'History Risk Score', 'History Risk Band', 'Reason 1', 'Reason 2', 'Reason 3',
                'Notes', 'Scorecard points', 'Parameters scored', 'Declarations (24 months)',
                'Customs value UGX (24 months)', 'Peer group', 'Unusual pattern', LIMITED,
                'No close peers', 'History and pattern disagree', 'Snapshot']
        widths = [7, 13, 7, 11, 48, 48, 48, 40, 10, 10, 12, 18, 30, 9, 9, 9, 9, 11]
        if tb is not None:
            sc = sc.rename(columns=TRACK_B_COLUMNS)
            evidence_col, evidence_width = [], []
            if evidence is not None:
                n = evidence.groupby('TIN').size()
                sc['Entry evidence rows'] = sc['TIN'].map(n).fillna(0).astype(int)
                evidence_col, evidence_width = ['Entry evidence rows'], [10]
            # the overall band after the history band, the behaviour columns after the history reasons
            cols = (cols[:4] + ['Overall Risk Band', 'Overall band set by'] + cols[4:8]
                    + [PCTL, 'Risky Behaviour Flag', 'Behaviour reason 1', 'Behaviour reason 2']
                    + evidence_col + cols[8:])
            widths = widths[:4] + [11, 18] + widths[4:8] + [12, 10, 48, 48] + evidence_width + widths[8:]
        sc = sc[cols]
        _sheet(w, 'Scores', sc, widths,
               wrap=['Reason 1', 'Reason 2', 'Reason 3', 'Notes', 'Behaviour reason 1', 'Behaviour reason 2'],
               formats={'Customs value UGX (24 months)': 'money', 'Scorecard points': 'pts', PCTL: 'pct'},
               band_col='History Risk Band')
        if tb is not None:
            _colour_bands(w, w.sheets['Scores'], cols.index('Overall Risk Band'), len(sc))

            # ---- Risky behaviour flags: taxpayers with no top-up history whose behaviour stands out ----
            dl = sc[sc['Risky Behaviour Flag'] == 'Y'].copy()
            dl.insert(0, 'Segment', np.where(dl[LIMITED] == 'Y', 'Small trader', 'Regular'))
            dl = dl.sort_values(['Segment', PCTL], ascending=[True, False])
            dcols = (['Segment', 'TIN', PCTL, 'Behaviour reason 1', 'Behaviour reason 2'] + evidence_col
                     + ['Overall Risk Band', 'History Risk Score', 'History Risk Band', 'Declarations (24 months)',
                        'Customs value UGX (24 months)', 'Peer group', 'Snapshot'])
            dwidths = [12, 13, 12, 55, 55] + evidence_width + [11, 9, 11, 12, 18, 30, 11]
            _sheet(w, 'Risky behaviour flags', dl[dcols], dwidths,
                   wrap=['Behaviour reason 1', 'Behaviour reason 2'],
                   formats={PCTL: 'pct', 'Customs value UGX (24 months)': 'money'}, band_col='Overall Risk Band')

            # ---- Small traders: fewer than 10 declarations, ranked among themselves (DECISIONS 62) ----
            st = sc[sc[LIMITED] == 'Y'].copy()
            st['_o'] = st['Overall Risk Band'].map(ORDER.index)
            st = st.sort_values(['_o', 'History Risk Score', PCTL], ascending=False)
            st.insert(0, 'Small-trader rank', range(1, len(st) + 1))
            scols = ['Small-trader rank', 'TIN', 'Overall Risk Band', 'Overall band set by', 'History Risk Score',
                     'History Risk Band', 'Reason 1', PCTL, 'Risky Behaviour Flag', 'Behaviour reason 1',
                     'Declarations (24 months)', 'Customs value UGX (24 months)', 'Snapshot']
            _sheet(w, 'Small traders', st[scols], [9, 13, 11, 18, 9, 11, 48, 12, 10, 55, 12, 18, 11],
                   wrap=['Reason 1', 'Behaviour reason 1'],
                   formats={PCTL: 'pct', 'Customs value UGX (24 months)': 'money'}, band_col='Overall Risk Band')

        # ---- Entry evidence: the declarations behind the behaviour flags (from the review query) ----
        if evidence is not None:
            _sheet(w, 'Entry evidence', evidence, EVIDENCE_WIDTHS, formats=EVIDENCE_FORMATS)

        # ---- Reasons: every reason, one per row (for filtering and audit) ----
        rs = result.reasons.rename(columns=REASONS_COLUMNS)
        _sheet(w, 'Reasons', rs, [13, 7, 11, 7, 9, 26, 90, 12, 12, 12, 8], wrap=['Reason'],
               formats={'Taxpayer value': 'val', 'Points': 'pts'}, band_col='History Risk Band')

        # ---- Parameter values: value and points of every parameter ----
        pv = result.params.rename(columns={'taxpayer_tin': 'TIN'})
        _sheet(w, 'Parameter values', pv, [13] + [14] * (pv.shape[1] - 1),
               formats={c: 'val' for c in pv.columns if c != 'TIN'})

        # ---- Band summary: how many taxpayers per band ----
        order = ORDER
        bs = s.groupby('band').agg(Taxpayers=('taxpayer_tin', 'count'),
                                   Declarations=('declarations_24m', 'sum'),
                                   Customs_value=('customs_value_24m', 'sum'),
                                   Limited_history=('flag_limited_history', lambda x: (x == 'Y').sum()),
                                   Lowest=('score', 'min'), Highest=('score', 'max')).reindex(order).fillna(0)
        bs.insert(1, 'Share of taxpayers', bs['Taxpayers'] / bs['Taxpayers'].sum())
        bs.insert(0, 'Intended handling', [BAND_MEANING[b] for b in order])
        bs = bs.reset_index().rename(columns={'band': 'Band', 'Customs_value': 'Customs value UGX',
                                              'Limited_history': 'Of which limited history'})
        _sheet(w, 'Band summary', bs, [11, 36, 11, 11, 14, 22, 14, 9, 9],
               formats={'Share of taxpayers': 'pct', 'Customs value UGX': 'money',
                        'Declarations': 'int', 'Taxpayers': 'int'}, band_col='Band')

        # ---- Reason codes: every code that can appear, with its fixed wording ----
        rc = [dict(Code=p['code'], Type='Scored parameter', Parameter=p['label'],
                   Wording=p['reason'].replace('{v}', '[value]').replace('{z}', '[minimum risk level]')
                   .replace('{o}', '[maximum]'),
                   Minimum_risk_level=p['zero_at'], Maximum_level=p['one_at'], Likelihood=p['L'], Impact=p['I'],
                   Scored='Yes' if p['L'] > 2 else 'Context only') for p in M.PARAMS]
        rc += [dict(Code=k, Type='Note (no points)', Parameter='',
                    Wording=v.replace('{p}', '[x%]').replace('{n}', str(M.ADEQUATE_ENTRIES))
                    .replace('{k}', '[k]').replace('{t}', '[n]'),
                    Minimum_risk_level=None, Maximum_level=None, Likelihood=None, Impact=None,
                    Scored='No') for k, v in M.NOTES.items()]
        rc = pd.DataFrame(rc).rename(columns={'Minimum_risk_level': 'Minimum risk level',
                                              'Maximum_level': 'Maximum level'})
        _sheet(w, 'Reason codes', rc, [9, 16, 28, 90, 12, 12, 10, 8, 14], wrap=['Wording'])

        # ---- Run info: version and settings, so any run can be traced ----
        info = pd.DataFrame({'Item': [
            'Model version', 'Settings fingerprint', 'Snapshot', 'Run at', 'Input file', 'Taxpayers scored',
            'Taxpayers with 10+ declarations', 'Bands (score ranges)', 'Pattern note from percentile', 'Random seed',
            'Peer grouping'], 'Value': [
            result.version, result.fingerprint, result.snapshot, run_time, source_file, len(s),
            int((s['flag_limited_history'] == 'N').sum()),
            ' | '.join(f'{n} {lo}-{hi}' for lo, hi, n in _band_ranges()), M.PATTERN_NOTE_PCT, M.SEED,
            ' / '.join(result.log[1:])]})
        _sheet(w, 'Run info', info, [30, 100], wrap=['Value'])
    return path


def _band_ranges():
    """(lowest score, highest score, band name) for each band, from M.BANDS."""
    out, lo = [], 0
    for hi, name in M.BANDS:
        out.append((lo, hi, name))
        lo = hi + 1
    return out
