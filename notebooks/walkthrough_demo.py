"""
Walk through Track A and Track B step by step, on MADE-UP data (no real TINs, no Hue needed).

What: builds a fake extract, then prints every intermediate value for one taxpayer: raw rates,
      recency, credibility weighting, ramp, weight, points, band, reasons (Track A); features,
      peer percentiles, model contributions, flag (Track B); and the Overall Risk Band.
Why:  reading the code beside real numbers is the fastest way to see what each function does.

    python notebooks/walkthrough_demo.py              # picks a taxpayer with points on several parameters
    python notebooks/walkthrough_demo.py 1000000042   # a chosen (fake) TIN
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

import pandas as pd  # noqa: E402

from ctrp import core as M, discovery as B, report as R  # noqa: E402
from tests.conftest import make_extract  # noqa: E402

pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 120)


def title(text):
    print('\n' + '=' * 100 + '\n' + text + '\n' + '=' * 100)


# ---- made-up data: three earlier snapshots to train Track B, one to score ----
snaps = ['2024-09-30', '2025-03-31', '2025-09-30', '2026-03-31']
extracts = {s: make_extract(3000, s, seed=i) for i, s in enumerate(snaps)}
raw = extracts[snaps[-1]]

# =========================================================================================
title('TRACK A, Step 1: derive() - recency weighting, then credibility weighting')
# =========================================================================================
d = M.derive(raw)
points, available, weights = M.layer2_scorecard(d)
if len(sys.argv) > 1:
    tin = sys.argv[1]
else:      # a regular taxpayer with points on at least three parameters makes the best example
    ok = (points > 0).sum(axis=1).ge(3) & d['adequate']
    tin = d.loc[ok[ok].index[0], 'taxpayer_tin']
i = d.index[d['taxpayer_tin'] == tin][0]
print(f'Taxpayer {tin}: {int(d.at[i, "entries_24m"])} declarations in 24 months '
      f'(credibility weight n/(n+K) = {d.at[i, "entries_24m"]}/({d.at[i, "entries_24m"]}+{M.SHRINK_K}) '
      f'= {d.at[i, "entries_24m"] / (d.at[i, "entries_24m"] + M.SHRINK_K):.2f})')
print(f'Recency applied: {bool(d.at[i, "recency_applied"])} (the made-up data has no yearly counts, '
      f'so the 24-month rates are used, as the code does for any extract without them)\n')
rows = []
for p in M.PARAMS:
    raw_v = d.at[i, p['col'] + '_raw'] if p['col'] + '_raw' in d else d.at[i, p['col']]
    rows.append(dict(code=p['code'], parameter=p['label'], raw_value=raw_v, after_weighting=d.at[i, p['col']]))
print(pd.DataFrame(rows).round(4).to_string(index=False))

# =========================================================================================
title('TRACK A, Step 2: layer2_scorecard() - ramp (scale), weight (L x I / total), points')
# =========================================================================================
li_total = sum(p['L'] * p['I'] for p in M.PARAMS)
rows = []
for p in M.PARAMS:
    x = d.at[i, p['col']]
    sc = float(M.scale(pd.Series([x]), p['zero_at'], p['one_at']).iloc[0])
    rows.append(dict(code=p['code'], value=x, zero_at=p['zero_at'], one_at=p['one_at'],
                     ramp_0_to_1=sc, L=p['L'], I=p['I'], LxI=p['L'] * p['I'],
                     max_points=f"{p['L'] * p['I']}/{li_total} x 100 = {p['L'] * p['I'] / li_total * 100:.1f}",
                     points=points.at[i, p['code']]))
t = pd.DataFrame(rows)
print(t.round(3).to_string(index=False))
print(f'\nramp = clip((value - zero_at) / (one_at - zero_at), 0, 1);  points = ramp x max_points')
print(f'Sum of points = {points.loc[i].sum():.2f}  ->  History Risk Score {round(points.loc[i].sum())}')

# =========================================================================================
title('TRACK A, Steps 3 to 5: peer group, pattern check (note only), band, reasons')
# =========================================================================================
res = M.score_snapshot(raw)
s = res.scores.set_index('taxpayer_tin').loc[tin]
for c in ['rank', 'score', 'band', 'peer_group_name', 'pattern_percentile', 'flag_unusual_pattern',
          'flag_limited_history', 'flag_low_agreement', 'reason_1', 'reason_2', 'reason_3', 'notes']:
    print(f'{c:22s} {s[c]}')
print('\nBands (score up to):', ', '.join(f'{b} <= {u}' for u, b in M.BANDS))
print('Band counts in this made-up snapshot:')
print(res.scores['band'].value_counts().reindex([b for _, b in M.BANDS]).fillna(0).astype(int).to_string())

# =========================================================================================
title('TRACK B, Sections 2 and 3: behaviour features and peer percentiles')
# =========================================================================================
X = B.build_features(raw)
groups = B.section_size_groups(raw)
P = B.peer_percentiles(X, groups)
print(f'Peer group (HS section | size tier 0-2): {groups.iloc[i]}')
print(f'Segment: {"regular" if raw.at[i, "entries_24m"] >= M.ADEQUATE_ENTRIES else "small"};  '
      f'no top-up history: {bool(B.no_history(raw).iloc[i])}\n')
print(pd.DataFrame({'feature': [B.LABEL[c] for c in P.columns], 'value': X.loc[i, P.columns].to_numpy(),
                    'peer_percentile': P.loc[i].to_numpy(),
                    'in_model': [c not in B.DROPPED for c in P.columns]}).round(3).to_string(index=False))

# =========================================================================================
title('TRACK B, Sections 4 and 5: train on earlier snapshots, score, explain, flag')
# =========================================================================================
train = [extracts[x] for x in snaps[:-1]]
models, cols = B.fit_models(train)
seg = 'regular' if raw.at[i, 'entries_24m'] >= M.ADEQUATE_ENTRIES else 'small'
gb = models[seg]
print(f'Trained one model per segment on {len(train)} earlier snapshots, {len(cols)} features.')
print(f'Model rules: monotonic_cst={gb.monotonic_cst[:3]}... (risk only rises), '
      f'interaction_cst={gb.interaction_cst[:3]}... (each feature alone = additive)\n')
row = P.loc[[i], cols]
score = gb.decision_function(row.to_numpy())[0]
contrib = {}
for c in cols:
    ref = row.copy()
    ref[c] = B.REFERENCE_PCT
    contrib[B.LABEL[c]] = score - gb.decision_function(ref.to_numpy())[0]
contrib = pd.Series(contrib).sort_values(ascending=False)
print(f'Score (log-odds of a hit per check): {score:.4f}')
print('Contribution of each feature = score - score with that feature set to the peer median (0.5):')
print(contrib.round(4).to_string())
print('Check: the contributions are exact parts of the score because the model is additive.')

out = B.score_snapshot_b(raw, train).set_index('taxpayer_tin').loc[tin]
print()
for c in ['segment', 'discovery_percentile', 'on_discovery_list', 'discovery_reason_1', 'discovery_reason_2']:
    print(f'{c:22s} {out[c]}')

# =========================================================================================
title('BOTH TRACKS: report.two_tracks() - the Overall Risk Band')
# =========================================================================================
both = R.two_tracks(res.scores, B.score_snapshot_b(raw, train))
b = both.set_index('taxpayer_tin').loc[tin]
print(f'History Risk Band {b["band"]}, Risky Behaviour Flag {b["on_discovery_list"]} '
      f'-> Overall Risk Band {b["overall_band"]} (set by: {b["driven_by"]})')
print('Rule: a flagged taxpayer whose History band is below HIGH is lifted to HIGH; otherwise History decides.')
lifted = (both['driven_by'] == 'Trading behaviour').sum()
print(f'In this made-up snapshot {lifted} taxpayers were lifted to HIGH by the flag.')
print(f'\nModel {M.MODEL_VERSION}, settings fingerprint {M.config_fingerprint()}. '
      f'The numbers above come from made-up data: do not quote them.')
