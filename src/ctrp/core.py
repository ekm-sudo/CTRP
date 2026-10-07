"""
The model itself (business logic): settings, the four layers, reasons and the back-test.

What: turns one extract from Hue (one row per taxpayer) into a score, a band and the reasons
      for every taxpayer.
Why:  every rule that decides a score lives in this one file, so the notebook, main.py and
      production always give the same answer from the same input.

    from ctrp import core as M
    result = M.score_snapshot(M.load_extract('data/live_2026-09-30.csv'))
    result.scores      # one row per taxpayer: rank, score, band, top 3 reasons, flags
    result.reasons     # every reason for every taxpayer, one per row

How a score is built (the four layers)
  L1  Peer groups     who each taxpayer is compared with: main goods x size
  L2  Scorecard       the agreed risk parameters, each turned into points (0 to 100 in total)
  L3  Pattern check   how unusual the taxpayer looks next to their peers: a NOTE, no points
                      (Stage 6, DECISIONS 46)
  L4  Score and band  the scorecard points, rounded, put in a band (VERY LOW to VERY HIGH)

Reading order for a new officer: SETTINGS, then score_snapshot() at the bottom, then each layer.
"""
import hashlib
import json
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ctrp.utils import load_extract  # noqa: F401  (kept here so M.load_extract works)

warnings.filterwarnings('ignore', category=FutureWarning)

MODEL_VERSION = '1.0.0-dev4'


# =========================================================================================
# SETTINGS
# What: every number that shapes a score.
# Why:  one place to read and change them. Nothing further down is hard-coded, and a
#       fingerprint of these settings is stamped on every output.
# All values are PROVISIONAL until the Risk Officers confirm them.
# =========================================================================================

# ---- L2 scorecard: the risk parameters -------------------------------------------------
# Each parameter is turned into a 0..1 scale:
#   zero_at  value where concern begins (0 below it)
#   one_at   value where it is as bad as it gets (1 from there)
# Weight = L x I / total of all L x I  (L = likelihood, I = impact, each 1 to 5).
# L and I below are Data Science working ratings set from the back-test (DECISIONS 41):
# the three parameters that predict later top-ups carry most of the weight.
#   PAR_045T 33%, PAR_077 26%, PAR_045 21%, the other five 4% each.
# reason: the fixed sentence shown to officers. {v} = taxpayer's value, {z} = concern level,
#         {o} = maximum. fmt says how to write them: 'pct' (percent) or 'yesno'.
PARAMS = [
    # Officers' rule "entries with top-up / total entries". Maximum at 40%, not their 10%:
    # at 10%, 35% of regular traders hit full points and the scale stops ranking (DECISIONS 42).
    dict(code='PAR_045T', col='top_up_entry_rate', zero_at=0.03, one_at=0.40, L=5, I=5, fmt='pct',
         label='Declarations topped up',
         reason='{v} of declarations needed a top-up (concern from {z}, maximum at {o})'),
    dict(code='PAR_077', col='par077_severe_top_up_rate', zero_at=0.02, one_at=0.20, L=4, I=5, fmt='pct',
         label='Severe top-ups',
         reason='{v} of declarations had a top-up of 30% or more of the final tax (concern from {z}, maximum at {o})'),
    dict(code='PAR_045', col='par045_amended_entry_rate', zero_at=0.10, one_at=0.50, L=4, I=4, fmt='pct',
         label='Declarations amended',
         reason='{v} of declarations were amended (concern from {z}, maximum at {o})'),
    # Measured over FINAL tax so it stays between 0 and 1 (DECISIONS 32 and 40).
    dict(code='PAR_048', col='par048_top_up_share_final', zero_at=0.05, one_at=0.25, L=3, I=1, fmt='pct',
         label='Top-ups as a share of final tax',
         reason='Top-ups made up {v} of the final tax (concern from {z}, maximum at {o})'),
    dict(code='PAR_076', col='par076_shortfall_share', zero_at=0.02, one_at=0.20, L=3, I=1, fmt='pct',
         label='Value below benchmark',
         reason='Declared prices short of the HS benchmark by {v} of declared value (concern from {z}, maximum at {o})'),
    dict(code='PAR_066', col='par066_negative_top_up_rate', zero_at=0.02, one_at=0.20, L=3, I=1, fmt='pct',
         label='Tax reduced after assessment',
         reason='{v} of declarations had their tax reduced after assessment (concern from {z}, maximum at {o})'),
    dict(code='PAR_105', col='par105_top_up_180d', zero_at=0.0, one_at=1.0, L=3, I=1, fmt='yesno',
         label='Recent top-ups',
         reason='A top-up was raised within 180 days of the snapshot: {v}'),
    dict(code='PAR_023', col='par023_station_spread', zero_at=0.30, one_at=0.70, L=3, I=1, fmt='pct',
         label='Clearance away from main station',
         reason='{v} of declarations cleared away from the main station (concern from {z}, maximum at {o})'),
]

