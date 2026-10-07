"""What: checks the measuring stick (lift and friends) and the CSV reader.
Why:  every comparison in the project rests on these being right."""
import numpy as np
import pandas as pd
import pytest

from ctrp import utils as U


def test_top_mask_takes_exactly_k():
    score = pd.Series(np.arange(100, dtype=float))
    assert U.top_mask(score, 0.05).sum() == 5
    assert U.top_mask(score, 0.05)[-5:].all()            # the five highest scores


def test_lift_of_a_perfect_ranking_beats_random(extract):
    perfect = extract['out_checked_hits'] / extract['out_checked'].replace(0, np.nan)
    random = pd.Series(np.random.default_rng(1).random(len(extract)))
    assert U.lift(extract, perfect.fillna(0), 0.05) > 2
    assert U.lift(extract, perfect.fillna(0), 0.05) > U.lift(extract, random, 0.05)


def test_lift_of_everyone_is_one(extract):
    assert U.lift(extract, pd.Series(np.ones(len(extract))), 1.0) == pytest.approx(1.0)


def test_revenue_share_is_between_0_and_1(extract):
    share = U.revenue_share(extract, extract['top_up_entry_rate'], 0.1)
    assert 0 <= share <= 1


def test_load_extract_keeps_tins_as_text_and_refuses_duplicates(tmp_path, extract):
    f = tmp_path / 'x.csv'
    extract.assign(taxpayer_tin='0' + extract['taxpayer_tin'].str[1:]).to_csv(f, index=False)
    d = U.load_extract(f)
    assert d['taxpayer_tin'].str.len().eq(10).all() and d['taxpayer_tin'].str.startswith('0').all()
    pd.concat([extract, extract.head(1)]).to_csv(f, index=False)
    with pytest.raises(ValueError):
        U.load_extract(f)
