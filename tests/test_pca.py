"""Post-clearance audit list and officer view: the queries are valid for Hue, and blanks never break the page."""
import json

import numpy as np
import pandas as pd

from ctrp import officer_view as V
from ctrp import pca


def test_queries_are_single_statements():
    for _, a, b in pca.MONTHS:
        for sql in (pca.q_entries(a, b), pca.q_items(a, b)):
            assert ';' not in sql                       # Hue splits statements on semicolons
            assert f"> '{a}'" in sql and f"<= '{b}'" in sql


def test_signals_text():
    r = pd.Series({'items_under_half_peer_price': 1, 'lowest_price_vs_peers': 0.25, 'items_50_80_pct_of_peer_price': 0,
                   'items_possible_unit_error': 0, 'items_under_half_peer_duty': 0, 'lowest_duty_vs_peers': np.nan,
                   'watchlist_apcs': '451', 'items_claiming_preference': 0, 'same_day_same_hs_declarations': np.nan,
                   'same_day_norm_for_goods': np.nan, 'amended': 'N', 'new_importer': 'Y'})
    assert pca._signals(r) == 'price 25% of peers; watchlist APC 451; new importer'


def test_page_data_has_no_nan():
    d = pd.DataFrame({'a': [1.0, np.nan], 'b': ['x', None], 'c': [np.int64(3), np.int64(4)]})
    rec = V._records(d, ['a', 'b', 'c'])
    json.dumps(rec, allow_nan=False)                    # raises if a NaN slipped through
    assert rec['rows'][1] == [None, None, 4]