# Threshold profiles: alternative settings kept for comparison (DECISIONS 34).
# Each profile changes only what it names. Switch with set_profile('officers_andrew').
PROFILES = {
    'adopted': {},
    'officers_judith': {'PAR_045T': dict(one_at=0.10), 'PAR_048': dict(zero_at=0.03, one_at=0.06)},
    'officers_andrew': {'PAR_045T': dict(one_at=0.10)},
}

# ---- Small-history protection (credibility weighting, DECISIONS 31 and 35) --------------
# A rate built on 2 declarations is mostly luck. Each rate is pulled towards the population
# average by weight n / (n + K), where n = the taxpayer's declarations. Only ever DOWN.
SHRINK_K = 10                                                 # None switches it off
SHRINK_N = {'par076_shortfall_share': 'items_benchmarked'}    # n for PAR_076 is items, not declarations
ADEQUATE_ENTRIES = 10        # fewer than this: "limited history", no peer group, no pattern points

# ---- L1 peer groups: main goods (HS section) x size tier (DECISIONS 44) ------------------
# HDBSCAN was tested and dropped (DECISIONS 45); the evidence is in the notebook, section 4.
HS_SECTIONS = [(1, 5, 'Live animals'), (6, 14, 'Vegetable products'), (15, 15, 'Fats and oils'),
               (16, 24, 'Food, drink, tobacco'), (25, 27, 'Minerals and fuel'), (28, 38, 'Chemicals'),
               (39, 40, 'Plastics and rubber'), (41, 43, 'Hides and leather'), (44, 46, 'Wood'),
               (47, 49, 'Paper'), (50, 63, 'Textiles'), (64, 67, 'Footwear'), (68, 70, 'Stone, glass'),
               (71, 71, 'Precious metals'), (72, 83, 'Base metals'), (84, 85, 'Machinery, electrical'),
               (86, 89, 'Vehicles'), (90, 92, 'Instruments'), (93, 93, 'Arms'),
               (94, 96, 'Miscellaneous manufactures'), (97, 99, 'Art and other')]
# ---- L3 pattern check (a note only, no points: DECISIONS 46) ------------------------------
# Inputs: the scored parameters, the trading-structure measures below and a few extras.
PEER_FEATURES = ['log_value', 'log_entries', 'active_months', 'avg_items_per_entry',
                 'hs_headings_used', 'origins_used', 'cpcs_used', 'stations_used_24m',
                 'chapter_value_share']
PATTERN_FEATURES = ['volume_trend', 'im7_share', 'top_up_entry_rate', 'stations_used_90d']
UNBOUNDED = ['par076_shortfall_share']     # squashed with log before the pattern check
MIN_GROUP_FOR_PATTERN = 30                 # smaller groups are pooled into "Other goods, <size>"
PATTERN_NOTE_PCT = 0.95                    # note when more unusual than 95% of the peer group
LOW_AGREE = {'score_low': 0.25, 'pattern_high': 0.95, 'score_high': 0.90, 'pattern_low': 0.10}

# ---- L4 bands (upper edge of each band) -------------------------------------------------
BANDS = [(15, 'VERY LOW'), (35, 'LOW'), (50, 'MEDIUM'), (80, 'HIGH'), (100, 'VERY HIGH')]
SEED = 42                                  # fixed, so the same input always gives the same scores

# ---- Notes: written beside a score, carry no points --------------------------------------
NOTES = {
    'PAT': 'Trading pattern more unusual than {p} of the peer group (pattern check, no points)',
    'LIM': 'Fewer than {n} declarations in 24 months: the score rests on little history',
    'NPE': 'No close peer group: pattern check compared with a pooled group',
    'LAG': 'Parameters and pattern check disagree: worth a closer look either way',
    'MIS': '{k} of {t} parameters could not be computed; the rest were reweighted',
}

