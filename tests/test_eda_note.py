"""
Tests for the Zeppelin EDA and features note (src/ctrp/eda_note.py).

What: (1) the note is complete: every setting filled in, the code compiles, all 22 features and both tracks are
      there, and the settings are the production ones; (2) when PySpark is installed, the note is run on a
      synthetic view and every column is compared with the production query and the production Python
      (core.derive for Track A, discovery for Track B), and every data problem table with its Hue query.
Why:  the note must give the same numbers as production, or the sign-off would be on something else.

The second part needs PySpark (Python 3.11 or 3.12; it does not install on 3.13) and Java. Without them it is
skipped. To run it:  py -3.11 -m pytest tests/test_eda_note.py
"""
import re

import numpy as np
import pandas as pd
import pytest

from ctrp import core as M
from ctrp import discovery as B
from ctrp import eda_note as N
from ctrp import eda_note_mine as N2
from ctrp import extract as E
from ctrp import issues as I


@pytest.mark.parametrize('note', [N, N2])
def test_every_setting_is_filled_and_the_code_compiles(note):
    for _, text in note.paragraphs():
        assert not re.findall(r'__[A-Z0-9_]+__', text)
    compile(note.script(), 'note', 'exec')


@pytest.mark.parametrize('note', [N, N2], ids=['review note', 'my note'])
def test_note_has_the_22_features_and_both_tracks(note):
    code = note.script()
    assert len(N.FEATURE_LIST) == 22
    # 22 features, 23 names: 'amended' has a 3-year name (Track A) and a 24-month name (Track B)
    assert len(set(N.TRACK_A_NAMES.values()) | set(N.TRACK_B_NAMES.values())) == 23
    track_a = re.search(r'TRACK_A = [\[{](.*?)[\]}]', code, re.S).group(1)
    assert re.findall(r"'(\w+)'", track_a)[::1 if note is N2 else 2] == [N.TRACK_A_NAMES[p['col']] for p in M.PARAMS]
    track_b = re.search(r'TRACK_B = [\[{](.*?)[\]}]', code, re.S).group(1)
    names = re.findall(r"'(\w+)'", track_b)
    names = [x for x in names if x not in ('decl_24m_count', 'priced_items_24m_count')]
    assert names == [N.TRACK_B_NAMES[f] for f, *_ in B.FEATURES]


def test_names_follow_the_rule():
    # unit last, no parameter codes, no 'share'
    units = ('_rate', '_flag', '_log', '_ratio', '_diff', '_score', '_count', '_ugx')
    for old, new in N.FEATURE_NAMES.items():
        if old in ('days_since_last_top_up',) or new.startswith('days_since'):
            continue
        assert new.endswith(units), new
        assert not re.search(r'par\d{3}|ctx_|share', new), new


def test_note_uses_the_production_settings():
    code = N.script()
    assert repr(E.MOTOR_VEHICLE_HEADINGS) in code
    assert f'EXCLUDE_APC_483 = {E.EXCLUDE_APC_483}' in code
    assert f'LATEST_DECLARATION_PER_ENTRY = {E.LATEST_DECLARATION_PER_ENTRY}' in code
    assert f"SNAPSHOT = '{E.LIVE_SNAPSHOT}'" in code
    for code_, *_ in I.ISSUES:
        assert (f"'{code_}'" in code) == (code_ in N.REVIEW_ISSUES)


# =========================================================================================
# The note against production, on a synthetic view (needs PySpark)
# =========================================================================================
@pytest.fixture(scope='module')
def spark(tmp_path_factory):
    pytest.importorskip('pyspark')
    import os
    import sys
    os.environ.setdefault('PYSPARK_PYTHON', sys.executable)
    from pyspark.sql import SparkSession, types as T
    try:
        from tests.synthetic_view import make
    except ImportError:
        from synthetic_view import make
    try:
        s = (SparkSession.builder.master('local[2]').config('spark.ui.enabled', 'false')
             .config('spark.ui.showConsoleProgress', 'false').config('spark.sql.shuffle.partitions', '4')
             .config('spark.sql.warehouse.dir', str(tmp_path_factory.mktemp('warehouse'))).getOrCreate())
    except Exception as e:                                   # no Java
        pytest.skip(f'Spark cannot start: {e}')
    s.sparkContext.setLogLevel('ERROR')
    v = make(seed=5, n_tp=150, n_decl=12000)
    num = {'customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt', 'final_amt', 'top_up_amt'}
    ints = {'is_red_flg', 'is_yellow_flg'}
    schema = T.StructType([T.StructField(c, T.DoubleType() if c in num else T.IntegerType() if c in ints else T.StringType())
                           for c in v.columns])

    def clean(x, c):                                         # blanks must be NULL, as in Hive, not NaN
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return float(x) if c in num else int(x) if c in ints else str(x)
    rows = [tuple(clean(x, c) for x, c in zip(r, v.columns)) for r in v.itertuples(index=False)]
    s.sql('CREATE DATABASE IF NOT EXISTS dm_modeled_ura_datascience')
    s.createDataFrame(rows, schema).write.mode('overwrite').saveAsTable('dm_modeled_ura_datascience.vw_cstm_AEO_model')
    yield s


