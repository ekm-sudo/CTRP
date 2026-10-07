"""
Stage 2 follow-up: who has a top-up ratio far above 1, and why?

    python look_top_up_ratio.py

PAR_048 = total top-ups / total original tax over 24 months. A ratio of 4,399 means the
top-ups were 4,399 times the tax first declared. That happens when the original tax is
tiny, so this prints, for the two snapshots with the largest values, how many taxpayers
are affected and the ten most extreme, with the amounts behind the ratio.
"""
import pandas as pd

for f in ['data/bt_2025-09-30.csv', 'data/bt_2026-03-31.csv']:
    d = pd.read_csv(f, dtype={'taxpayer_tin': str})
    r = d['par048_top_up_ratio']
    print('=' * 100 + f'\n{f}')
    print(f'taxpayers with a ratio:            {r.notna().sum():,}')
    print(f'  ratio above 0.33 (officer max):  {(r > 0.33).sum():,}')
    print(f'  ratio above 1 (top-ups > tax):   {(r > 1).sum():,}')
    print(f'  ratio above 10:                  {(r > 10).sum():,}')
    print('percentiles: ' + ', '.join(f'p{int(q * 1000) / 10:g}={r.quantile(q):.3f}'
                                      for q in [0.5, 0.9, 0.99, 0.999]))
    cols = ['taxpayer_tin', 'entries_24m', 'total_original_tax', 'total_top_up',
            'par048_top_up_ratio', 'top_up_entry_rate']
    top = d.nlargest(10, 'par048_top_up_ratio')[cols].copy()
    top['total_original_tax'] = top['total_original_tax'].map('{:,.0f}'.format)
    top['total_top_up'] = top['total_top_up'].map('{:,.0f}'.format)
    print(top.round(3).to_string(index=False))