BASE_PARAMS = [dict(p) for p in PARAMS]
PROFILE = 'adopted'


def set_profile(name):
    """What: swap in a threshold profile.  Why: compare officers' thresholds with ours."""
    global PROFILE
    if name not in PROFILES:
        raise ValueError(f'unknown profile {name}; choose from {list(PROFILES)}')
    PARAMS[:] = [dict(p, **PROFILES[name].get(p['code'], {})) for p in BASE_PARAMS]
    PROFILE = name


def config_dict():
    return dict(version=MODEL_VERSION, profile=PROFILE, params=PARAMS, adequate=ADEQUATE_ENTRIES, shrink=SHRINK_K,
                peer=PEER_FEATURES, pattern=PATTERN_FEATURES, pattern_note=PATTERN_NOTE_PCT,
                min_group=MIN_GROUP_FOR_PATTERN, bands=BANDS, seed=SEED, low_agree=LOW_AGREE)


def config_fingerprint():
    """What: a 10-character code for the settings.  Why: same code = same model settings."""
    return hashlib.sha256(json.dumps(config_dict(), sort_keys=True).encode()).hexdigest()[:10]


# =========================================================================================
# PREPARATION
# =========================================================================================
def derive(df):
    """What: add the columns the model needs that the SQL does not give directly.
    Why:  keeps the SQL simple; small calculations are easier to read and test here."""
    d = df.copy()

    # Measures built from SQL columns
    d['par105_top_up_180d'] = (d['par105_days_since_last_top_up'] <= 180).astype(float)
    d['par023_station_spread'] = 1.0 - d['main_station_share']
    final_tax = d['total_original_tax'] + d['total_top_up']
    d['par048_top_up_share_final'] = (d['total_top_up'] / final_tax).where(final_tax > 0)

    # Inputs for peer groups and the pattern check (logs tame the huge spread in value)
    d['log_value'] = np.log1p(d['total_customs_value'].clip(lower=0))
    d['log_entries'] = np.log1p(d['entries_24m'])
    d['volume_trend'] = np.log((d['entries_last_90d'] + 1) / (d['entries_prev_90d'] + 1))
    d['adequate'] = d['entries_24m'] >= ADEQUATE_ENTRIES

    if SHRINK_K:
        _shrink_small_counts(d)
    return d


def _shrink_small_counts(d):
    """What: pull each rate towards the population average when it rests on few declarations.
    Why:  1 top-up in 2 declarations is 50%, but says little. The raw value is kept in
          <col>_raw for the reason text. The weighting only lowers a value, never raises it,
          so a clean small trader is never given points for other people's behaviour."""
    for p in PARAMS:
        col = p['col']
        if col + '_raw' in d:                       # already done (derive called twice)
            continue
        n = d[SHRINK_N.get(col, 'entries_24m')].fillna(0)
        has = d[col].notna()
        prior = (d.loc[has, col] * n[has]).sum() / n[has].sum()     # declaration-weighted average
        w = n / (n + SHRINK_K)
        d[col + '_raw'] = d[col]
        d[col] = np.minimum(d[col], w * d[col] + (1 - w) * prior)


def scale(x, zero_at, one_at):
    """0 at the concern level, 1 at the maximum, a straight line between, held at the ends."""
    return ((x - zero_at) / (one_at - zero_at)).clip(0, 1)


def band_of(score):
    for upper, name in BANDS:
        if score <= upper:
            return name
    return BANDS[-1][1]


def hs_section(chapter):
    """HS chapter (e.g. 87) -> WCO section name (e.g. 'Vehicles')."""
    try:
        c = int(float(chapter))
    except (TypeError, ValueError):
        return 'Unknown'
    for lo, hi, name in HS_SECTIONS:
        if lo <= c <= hi:
            return name
    return 'Unknown'


# =========================================================================================
# L1 PEER GROUPS
# What: decide who each regular taxpayer (10+ declarations) is compared with.
# Why:  "unusual" only means something next to similar traders. A large fuel importer and a
#       small car importer should not be judged against each other.
# =========================================================================================
def layer1_peers(d, log):
    return peers_section_size(d, log)