class _Z:
    """Stands in for Zeppelin's z: runs every result shown, picks the default of a dropdown."""
    def show(self, df, *a, **k):
        if not isinstance(df, pd.DataFrame):
            df.limit(5).collect()

    def select(self, name, options, default=''):
        return default


def _run_note(spark, snapshot, with_outcomes, note=N):
    code = (note.script().replace(f"SNAPSHOT = '{E.LIVE_SNAPSHOT}'", f'SNAPSHOT = {snapshot!r}')
            .replace('WITH_OUTCOMES = False', f'WITH_OUTCOMES = {with_outcomes}'))
    ns = {'spark': spark, 'z': _Z()}
    exec(compile(code, 'note', 'exec'), ns)
    return ns


def _production(spark, snapshot, live):
    _, sql, *_ = E.render(snapshot, live=live)
    sql = re.sub(r'(?<![\w.])(\d+\.\d+)(?![\w.])', r'\1D', sql)     # Hive reads 1.0 as a double, Spark as a decimal
    prod = spark.sql(sql).toPandas()
    prod['taxpayer_tin'] = prod['taxpayer_tin'].astype(str)
    return prod.sort_values('taxpayer_tin').reset_index(drop=True)


@pytest.mark.parametrize('note', [N, N2], ids=['review note', 'my note'])
@pytest.mark.parametrize('snapshot,live', [(E.LIVE_SNAPSHOT, True), ('2026-03-31', False)])
def test_note_gives_the_production_numbers(spark, snapshot, live, note):
    ns = _run_note(spark, snapshot, with_outcomes=not live, note=note)
    prod = _production(spark, snapshot, live)
    p = prod.set_index('taxpayer_tin')
    inputs = spark.table('ctrp_feature_inputs').toPandas().set_index('taxpayer_tin').reindex(p.index)
    final = ns['final_dataset'].set_index('taxpayer_tin').reindex(p.index)
    assert len(final) == len(ns['final_dataset']) == len(p)

    def same(a, b):
        return np.isclose(pd.to_numeric(a), pd.to_numeric(b), rtol=1e-9, atol=1e-12, equal_nan=True).all()

    renamed = {old: new for old, new in N.FEATURE_NAMES.items() if old in p and new in inputs}
    assert len(renamed) >= 30          # every production column that the notes also build
    bad = [old for old, new in renamed.items() if not same(inputs[new], p[old])]
    assert (inputs['new_trader'] == p['new_trader']).all()
    d = M.derive(prod.copy()).set_index('taxpayer_tin')
    for q in M.PARAMS:
        name = N.TRACK_A_NAMES[q['col']]
        bad += [name] if not same(final[name], d[q['col']]) else []
        bad += ['raw_' + name] if not same(final['raw_' + name], d[q['col'] + '_raw']) else []
    X = B.build_features(prod)
    P = B.peer_percentiles(X, B.section_size_groups(prod))
    X.index = P.index = prod['taxpayer_tin']
    for c in X:
        name = N.TRACK_B_NAMES[c]
        pct = 'b_' + name.rsplit('_', 1)[0] + '_pct'
        bad += ['b_' + name] if not same(final['b_' + name], X[c]) else []
        bad += [pct] if not same(final[pct], P[c]) else []
    for c in [c for c in p if c.startswith('out_') and not live]:
        bad += [c] if not same(final[c], p[c]) else []
    assert not bad, f'columns that differ from production: {bad}'


@pytest.mark.parametrize('note', [N, N2], ids=['review note', 'my note'])
def test_problem_tables_match_the_hue_queries(spark, note):
    ns = _run_note(spark, E.LIVE_SNAPSHOT, with_outcomes=False, note=note)
    log = spark.table('ctrp_cleaning_log').toPandas()
    assert int(log['rows left'].iloc[-1]) == ns['items'].count()
    expected = N.REVIEW_ISSUES if note is N else [i[0] for i in I.ISSUES] + ['E13']
    for issue in I.ISSUES + [None]:
        code, sql = ('E13', I.render_names()) if issue is None else (issue[0], I.render(issue))
        if code not in expected:
            continue
        hue = spark.sql(sql).toPandas().astype(str)
        note = spark.table('ctrp_eda_' + code.lower()).toPandas().astype(str)
        assert list(note.columns) == list(hue.columns), code
        cols = list(hue.columns)
        assert hue.sort_values(cols).reset_index(drop=True).equals(note.sort_values(cols).reset_index(drop=True)), code


def test_pull_reads_the_run_order():
    from ctrp import datalake
    text = ('[ ] sql/long_run/if_too_big/long_run_2021.sql       save as data/long_run/long_run_2021.csv\n'
            '[ ] sql/bt_2023-09-30.sql                           save as data/bt_2023-09-30.csv\n')
    assert datalake.run_order_jobs(text) == [
        ('sql/long_run/if_too_big/long_run_2021.sql', 'data/long_run/long_run_2021.csv'),
        ('sql/bt_2023-09-30.sql', 'data/bt_2023-09-30.csv')]
