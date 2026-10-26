"""
Stage 2 check: is each extracted CSV complete and sensible before we model on it?

    python check_extract.py "data\\*.csv"

For each file it prints one block with PASS or CHECK against each test, then a one-line
summary per file at the end. Anything marked CHECK should be looked at before Stage 3.
"""
import glob
import sys

import numpy as np
import pandas as pd

RATES = ['par045_amended_entry_rate', 'par066_negative_top_up_rate', 'par077_severe_top_up_rate',
         'top_up_entry_rate', 'main_station_share', 'im7_share', 'consignee_is_self_share',
         'par076_low_price_item_rate', 'ctx_implausible_price_rate', 'ctx_unpaid_rate',
         'ctx_red_lane_rate', 'ctx_yellow_lane_rate', 'ctx_preferential_use_rate', 'chapter_value_share',
         'own_price_drop_share', 'low_duty_value_share', 'same_day_split_share', 'origin_benchmark_share']


def check(path):
    """What: run the PASS/CHECK tests on one CSV and print a summary.
    Why:  a bad download (cut off, duplicated, wrong dates) must be caught before modelling."""
    d = pd.read_csv(path, dtype={'taxpayer_tin': str})
    d.columns = [c.split('.')[-1].lower() for c in d.columns]
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


if __name__ == '__main__':
    files = sorted({f for pat in sys.argv[1:] for f in glob.glob(pat)})
    if not files:
        sys.exit('No files matched. Example: python check_extract.py "data\\*.csv"')
    summary = pd.DataFrame([check(f) for f in files])
    print('=' * 80 + '\nSUMMARY\n' + summary.to_string(index=False))