def peers_section_size(d, log):
    """Peer group = main goods x size.
      main goods: the WCO HS section of the chapter where most of the taxpayer's value is
      size:       small, medium or large = bottom, middle or top third by 24-month customs
                  value, among regular taxpayers in the SAME section
    e.g. 'Textiles, large' = a top-third textile importer by value.
    Groups under MIN_GROUP_FOR_PATTERN are pooled into 'Other goods, <size>' and flagged."""
    ad = d[d['adequate']].copy()
    ad['section'] = ad['dominant_hs_chapter'].map(hs_section)
    ad['size'] = ad.groupby('section')['log_value'].transform(_size_tiers).astype(str)
    ad['grp'] = ad['section'] + ', ' + ad['size']

    too_small = ad['grp'].map(ad['grp'].value_counts()) < MIN_GROUP_FOR_PATTERN
    ad.loc[too_small, 'grp'] = 'Other goods, ' + ad.loc[too_small, 'size']
    log.append(f"Peer groups by HS section x size: {ad['grp'].nunique()} groups; "
               f"{too_small.mean():.1%} pooled into 'Other goods'")

    codes = {g: i for i, g in enumerate(sorted(ad['grp'].unique()))}
    return pd.DataFrame({'peer_group': ad['grp'].map(codes), 'peer_group_name': ad['grp'],
                         'no_close_peers': np.where(too_small, 'Y', 'N')}, index=ad.index)


def _size_tiers(log_value):
    if len(log_value) < 3:
        return pd.Series(['medium'] * len(log_value), index=log_value.index)
    return pd.qcut(log_value.rank(method='first'), 3, labels=['small', 'medium', 'large'])


# =========================================================================================
# L2 SCORECARD
# What: each parameter -> 0..1 on its scale -> x its weight -> points. Points add up to 100.
# Why:  transparent and explainable: every point traces to one parameter and one sentence.
#       If a parameter is missing for a taxpayer, the others are reweighted to still total 100.
# =========================================================================================
def layer2_scorecard(d):
    scored = [p for p in PARAMS if p['L'] > 2]          # L <= 2 would be context only
    li = pd.Series({p['code']: p['L'] * p['I'] for p in scored})
    scaled = pd.DataFrame({p['code']: scale(d[p['col']].astype(float), p['zero_at'], p['one_at'])
                           for p in scored}, index=d.index)
    available = scaled.notna()
    weights = available.mul(li).div(available.mul(li).sum(axis=1), axis=0) * 100
    points = (scaled.fillna(0) * weights).round(2)
    return points, available, weights.round(2)


# =========================================================================================
# L3 PATTERN CHECK
# What: an Isolation Forest per peer group gives every regular taxpayer an "unusualness"
#       percentile (1.00 = the most unusual in the group). Above PATTERN_NOTE_PCT the officer
#       gets a note. It adds NO points.
# Why:  Stage 6 showed the pattern points lowered lift: the forest mostly flags traders with
#       many products, not traders who are later topped up (DECISIONS 46). Kept as a note so
#       officers still see an odd profile.
# =========================================================================================
def layer3_pattern(d, peers, subtotal):
    cols = list(dict.fromkeys([p['col'] for p in PARAMS] + PEER_FEATURES + PATTERN_FEATURES))
    pct = pd.Series(np.nan, index=d.index)
    for _, idx in peers.groupby('peer_group').groups.items():
        sub = d.loc[idx, cols].astype(float).copy()
        for c in UNBOUNDED:
            sub[c] = np.log1p(sub[c].clip(lower=0))
        sub = sub.fillna(sub.median()).fillna(0)
        if len(sub) < MIN_GROUP_FOR_PATTERN:
            continue
        forest = IsolationForest(n_estimators=200, random_state=SEED).fit(sub)
        pct.loc[idx] = pd.Series(-forest.score_samples(sub), index=idx).rank(pct=True)

    # Low agreement: scorecard and pattern check point opposite ways
    s_pct = subtotal.rank(pct=True)
    low = ((s_pct < LOW_AGREE['score_low']) & (pct > LOW_AGREE['pattern_high'])) | \
          ((s_pct > LOW_AGREE['score_high']) & (pct < LOW_AGREE['pattern_low']))
    return pct, low


# =========================================================================================
# REASONS
# What: one fixed sentence per parameter that earned points, largest first.
# Why:  two taxpayers with the same facts get word-for-word the same explanation.
# =========================================================================================
def _fmt(v, kind):
    if pd.isna(v):
        return 'not available'
    if kind == 'pct':
        return f'{v:.0%}' if v < 10 else f'{v:,.0f} times'
    if kind == 'yesno':
        return 'yes' if v >= 0.5 else 'no'
    return str(v)


