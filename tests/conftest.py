"""
Shared test data: a made-up extract with the same columns as a real Hue download.

What: make_extract() builds n fake taxpayers whose rates and counts are consistent.
Why:  tests must run anywhere, quickly, and never touch real taxpayer data.
"""
import numpy as np
import pandas as pd
import pytest


def make_extract(n=500, snapshot='2026-03-31', seed=0):
    rng = np.random.default_rng(seed)
    entries = np.maximum(1, rng.lognormal(2.0, 1.4, n).round()).astype(int)
    risk = rng.beta(1, 8, n)                                     # each taxpayer's true top-up tendency
    topped = rng.binomial(entries, risk)
    severe = rng.binomial(topped, 0.4)
    amended = rng.binomial(entries, np.clip(risk * 2, 0, 1))
    negative = rng.binomial(entries, 0.01)
    orig_tax = rng.lognormal(17, 2, n)
    top_up = np.where(topped > 0, orig_tax * rng.uniform(0.01, 0.3, n), 0.0)
    items_b = (entries * rng.uniform(1, 3, n)).round()
    checked = rng.binomial(np.maximum(1, entries // 4), 0.6)
    hits = rng.binomial(checked, np.clip(risk * 3, 0, 1))
    d = pd.DataFrame({
        'taxpayer_tin': [f'{1000000000 + i:010d}' for i in range(n)],
        'snapshot_date': snapshot,
        'limited_history': np.where(entries < 10, 'Y', 'N'),
        'entries_24m': entries,
        'active_months': np.minimum(24, np.maximum(1, entries // 2)),
        'avg_items_per_entry': rng.uniform(1, 6, n),
        'total_customs_value': rng.lognormal(20, 2, n),
        'total_original_tax': orig_tax,
        'total_top_up': top_up,
        'hs_headings_used': rng.integers(1, 40, n),
        'origins_used': rng.integers(1, 8, n),
        'cpcs_used': rng.integers(1, 4, n),
        'dominant_hs_chapter': rng.choice([87, 84, 61, 39, 27, 10], n),
        'chapter_value_share': rng.uniform(0.3, 1, n),
        'stations_used_24m': rng.integers(1, 5, n),
        'stations_used_90d': rng.integers(1, 3, n),
        'main_station_share': rng.uniform(0.3, 1, n),
        'entries_last_90d': rng.integers(0, 10, n),
        'entries_prev_90d': rng.integers(0, 10, n),
        'im7_share': rng.uniform(0, 1, n),
        'distinct_consignees': 1,
        'consignee_is_self_share': 1.0,
        'par045_amended_entry_rate': amended / entries,
        'par048_top_up_ratio': np.where(orig_tax > 0, top_up / orig_tax, np.nan),
        'par066_negative_top_up_rate': negative / entries,
        'par077_severe_top_up_rate': severe / entries,
        'par105_days_since_last_top_up': np.where(topped > 0, rng.integers(1, 700, n), np.nan),
        'top_up_entry_rate': topped / entries,
        'items_benchmarked': items_b,
        'par076_low_price_item_rate': rng.uniform(0, 0.3, n),
        'par076_shortfall_share': rng.exponential(0.05, n),
        'ctx_implausible_price_rate': 0.0,
        'ctx_unpaid_rate': rng.uniform(0, 0.1, n),
        'ctx_red_lane_rate': rng.uniform(0, 1, n),
        'ctx_yellow_lane_rate': rng.uniform(0, 0.5, n),
        'ctx_preferential_use_rate': rng.uniform(0, 0.2, n),
        'out_entries': checked + rng.integers(0, 3, n),
        'out_checked': checked,
        'out_checked_hits': hits,
        'out_topped_up_entries': hits,
        'out_top_up': hits * rng.lognormal(14, 1, n),
        'out_original_tax': rng.lognormal(16, 1, n),
    })
    return d


@pytest.fixture
def extract():
    return make_extract()


@pytest.fixture
def extracts():
    snaps = ['2024-09-30', '2025-03-31', '2025-09-30', '2026-03-31']
    return {s: make_extract(400, s, seed=i) for i, s in enumerate(snaps)}