def build_reasons(d, points):
    """Long table: one row per taxpayer per reason, ordered by points then code.
    The sentence shows the taxpayer's RAW value (before small-count weighting)."""
    pinfo = {p['code']: p for p in PARAMS}
    long = points.reset_index().melt(id_vars='index', var_name='code', value_name='points')
    long = long[long['points'] > 0]
    rows = []
    for idx, code, pts in long[['index', 'code', 'points']].itertuples(index=False):
        p = pinfo[code]
        raw_col = p['col'] + '_raw' if p['col'] + '_raw' in d else p['col']
        v = d.at[idx, raw_col]
        text = p['reason'].format(v=_fmt(v, p['fmt']), z=_fmt(p['zero_at'], p['fmt']),
                                  o=_fmt(p['one_at'], p['fmt']))
        rows.append((idx, code, p['label'], text, v, p['zero_at'], p['one_at'], pts))
    r = pd.DataFrame(rows, columns=['_idx', 'code', 'label', 'reason', 'value', 'concern_level',
                                    'maximum_level', 'points'])
    r = r.sort_values(['_idx', 'points', 'code'], ascending=[True, False, True])
    r['order'] = r.groupby('_idx').cumcount() + 1
    return r


def build_notes(s):
    """Notes (no points): an unusual pattern, and how much weight a score can bear."""
    notes = []
    for idx in s.index[s['flag_unusual_pattern'] == 'Y']:
        notes.append((idx, 'PAT', NOTES['PAT'].format(p=f"{s.at[idx, 'pattern_percentile']:.0%}")))
    for idx in s.index[s['flag_limited_history'] == 'Y']:
        notes.append((idx, 'LIM', NOTES['LIM'].format(n=ADEQUATE_ENTRIES)))
    for idx in s.index[s['flag_no_close_peers'] == 'Y']:
        notes.append((idx, 'NPE', NOTES['NPE']))
    for idx in s.index[s['flag_low_agreement'] == 'Y']:
        notes.append((idx, 'LAG', NOTES['LAG']))
    missing = s['params_total'] - s['params_scored']
    for idx in missing[missing > 0].index:
        notes.append((idx, 'MIS', NOTES['MIS'].format(k=missing.at[idx], t=s.at[idx, 'params_total'])))
    nt = pd.DataFrame(notes, columns=['_idx', 'code', 'text'])
    text = nt.groupby('_idx')['text'].agg(' | '.join).reindex(s.index).fillna('')
    codes = nt.groupby('_idx')['code'].agg(','.join).reindex(s.index).fillna('')
    return text, codes


# =========================================================================================
# THE WHOLE MODEL
# What: run L2 -> L1 -> L3 -> L4 on one extract and package the result.
# Why:  the only function the notebook, the command line and production need to call.
# =========================================================================================
@dataclass
class Result:
    snapshot: str
    scores: pd.DataFrame
    reasons: pd.DataFrame
    params: pd.DataFrame
    log: list = field(default_factory=list)
    version: str = MODEL_VERSION
    fingerprint: str = ''


NOT_GROUPED = 'Not grouped (fewer than 10 declarations)'


def score_snapshot(raw):
    snap = str(raw['snapshot_date'].iloc[0])[:10]
    d = derive(raw)
    log = [f'Snapshot {snap}: {len(d):,} taxpayers, {int(d["adequate"].sum()):,} with '
           f'{ADEQUATE_ENTRIES}+ declarations']

    # ---- the four layers ----
    points, available, _ = layer2_scorecard(d)
    subtotal = points.sum(axis=1)
    peers = layer1_peers(d, log)
    pat_pct, low = layer3_pattern(d, peers, subtotal)

    # ---- L4: one row per taxpayer ----
    s = pd.DataFrame(index=d.index)
    s['taxpayer_tin'] = d['taxpayer_tin']
    s['snapshot_date'] = snap
    s['score'] = subtotal.round().clip(0, 100).astype(int)
    s['band'] = s['score'].map(band_of)
    s['scorecard_points'] = subtotal.round(2)
    s['pattern_percentile'] = pat_pct.round(3)
    s['flag_unusual_pattern'] = np.where(pat_pct >= PATTERN_NOTE_PCT, 'Y', 'N')
    s['params_scored'] = available.sum(axis=1)
    s['params_total'] = available.shape[1]
    s['peer_group'] = peers['peer_group'].reindex(d.index).fillna(-1).astype(int)
    if 'peer_group_name' in peers:
        s['peer_group_name'] = peers['peer_group_name'].reindex(d.index).fillna(NOT_GROUPED)
    else:
        s['peer_group_name'] = s['peer_group'].map(lambda g: f'Group {g}' if g >= 0 else NOT_GROUPED)
    s['flag_limited_history'] = np.where(d['adequate'], 'N', 'Y')
    s['flag_no_close_peers'] = peers['no_close_peers'].reindex(d.index).fillna('N')
    s['flag_low_agreement'] = np.where(low, 'Y', 'N')
    s['declarations_24m'] = d['entries_24m']
    s['customs_value_24m'] = d['total_customs_value']
    s['_rank_key'] = subtotal                             # unrounded, so ties rank stably

    # ---- reasons and notes ----
    reasons = build_reasons(d, points)
    s['notes'], s['note_codes'] = build_notes(s)
    for k in (1, 2, 3):
        rk = reasons[reasons['order'] == k].set_index('_idx')
        s[f'reason_{k}'] = (rk['code'] + ': ' + rk['reason']).reindex(s.index).fillna('')

    # ---- rank, highest risk first ----
    s = s.sort_values(['_rank_key', 'taxpayer_tin'], ascending=[False, True])
    s.insert(0, 'rank', np.arange(1, len(s) + 1))

    reasons = reasons.merge(s[['taxpayer_tin', 'score', 'band']], left_on='_idx', right_index=True)
    reasons = reasons[['taxpayer_tin', 'score', 'band', 'order', 'code', 'label', 'reason', 'value',
                       'concern_level', 'maximum_level', 'points']]
    reasons = reasons.sort_values(['score', 'taxpayer_tin', 'order'], ascending=[False, True, True])

    pv = d[['taxpayer_tin'] + [p['col'] for p in PARAMS]].copy()
    for p in PARAMS:
        if p['L'] > 2:
            pv[f'points_{p["code"]}'] = points[p['code']]
    pv = pv.loc[s.index]

    return Result(snapshot=snap, scores=s.drop(columns='_rank_key').reset_index(drop=True),
                  reasons=reasons.reset_index(drop=True), params=pv.reset_index(drop=True), log=log,
                  fingerprint=config_fingerprint())


# =========================================================================================
# BACK-TEST
# What: compare the model's top x% with what happened in the 6 months after the snapshot.
# Why:  the only honest test of a risk model: did the taxpayers it ranked high go on to be
#       topped up more often than everyone else?  Lift = their hit rate / everyone's.
# =========================================================================================
def outcome_summary(frame, key):
    g = frame.groupby(key, observed=True).agg(
        taxpayers=('taxpayer_tin', 'count'), entries=('out_entries', 'sum'),
        checked=('out_checked', 'sum'), hits=('out_checked_hits', 'sum'),
        top_up=('out_top_up', 'sum'), original_tax=('out_original_tax', 'sum'))
    g['hit_rate'] = g['hits'] / g['checked'].replace(0, np.nan)
    g['top_up_rate'] = g['top_up'] / g['original_tax'].replace(0, np.nan)
    return g


def backtest(result, raw, shares=(0.01, 0.05, 0.10), baseline_col='par048_top_up_ratio'):
    """Top x% by the model vs top x% by past top-ups alone (the baseline), against everyone."""
    m = result.scores.merge(raw[['taxpayer_tin', baseline_col] + [c for c in raw if c.startswith('out_')]],
                            on='taxpayer_tin')
    base = outcome_summary(m.assign(all='ALL'), 'all').iloc[0]
    rows = []
    for share in shares:
        k = max(1, int(round(share * len(m))))
        for name, order in [('Model', m['rank']),
                            ('Past top-ups only', m[baseline_col].fillna(0).rank(ascending=False, method='first'))]:
            g = outcome_summary(m[order <= k].assign(all='x'), 'all').iloc[0]
            rows.append(dict(snapshot=result.snapshot, top_share=share, ranked_by=name, taxpayers=k,
                             hit_rate=g['hit_rate'], top_up_rate=g['top_up_rate'],
                             hit_lift=g['hit_rate'] / base['hit_rate'] if base['hit_rate'] else np.nan))
    by_band = outcome_summary(m, 'band').reindex([b for _, b in BANDS]).assign(snapshot=result.snapshot)
    return pd.DataFrame(rows), by_band.reset_index(), base
