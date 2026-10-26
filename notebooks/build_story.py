"""
Build the notebook CTRP_story.ipynb: the EDA and feature story, decision by decision.

What: a notebook to present from. Each step asks one question, shows example records (the first 10 rows),
      a chart or table from the real extracts, what we decided, and what it means for Customs.
      Code cells are folded so the story reads cleanly. Example records show real TINs and declaration
      numbers, so a run notebook is for internal use only and is not committed to git (see .gitignore).
Why:  the reasoning behind the features is easier to follow in the order the decisions were made than in
      SQL files or slides, and example records show that a feature is built, not picked from a column.

    python notebooks/build_story.py                       (writes notebooks/CTRP_story.ipynb)
    then open it and Run All, or, to save a copy with no code for sharing:
    jupyter nbconvert --to html --no-input --execute notebooks/CTRP_story.ipynb --output-dir results

Optional example records from the view (three small Hue queries; the notebook works without them):
    sql/review/story_01_one_taxpayer.sql  ->  data/samples/story_one_taxpayer.csv
    sql/story/story_02_repeated_item.sql  ->  data/samples/story_repeated_item.csv
    sql/story/story_03_top_up_column.sql  ->  data/samples/story_top_up_column.csv
"""
from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []
HIDE = {'jupyter': {'source_hidden': True}, 'tags': ['hide-input']}


def md(s):
    C.append(nbf.v4.new_markdown_cell(s.strip()))


def code(s):
    C.append(nbf.v4.new_code_cell(s.strip(), metadata=dict(HIDE)))


# =================================================================================== title
md(r"""
# CTRP: from the data to the features

**Customs Taxpayer Risk Profiling Model.** Data Science Section, ITID.

This notebook tells the story of how the model was built, in the order the decisions were made. Each step
answers one question. For each step you will see:

* **Example records**: the first 10 rows of the data the step works on, so you can see what the model sees.
* **The evidence**: a chart or table from the real data.
* **What we decided**, and why.
* **What it means for Customs**: how the decision affects officers, traders and revenue.

| Part | Question |
|---|---|
| A | What are we trying to predict? |
| B | What does the data look like, and what did it force on us? (EDA) |
| C | How does a column in the data become a feature? |
| D | How did we choose and shape each feature? |
| E | How do features become a score and a band? |
| F | What does Track B look at, for taxpayers with no record? |

**To present:** Run All (about a minute). The code is folded away; click the left edge of a cell to see it.
Example records show real TINs and declaration numbers: this notebook is for internal use only.
""")

code(r"""
# What: libraries, chart style, the extracts, and the helpers that hide TINs.  Why: one place for all of it.
import sys, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mt
from matplotlib.colors import LinearSegmentedColormap
from IPython.display import display, Markdown
warnings.filterwarnings('ignore')

try:
    import ctrp
except ImportError:
    sys.path.insert(0, str(Path.cwd().parent / 'src'))
from ctrp import core as M, performance as P, sensitivity as S, discovery as B
from ctrp.utils import DATA_DIR, RESULTS_DIR, load_extract

SURFACE, INK, INK2, GRID, MUTED = '#fcfcfb', '#0b0b0b', '#52514e', '#e6e5e0', '#bdbcb7'
BLUE, ORANGE = '#1f4fd8', '#eb6834'
RAMP = ['#cde2fb', '#9ec5f4', '#5598e7', '#1c5cab', '#0d366b']
plt.rcParams.update({
    'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
    'axes.edgecolor': GRID, 'axes.labelcolor': INK2, 'text.color': INK, 'xtick.color': INK2,
    'ytick.color': INK2, 'axes.grid': True, 'grid.color': GRID, 'grid.linewidth': 0.8,
    'axes.spines.top': False, 'axes.spines.right': False, 'axes.titlesize': 13,
    'axes.titleweight': 'bold', 'axes.titlelocation': 'left', 'font.size': 11, 'lines.linewidth': 2,
    'figure.dpi': 110, 'legend.frameon': False})
pct = mt.PercentFormatter(1.0, decimals=0)

def _big(x, _=None):
    for v, s in [(1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'k')]:
        if abs(x) >= v:
            return f'{x / v:.1f}'.rstrip('0').rstrip('.') + s
    return f'{x:.0f}'
big = mt.FuncFormatter(_big)

def bar_labels(ax, bars, fmt='{:,.0f}'):
    for b in bars:
        ax.text(b.get_width(), b.get_y() + b.get_height() / 2, '  ' + fmt.format(b.get_width()),
                va='center', fontsize=9, color=INK2)

# ---- example records show the real TIN (internal use only)
def who(tin):
    return f'TIN {tin}'

def table(df, **fmt):
    display(df.style.hide(axis='index').format(fmt or None, na_rep=''))

def preview(df, cols, names=None, fmt=None, n=10, note=None):
    # What: the first n rows of a table, TIN replaced, friendly column names.  Why: example records to present.
    t = df.head(n).copy()
    if 'taxpayer_tin' in t:
        t.insert(0, 'TIN', t['taxpayer_tin'])
    t = t[(['TIN'] if 'TIN' in t else []) + cols]
    if names:
        t = t.rename(columns=names)
    if note:
        display(Markdown(note))
    table(t, **(fmt or {}))

UGX = '{:,.0f}'
PCT = '{:.1%}'
ex = {f.stem.replace('bt_', ''): load_extract(f) for f in sorted(DATA_DIR.glob('bt_*.csv'))}
latest = list(ex)[-1]
D = {s: M.derive(r) for s, r in ex.items()}
d = D[latest]
d['group'] = np.where(d['adequate'], '10+ declarations', 'Fewer than 10')
ad = d[d['adequate']]
ORDER = ['Fewer than 10', '10+ declarations']
SIX = [s for s in ex if s >= '2023-09-30']
li = {q['code']: q['L'] * q['I'] for q in M.PARAMS}
PTS = M.layer2_scorecard(d)[0]                              # points per feature, latest date

# ---- optional example records pulled from the view in Hue (see the top of build_story.py)
SAMPLES = DATA_DIR / 'samples'
def sample(name):
    f = SAMPLES / name
    if not f.exists():
        return None
    s = pd.read_csv(f, dtype=str)
    s.columns = [c.split('.')[-1].lower() for c in s.columns]
    for c in ['customs_value', 'net_weight', 'supplementary_qnty', 'tax_assessed', 'original_tax_amt',
              'final_amt', 'top_up_amt', 'copies']:
        if c in s:
            s[c] = pd.to_numeric(s[c], errors='coerce')
    if 'instance_id' in s:
        s['declaration'] = s['instance_id']
    return s

def missing(name, sql):
    display(Markdown(f'*Example records not loaded yet. Run `{sql}` in Hue, save the result as '
                     f'`data/samples/{name}`, then Run All again.*'))

S1, S2, S3 = sample('story_one_taxpayer.csv'), sample('story_repeated_item.csv'), sample('story_top_up_column.csv')
print(f'{len(ex)} extracts loaded ({list(ex)[0]} to {latest}). Latest: {len(d):,} taxpayers. '
      f'Example records from the view: {sum(x is not None for x in (S1, S2, S3))} of 3 loaded.')
""")

# =================================================================================== A
md(r"""
## A. What are we trying to predict?

Customs checks a declaration by sending it to the **red** lane (physical examination) or the **yellow** lane
(documentary check). Sometimes the check finds that more tax is due, and the declaration is **topped up**.
A check that ends in a top-up is what we call a **hit**.

The model looks at each IM4 and IM7 taxpayer on a given date and ranks them by how likely it is that
**checks on their declarations in the next 6 months will find a top-up**.

Everything the model uses comes from **before** that date. The result we judge it against comes from the
6 months **after**. We repeat this at many dates, so we always test the model on a period it has never seen.

**Example records: one row per taxpayer, with what happened in the 6 months after 31 March 2026**
""")

code(r"""
# What: the outcome columns for the first 10 taxpayers of the latest extract.
raw = ex[latest]
preview(raw, ['out_entries', 'out_checked', 'out_checked_hits', 'out_top_up'],
        names={'out_entries': 'Declarations in the next 6 months', 'out_checked': 'Of which checked (red or yellow)',
               'out_checked_hits': 'Checks that found a top-up (hits)', 'out_top_up': 'Top-up found, UGX'},
        fmt={'Top-up found, UGX': UGX})
""")

md(r"""
**Across all taxpayers, at each test date**
""")

code(r"""
# What: checks and hits at each test date.  Why: shows how often checks find something.
rows = []
for s, r in ex.items():
    rows.append({'Date': s, 'Taxpayers': len(r), 'Taxpayers checked': int((r['out_checked'] > 0).sum()),
                 'Checks (red or yellow)': int(r['out_checked'].sum()), 'Hits': int(r['out_checked_hits'].sum()),
                 'Share of checks that found a top-up': r['out_checked_hits'].sum() / r['out_checked'].sum()})
table(pd.DataFrame(rows), **{'Taxpayers': '{:,}', 'Taxpayers checked': '{:,}', 'Checks (red or yellow)': '{:,}',
                             'Hits': '{:,}', 'Share of checks that found a top-up': PCT})
""")

md(r"""
**What it means for Customs.** Only about 7 to 13 checks in 100 find a top-up. Every other check costs an
officer's time and holds up a trader who had nothing wrong. If the riskiest taxpayers can be put first, each
check finds more revenue, and compliant traders are checked less.

### A2. Snapshots: the dates we test on

A **snapshot** is a date we pick to take a picture of every taxpayer. At a snapshot the model may only use
what happened **before** that date. We then look at the **6 months after** it to see whether the taxpayers
it ranked highest were the ones whose checks found top-ups.

How much history the model looks at, counting back from the snapshot:

* **3 years** for the top-up, severe top-up, amendment and tax-reduction rates. The latest year counts most
  (see D7).
* **2 years** for everything else: prices against other importers, stations, kinds of goods, and how many
  declarations a taxpayer made.
* **180 days** for "recent top-up".
""")

code(r"""
# What: a timeline of one snapshot.  Why: shows what the model may use and what it is judged on.
fig, ax = plt.subplots(figsize=(12, 2.4))
snap = pd.Timestamp('2026-03-31')
bars = [('History: 3 years (top-up, amendment and reduction rates)', snap - pd.DateOffset(years=3), snap, BLUE, 2),
        ('History: 2 years (prices, stations, goods, declarations)', snap - pd.DateOffset(years=2), snap, '#5598e7', 1),
        ('Result: the 6 months after (used only for testing)', snap, snap + pd.DateOffset(months=6), ORANGE, 0)]
for lab, a, b, c, y in bars:
    ax.barh(y, (b - a).days, left=a, color=c, height=0.6)
ax.axvline(snap, color=INK, linewidth=2); ax.text(snap, 2.55, 'snapshot: 31 Mar 2026', ha='center', fontsize=10)
ax.set_yticks([2, 1, 0], [b_[0] for b_ in bars]); ax.grid(axis='y', visible=False); ax.set_ylim(-0.5, 2.9)
ax.set_xlim(snap - pd.DateOffset(years=3, months=1), snap + pd.DateOffset(months=8))
ax.set_title('One snapshot: what the model may use, and what it is judged on')
plt.show()
""")

md(r"""
**The snapshot dates.** Snapshots fall on 31 March and 30 September each year, so the 6-month result windows
follow each other without overlapping and every test is separate.

| Data | Snapshot dates | Used for |
|---|---|---|
| Full extracts (every feature) | 30 Sep 2022, 30 Sep 2023, 31 Mar 2024, 30 Sep 2024, 31 Mar 2025, 30 Sep 2025, 31 Mar 2026 | Building and testing features; the examples in this notebook (latest: 31 Mar 2026) |
| The long run (counts per half-year since 2014) | 18 dates, 30 Sep 2017 to 31 Mar 2026 | Testing that the ranking holds over nine years; recency |
| Live | 30 Sep 2026 | The list officers receive. Its 6 months have not happened yet |

**How it works in production.** In production there is no "6 months after" yet. The model is run on a date
(for the live list, 30 September 2026) using the history before that date, in the same windows as above. The
score is its view of which taxpayers' checks are most likely to find a top-up **from that date on**. The 6
months after are only used in testing, to show that this view has held at every past snapshot. When the next
6 months have passed, the live list can be checked the same way. How often to re-run the list is to be agreed
with the Risk Officers.

---
## B. What does the data look like? (EDA)

The data comes from one view, `vw_cstm_AEO_model`, built by Data Engineering for this project. It has
**one row for every item on every declaration**, for all regimes, from November 2012. EDA (exploratory data
analysis) means looking carefully at the data before building anything, to find what is in it and what is
wrong with it.

### B1. Which regimes do we score?
""")

code(r"""
# What: the ten largest regime and procedure codes over 24 months.  Why: shows what we keep and what we leave out.
reg = pd.Series({'IM7 000': 416769, 'IM4 405': 396129, 'IM8 000': 344205, 'IM4 000': 288668, 'WT8': 181143,
                 'EX8': 134261, 'PB4': 120079, 'ES1': 115226, 'IM4 478': 72567, 'ST8': 71247}).sort_values()
kept = [k.startswith(('IM4', 'IM7')) for k in reg.index]
fig, ax = plt.subplots(figsize=(10, 3.8))
bar_labels(ax, ax.barh(reg.index, reg.values, color=[BLUE if k else MUTED for k in kept], height=0.65))
ax.xaxis.set_major_formatter(big); ax.grid(axis='y', visible=False); ax.set_xlim(0, reg.max() * 1.15)
ax.set_title('Declarations by regime and procedure, 24 months (blue = scored)')
plt.show()
""")

md(r"""
**Decision: score IM4 (home use) and IM7 (warehousing) only.** These are the regimes where duty is
assessed and paid. Transit (IM8) and export carry guarantees or suspended amounts, so a "top-up" there does
not mean the same thing.

**What it means for Customs.** The model speaks about duty-paid imports, where a top-up is real revenue that
was at risk. Transit and export risk need their own measures and are not mixed in.

### B2. Problems found in the data

Two problems would have made every count wrong if we had not caught them.

**Problem 1: the view stores some items many times.** Below is one item from March 2026 as the view holds it.
""")

code(r"""
# What: one item that the view stores many times.  Why: shows why duplicates must be removed before counting.
if S2 is None:
    missing('story_repeated_item.csv', 'sql/story/story_02_repeated_item.sql')
else:
    preview(S2, ['declaration', 'key_itm_nbr', 'assessment_dt_wid', 'hsc_cd', 'customs_value', 'final_amt', 'copies'],
            names={'declaration': 'Declaration (instance_id)', 'key_itm_nbr': 'Item', 'assessment_dt_wid': 'Date', 'hsc_cd': 'HS code',
                   'customs_value': 'Customs value, UGX', 'final_amt': 'Final tax, UGX', 'copies': 'Copies in the view'},
            fmt={'Customs value, UGX': UGX, 'Final tax, UGX': UGX})
""")

md(r"""
Every copy is identical. Across 24 months, 14,215 items are stored more than once, adding 1.48 million extra
rows (one item up to 522 times). Counting them as they are would make some taxpayers look as if they
declared hundreds of times more than they did.

**Problem 2: the column `top_up_amt` does not always hold the top-up.** Below are 10 declarations without
the top-up flag and 10 with it.
""")

code(r"""
# What: the top-up flag against top_up_amt, with the final tax beside it.  Why: shows what top_up_amt really holds.
if S3 is None:
    missing('story_top_up_column.csv', 'sql/story/story_03_top_up_column.sql')
else:
    s3 = S3.copy()
    s3['diff'] = s3['final_amt'] - s3['original_tax_amt'].fillna(s3['final_amt'])
    s3['is_final'] = np.where(s3['top_up_amt'] == s3['final_amt'], 'Yes', 'No')
    s3['is_diff'] = np.where(np.isclose(s3['top_up_amt'], s3['diff']), 'Yes', 'No')
    for flag, title in [('N', '**10 declarations WITHOUT the top-up flag**'), ('Y', '**10 declarations WITH the top-up flag**')]:
        preview(s3[s3['top_up_flg'] == flag], ['declaration', 'original_tax_amt', 'final_amt', 'diff', 'top_up_amt', 'is_final', 'is_diff'],
                names={'declaration': 'Declaration (instance_id)', 'original_tax_amt': 'Original tax (blank = not recorded)', 'final_amt': 'Final tax',
                       'diff': 'Final minus original', 'top_up_amt': 'top_up_amt', 'is_final': 'top_up_amt = final tax?',
                       'is_diff': 'top_up_amt = the increase?'},
                fmt={'Original tax (blank = not recorded)': UGX, 'Final tax': UGX, 'Final minus original': UGX, 'top_up_amt': UGX},
                note=title)
    y = s3[s3['top_up_flg'] == 'Y']
    display(Markdown(f"Without the flag: `top_up_amt` equals the final tax on {int((s3[s3['top_up_flg'] == 'N']['is_final'] == 'Yes').sum())} of 10. "
                     f"With the flag: it equals the increase on {int((y['is_diff'] == 'Yes').sum())}, the final tax on "
                     f"{int(((y['is_final'] == 'Yes') & (y['is_diff'] == 'No')).sum())}, and on "
                     f"{int((y['diff'] <= 0).sum())} the flag is set but the final tax is no higher than the original."))
""")

md(r"""
**What these columns mean.**

* `original_tax_amt` is the tax worked out when the declaration was first assessed. It is often blank when
  nothing changed.
* `final_amt` is the tax finally due.
* `top_up_flg` is Y when the declaration was marked as topped up.
* `top_up_amt` was expected to hold the extra tax from a top-up. It does not, most of the time.

**How we found out.** We compared `top_up_amt` with `final_amt` on every IM4 and IM7 declaration. On
declarations **without** the top-up flag, the two were the same 99.5% of the time: the column simply repeats
the final tax. The examples above show it. Even **with** the flag, the column sometimes holds the increase and
sometimes the whole final tax, and some flagged declarations have no increase at all.

**What "zero", "positive" and "negative" mean in the table below.** They describe the value in `top_up_amt`.
Zero is mostly declarations with no tax due at all (about a third of declarations have zero tax). Positive is
usually the final tax, which is why there are over a million "positive" amounts on unflagged declarations.
Negative amounts are rare (about 1,400) and are not used.
""")

code(r"""
# What: the flag against the value in top_up_amt, all IM4 and IM7 declarations, 24 months (EDA query).
b3 = pd.DataFrame({'top_up_amt is zero': [1254111, 770], 'top_up_amt is positive': [1024691, 99195],
                   'top_up_amt is negative': [1127, 286]}, index=['Top-up flag N', 'Top-up flag Y'])
table(b3.reset_index().rename(columns={'index': 'Declarations'}), **{c: '{:,}' for c in b3.columns})
""")

md(r"""
**The rule we wrote.** We do not read `top_up_amt` at all. A declaration counts as **topped up** only when the
flag is Y **and** the final tax is higher than the original tax. The top-up amount is the final tax minus the
original tax. Where the original tax is blank, it is taken to be the same as the final tax (nothing changed).
A tax **reduction** is a final tax lower than the original.

| What we found | Rule we wrote |
|---|---|
| Some items stored hundreds of times (the example above: 412 copies) | Keep one row per item |
| `top_up_amt` holds the final tax, not the top-up | Top-up = flag Y and final tax above original; amount = final minus original |
| Original tax blank when nothing changed | Use the final tax |
| Tax repeated on every item row of a declaration | Take tax once per declaration |
| Cancelled declarations; APC 483 dummy entries | Removed |

**What it means for Customs.** Without these rules the model would have flagged the wrong traders: those whose
records happen to be duplicated, or any trader with a large final tax. Officers would lose trust in it quickly.
These problems are also worth raising with Data Engineering, because any other report built on the view would
have the same errors.

### B3. How often do the things we measure happen?
""")

code(r"""
# What: share of declarations with each event over 24 months.  Why: top-ups are rare, which shapes every threshold.
ev = pd.Series({'Sent to red lane at some point': 0.32, 'Original tax of zero': 0.318, 'Amended': 0.112,
                'Items with preferential treatment': 336931 / (336931 + 7578855), 'Topped up': 0.042}).sort_values()
fig, ax = plt.subplots(figsize=(10, 3.0))
bar_labels(ax, ax.barh(ev.index, ev.values, color=[ORANGE if k == 'Topped up' else BLUE for k in ev.index], height=0.6), fmt='{:.1%}')
ax.xaxis.set_major_formatter(pct); ax.set_xlim(0, 0.4); ax.grid(axis='y', visible=False)
ax.set_title('Share of declarations with each event')
plt.show()
""")

md(r"""
**What we saw.** About 1 declaration in 24 is topped up. A third of declarations go to the red lane at some
point, but only a small share of those end in a top-up.

**What it means for Customs.** Because top-ups are rare, one top-up on a trader with two declarations says
much less than ten top-ups on a trader with a hundred. The model has to account for how much history each
trader has (step B5).

### B4. Prices span a huge range

**Example records: declarations priced furthest below other importers of the same goods** (from the entry
evidence the model produces for officers)
""")

code(r"""
# What: entry-level price records from the officers' evidence file.  Why: shows a price judged against peers.
ev_file = DATA_DIR / 'evidence' / 'review_2026-09-30_v2.csv'
if ev_file.exists():
    evd = pd.read_csv(ev_file, dtype={'taxpayer_tin': str, 'hsc_cd': str})
    preview(evd, ['station', 'entry_year', 'entry_num', 'hsc_cd', 'origin', 'customs_value', 'net_weight', 'declared_ugx_per_kg', 'peers_median_ugx_per_kg',
                  'importers_in_benchmark', 'price_vs_peers'],
            names={'station': 'Station', 'entry_year': 'Year', 'entry_num': 'Entry number', 'hsc_cd': 'HS code', 'origin': 'Origin', 'customs_value': 'Customs value, UGX', 'net_weight': 'Net weight, kg',
                   'declared_ugx_per_kg': 'Declared UGX per kg', 'peers_median_ugx_per_kg': 'Other importers, middle UGX per kg',
                   'importers_in_benchmark': 'Importers compared', 'price_vs_peers': 'Declared price as share of peers'},
            fmt={'Customs value, UGX': UGX, 'Net weight, kg': '{:,.0f}', 'Declared UGX per kg': UGX,
                 'Other importers, middle UGX per kg': UGX, 'Declared price as share of peers': '{:.0%}'})
else:
    display(Markdown('*Entry evidence file not found in data/evidence.*'))
""")

code(r"""
# What: percentiles of declared price per kg across all items (EDA query F3).
q = {'0.1%': 69, '1%': 227, '50%': 8362, '99%': 1077012, '99.9%': 17318352}
fig, ax = plt.subplots(figsize=(10, 1.8))
ax.plot([min(q.values()), max(q.values())], [0, 0], color=GRID, linewidth=8, solid_capstyle='round', zorder=1)
for k, v in q.items():
    ax.scatter(v, 0, s=70 if k == '50%' else 40, color=ORANGE if k == '50%' else BLUE, zorder=3)
    ax.annotate(f'{k}\nUGX {_big(v)}', (v, 0), xytext=(0, 10), textcoords='offset points', ha='center', fontsize=9, color=INK2)
ax.set_xscale('log'); ax.set_yticks([]); ax.set_ylim(-0.5, 1); ax.xaxis.set_major_formatter(big); ax.grid(axis='y', visible=False)
ax.set_title('Declared price per kg across all items (orange = the middle value)')
plt.show()
""")

md(r"""
**What we saw.** A kilogram of declared goods runs from UGX 69 to UGX 17 million. That range is real: cement
and mobile phones are both in the data.

**Decision: judge a price only against other importers of the same HS code** (and the same origin
where at least 5 importers bring it in).

**Where the benchmark comes from.** We build it ourselves from the same view. For every HS code we take all
items declared by all importers over the 2 years before the snapshot, work out each item's price per kg (and
per unit where a quantity is given), and take the middle value. Where at least 5 importers bring that HS code
from the same country, we use the middle value for that origin; otherwise the middle value for the HS code
from all origins. An HS code needs at least 5 different importers to have a benchmark at all. This is a
stand-in: the official valuation benchmarks are not in the view, and could replace it if they were added. A price below 1% of that middle value is treated as a keying error
(a weight in the wrong unit), not as undervaluation. Fuel is priced per litre with specific duties, so it is
left out of price checks.

**What it means for Customs.** A low price is only suspicious next to the same goods. Comparing like with like
means the model points officers at real undervaluation, and a typing mistake cannot make an honest trader look
like the worst undervaluer in the country. The table above is exactly what an officer receives as entry
evidence.

### B5. Most taxpayers have very little history

**Example records: the first 10 taxpayers, with how many declarations they made in 24 months**
""")

code(r"""
# What: declarations and simple rates for 10 taxpayers.  Why: shows how thin most taxpayers' history is.
preview(d, ['entries_24m', 'top_up_entry_rate_raw', 'par045_amended_entry_rate_raw', 'group'],
        names={'entries_24m': 'Declarations in 24 months', 'top_up_entry_rate_raw': 'Share topped up',
               'par045_amended_entry_rate_raw': 'Share amended', 'group': 'History'},
        fmt={'Share topped up': '{:.0%}', 'Share amended': '{:.0%}'})
""")

code(r"""
# What: share of taxpayers, declarations, tax and later hits by history.  Why: the most important EDA finding.
share = pd.DataFrame({'Taxpayers': d.groupby('group').size(), 'Declarations': d.groupby('group')['entries_24m'].sum(),
                      'Original tax': d.groupby('group')['total_original_tax'].sum(),
                      'Hits (6 months after)': d.groupby('group')['out_checked_hits'].sum()})
share = share / share.sum()
fig, ax = plt.subplots(figsize=(10, 3.0))
left = np.zeros(len(share.columns))
for g, colr in zip(ORDER, [ORANGE, BLUE]):
    vals = share.loc[g].values
    ax.barh(share.columns[::-1], vals[::-1], left=left[::-1], color=colr, label=g, height=0.55, edgecolor=SURFACE, linewidth=2)
    for i, (v, l) in enumerate(zip(vals[::-1], left[::-1])):
        if v > 0.06:
            ax.text(l + v / 2, i, f'{v:.0%}', ha='center', va='center', color='white', fontsize=10, fontweight='bold')
    left += vals
ax.xaxis.set_major_formatter(pct); ax.set_xlim(0, 1); ax.grid(axis='y', visible=False)
ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.42), ncol=2)
ax.set_title(f"{share.loc['Fewer than 10', 'Taxpayers']:.0%} of taxpayers have fewer than 10 declarations in 24 months")
plt.show()
""")

code(r"""
# What: amendment rate by number of declarations.  Why: with few declarations a rate is 0% or 100% from one event.
bins = [0, 1, 2, 3, 5, 9, 19, 49, 99, 199, 10**9]
names = ['1', '2', '3', '4-5', '6-9', '10-19', '20-49', '50-99', '100-199', '200+']
b_ = pd.cut(d['entries_24m'], bins=bins, labels=names)
qq = d.groupby(b_, observed=True)['par045_amended_entry_rate_raw'].quantile([0.1, 0.5, 0.9]).unstack()
xs = np.arange(len(qq)); cols_ = [ORANGE if i < 5 else BLUE for i in xs]
fig, ax = plt.subplots(figsize=(10, 3.4))
ax.vlines(xs, qq[0.1], qq[0.9], color=cols_, linewidth=7, alpha=0.35)
ax.scatter(xs, qq[0.5], color=cols_, s=55, zorder=3)
ax.set_xticks(xs, qq.index); ax.yaxis.set_major_formatter(pct); ax.set_ylim(-0.02, 1.02); ax.grid(axis='x', visible=False)
ax.set_xlabel('declarations in 24 months')
ax.set_title('Share of declarations amended, per taxpayer: dot = middle value, bar = middle 80%')
plt.show()
""")

md(r"""
**What we saw.** Most taxpayers declare fewer than 10 times in two years, many of them only once (often a
single vehicle import). They make up a small share of declarations, tax and hits. With so few declarations,
one amendment or one top-up swings their rate from 0% to 50% or 100%. Before any fix, these small traders
filled most of the HIGH band.

**Decision: two protections for taxpayers with little history.**

1. **Credibility weighting** (shown in D4): the fewer declarations a taxpayer has, the less the model relies
   on their own rates and the more it leans on the average of all taxpayers. It can only lower a rate.
2. **The 10-declaration line**: a taxpayer with fewer than 10 declarations in the last 2 years is marked
   **"limited history"** on the officers' list, so officers know the score rests on little evidence. The line
   also decides who is compared with a peer group, and which Track B model applies (regular or small trader).
   It does not change any points: that is the job of credibility weighting.

**What it means for Customs.** Without these, officers would spend checks on one-off importers whose "high
rate" is a single event, and the large traders who carry most of the tax would be pushed down the list.

#### What if the line were 10 declarations in 5 years?

Counting over a longer period would call more taxpayers "regular". We tested it with the long run, which
counts every taxpayer's declarations per half-year since 2014.
""")

code(r"""
# What: small taxpayers under a 2-, 3- and 5-year count, at 31 Mar 2026.  Why: tests widening the 10-declaration line.
import glob
files = sorted(glob.glob(str(DATA_DIR / 'long_run' / 'long_run_20*.csv')))
if not files:
    display(Markdown('*The long-run files are not in data/long_run, so this test cannot run here.*'))
else:
    lr = pd.concat([pd.read_csv(f, dtype={'taxpayer_tin': str}, usecols=['taxpayer_tin', 'period_end', 'entries']) for f in files])
    lr['period_end'] = pd.to_datetime(lr['period_end'])
    snap = pd.Timestamp(latest)
    def count(years):
        q = lr[(lr['period_end'] > snap - pd.DateOffset(years=years)) & (lr['period_end'] <= snap)]
        return q.groupby('taxpayer_tin')['entries'].sum()
    t = raw.set_index('taxpayer_tin')
    for y in (3, 5):
        t[f'e{y}'] = count(y).reindex(t.index).fillna(0)
    rows = []
    for lab, col_ in [('10 in 2 years (now)', 'entries_24m'), ('10 in 3 years', 'e3'), ('10 in 5 years', 'e5')]:
        small = t[col_] < 10
        rows.append({'Line': lab, 'Taxpayers marked limited history': int(small.sum()), 'Share of all taxpayers': small.mean()})
    table(pd.DataFrame(rows), **{'Taxpayers marked limited history': '{:,}', 'Share of all taxpayers': '{:.0%}'})
    mv = (t['entries_24m'] < 10) & (t['e5'] >= 10)
    m_ = t[mv]
    display(Markdown(f"**Who would move.** {mv.sum():,} taxpayers would stop being 'limited history'. In the last 2 years they "
                     f"made {m_['entries_24m'].median():.0f} declarations each (middle value); over 5 years, {m_['e5'].median():.0f}. "
                     f"Over the last 3 years, the period their top-up rates are built on, {(m_['e3'] < 10).mean():.0%} of them "
                     f"still have fewer than 10. Together they gave {m_['out_checked_hits'].sum() / t['out_checked_hits'].sum():.1%} "
                     f"of the hits in the 6 months after."))
    m_ = m_.reset_index()
    preview(m_, ['entries_24m', 'e3', 'e5'], names={'entries_24m': 'Declarations, last 2 years',
            'e3': 'Declarations, last 3 years', 'e5': 'Declarations, last 5 years'},
            fmt={'Declarations, last 3 years': '{:,.0f}', 'Declarations, last 5 years': '{:,.0f}'},
            note='**Example records: 10 taxpayers who would move**')
""")

md(r"""
**What we saw.** A 5-year count would move about 4,300 taxpayers (7% of all) out of "limited history". But the
line is there to say whether a taxpayer's **rates** can be trusted, and those rates are built on the last 3
years with the latest year counting most. For more than half of the taxpayers who would move, those 3 years
still hold fewer than 10 declarations: they look regular on paper, but their rates still rest on a handful
of declarations, much of it old.

**Our view.** If the line is widened, it should count the same years the rates use: **3 years**. That moves
about 2,000 taxpayers and keeps the line honest. A 5-year line would also give more taxpayers peer groups and
the regular-trader Track B model, so Track B would need to be tested again. This is open for discussion.

### B6. Checks found less after March 2024
""")

code(r"""
# What: share of checks that found a top-up, 18 dates since 2017.  Why: the base the model is judged against moves.
m = pd.read_excel(RESULTS_DIR / 'CTRP_performance_since_2017.xlsx', sheet_name='Measures')
x = pd.to_datetime(m['Snapshot'])
fig, ax = plt.subplots(figsize=(10, 3.0))
ax.plot(x, m['Per check: hit rate, everyone'], color=ORANGE, marker='o')
ax.axvspan(pd.Timestamp('2024-03-31'), x.max() + pd.Timedelta(days=60), color=GRID, alpha=0.6)
ax.yaxis.set_major_formatter(pct); ax.set_ylim(0, 0.16)
ax.set_title('Share of red and yellow checks that found a top-up (shaded: after March 2024)')
plt.show()
""")

md(r"""
**What we saw.** From March 2024, checks in general found less: from 11 to 13 in 100 down to 7 or 8.

**Decision.** Each date is judged against its own level, so the drop does not distort the results.
What changed in March 2024 is a question for the Risk Officers.

**What it means for Customs.** Something changed in how checks are chosen or recorded, and it affects every
selectivity measure, not only this model. Knowing the cause matters for how results are read from 2024 on.

---
## C. How does a column become a feature?

This is the most important idea in the notebook.

* **A column** is a raw value stored in the view for one item on one declaration. For example `top_up_flg`
  (Y or N) or `final_amt` (the final tax).
* **A feature** is one number per taxpayer that the model calculates from several columns, across all of the
  taxpayer's declarations over a period. For example "the share of this taxpayer's declarations that were
  topped up in the last 3 years".

None of the model's features exists as a column in the view. Each one is built in steps: clean the rows,
combine the columns on each declaration, then summarise all of a taxpayer's declarations into one number.

### C1. The columns the model reads

**Example records: the first 10 item rows of one taxpayer, as the view stores them**
""")

code(r"""
# What: raw item rows from the view for the example taxpayer.  Why: the starting point of every feature.
if S1 is None:
    missing('story_one_taxpayer.csv', 'sql/review/story_01_one_taxpayer.sql')
else:
    preview(S1, ['declaration', 'key_itm_nbr', 'assessment_dt_wid', 'regime_cd', 'hsc_cd', 'gds_org_cty', 'customs_value',
                 'net_weight', 'original_tax_amt', 'final_amt', 'top_up_flg', 'amendment_flg', 'clearance_station_cd',
                 'is_red_flg', 'is_yellow_flg'],
            names={'declaration': 'Declaration (instance_id)', 'key_itm_nbr': 'Item', 'assessment_dt_wid': 'Date', 'regime_cd': 'Regime',
                   'hsc_cd': 'HS code', 'gds_org_cty': 'Origin', 'customs_value': 'Customs value', 'net_weight': 'Weight, kg',
                   'original_tax_amt': 'Original tax', 'final_amt': 'Final tax', 'top_up_flg': 'Top-up flag',
                   'amendment_flg': 'Amended', 'clearance_station_cd': 'Station', 'is_red_flg': 'Red', 'is_yellow_flg': 'Yellow'},
            fmt={'Customs value': UGX, 'Weight, kg': '{:,.0f}', 'Original tax': UGX, 'Final tax': UGX})
""")

md(r"""
The view has many more columns; the model reads 24 of them.

| Column | What it is | Used for |
|---|---|---|
| `instance_id`, `key_itm_nbr` | Declaration and item number | Removing repeated items; counting declarations |
| `taxpayer_tin`, `assessment_dt_wid` | Whose declaration, and the date | Grouping by taxpayer; the history window and the 3 years |
| `regime_cd`, `decl_status`, `cpc_cd`, `extended_proc_cd` | Regime, status, procedure codes | Keeping IM4 and IM7, dropping cancelled; exemption codes |
| `original_tax_amt`, `final_amt`, `top_up_flg`, `tax_assessed` | Tax first declared, final tax, top-up flag, tax per item | Top-ups, severe top-ups, tax reduced, duty rate |
| `amendment_flg` | Whether the declaration was amended | Amendments |
| `hsc_cd`, `gds_org_cty`, `customs_value`, `net_weight`, `supplementary_qnty` | Goods code, origin, value, weight, quantity | Price against other importers; kinds of goods |
| `clearance_station_cd` | Station | Station movement |
| `is_red_flg`, `is_yellow_flg` | Lanes | Only to measure the result (checks and hits); never an input |
| `pay_status`, `preferential_treatment_flag`, `consignee_tin` | Payment, preference, consignee | Tax unpaid and preference (Track B); consignee checked and dropped |

### C2. One taxpayer, from columns to points

Here we follow one real taxpayer and build one feature for them by hand: **PAR_045T, the
share of their declarations that were topped up**. Every other feature is built the same way.
""")

code(r"""
# What: one taxpayer's PAR_045T built by hand, in plain steps.  Why: shows that a feature is calculated, not read from a column.
SNAP = pd.Timestamp(latest)
raw = ex[latest]
if S1 is not None:
    pick = raw.index[raw['taxpayer_tin'] == S1['taxpayer_tin'].iloc[0]][0]
else:
    pick = raw[(raw['entries_24m'].between(25, 60)) & (raw['y1_topped_up'] > 0) & (raw['y2_topped_up'] > 0)
               & (raw['y1_entries'] > 0) & (raw['y3_entries'] > 0) & (raw['out_checked'] > 0)].index[0]
r, dd = raw.loc[pick], d.loc[pick]
name = who(r['taxpayer_tin'])
n1, n2, n3 = (int(r[f'y{k}_entries']) for k in (1, 2, 3))
t1, t2, t3 = (int(r[f'y{k}_topped_up']) for k in (1, 2, 3))

if S1 is not None:
    s1 = S1[(S1['decl_status'] != 'Cancelled') & (S1['cpc_cd'].fillna('') != '483')].copy()
    s1['date'] = pd.to_datetime(s1['assessment_dt_wid'].str[:8], format='%Y%m%d')
    before = len(s1)
    s1 = s1.sort_values('date').drop_duplicates(['instance_id', 'key_itm_nbr'])
    g = s1.groupby('declaration').agg(date=('date', 'max'), items=('key_itm_nbr', 'count'),
                                      original=('original_tax_amt', 'max'), final=('final_amt', 'max'),
                                      flag=('top_up_flg', 'max'), red=('is_red_flg', 'max'), yellow=('is_yellow_flg', 'max')).reset_index()
    g['original'] = g['original'].fillna(g['final'])
    g['topped'] = np.where((g['flag'] == 'Y') & (g['final'] > g['original']), 'Yes', 'No')
    g = g[g['date'] <= SNAP].sort_values('date')
    display(Markdown(f'**Step 1. Start from the rows in the view.** {name} has {before} item rows in the 3 years before {latest}. '
                     f'{before - len(s1)} are repeated copies and are removed. The rest are grouped into {len(g)} declarations.'))
    t = g.head(10).copy(); t['date'] = t['date'].dt.date
    table(t[['declaration', 'date', 'items', 'original', 'final', 'flag', 'topped']].rename(columns={
        'declaration': 'Declaration (instance_id)', 'date': 'Date', 'items': 'Items', 'original': 'Original tax', 'final': 'Final tax',
        'flag': 'Top-up flag', 'topped': 'Counted as topped up?'}), **{'Original tax': UGX, 'Final tax': UGX})
    display(Markdown('A declaration is counted as topped up only when the flag is Y **and** the final tax is higher than the original.'))
else:
    display(Markdown(f'**Step 1. Start from the rows in the view.** The SQL takes every item row of {name}, removes repeated '
                     f'copies, groups the items into declarations, and marks each declaration as topped up or not '
                     f'(flag Y and final tax higher than the original). *To see these rows, load the example records for C1.*'))

display(Markdown(f'**Step 2. Count, year by year.** Counting back from {latest}:'))
table(pd.DataFrame({'Year': ['Last 12 months', '12 to 24 months before', '24 to 36 months before'],
                    'Declarations': [n1, n2, n3], 'Topped up': [t1, t2, t3]}))

rec = dd['top_up_entry_rate_raw']; used = dd['top_up_entry_rate']
p = next(p for p in M.PARAMS if p['code'] == 'PAR_045T')
pts_ = PTS.loc[pick, 'PAR_045T']; mx = li['PAR_045T'] / sum(li.values()) * 100
display(Markdown(f'''**Step 3. Recent years count more.** The last year counts in full, the year before counts half, the year before
that a quarter. On that basis about **{rec:.0%}** of {name}'s declarations were topped up.

**Step 4. Allow for how much history there is.** {name} made {r['entries_24m']:.0f} declarations in the last 2 years, a
fair amount but not a lot, so the model trusts most of this rate but not all of it: the rate it uses is **{used:.0%}**.

**Step 5. Turn the rate into points.** PAR_045T starts giving points above {p['zero_at']:.0%} and gives its full
{mx:.0f} points at {p['one_at']:.0%} or more. {used:.0%} is a small part of the way up, so {name} gets
**{pts_:.1f} of {mx:.0f} points** from this feature.

**Step 6. Add up.** The same is done for the other seven features, and the points are added to give the score.'''))
""")

md(r"""
**What it means for Customs.** When the officers asked for "entries with a top-up over total entries", that
request was the start of a feature, not the feature. The data team had to decide what counts as a top-up (the
flag alone is not enough), remove repeated rows, choose the period, weight recent years, and protect taxpayers
with little history. Each of these choices changes who ends up at the top of the list. When we ask for new
data, the same work follows before it can be used.

### C3. The Track A features, one by one

Track A is the scorecard built on each taxpayer's own compliance history. It has eight features, all from
parameters agreed with the officers. For each one: the columns it uses, how it is built, why it is in, and
10 example taxpayers.
""")

FEATS = [
    ('PAR_045T', 'Declarations topped up', 'top_up_entry_rate',
     '`top_up_flg`, `original_tax_amt`, `final_amt`',
     'Share of the taxpayer\'s declarations with the flag Y and a final tax above the original, over 3 years',
     'The officers\' own rule, and the strongest single sign of future top-ups.',
     'Traders who were often found to under-declare are checked first, where checks pay most.',
     ['y1_entries', 'y1_topped_up', 'y2_entries', 'y2_topped_up', 'y3_entries', 'y3_topped_up']),
    ('PAR_077', 'Severe top-ups', 'par077_severe_top_up_rate',
     '`top_up_flg`, `original_tax_amt`, `final_amt`',
     'Share of declarations whose top-up was 30% or more of the final tax',
     'A large top-up means a large part of the tax was missing, not a small correction.',
     'Separates traders with big gaps from those with small adjustments, so the biggest revenue risks rise.',
     ['y1_entries', 'y1_severe', 'y2_entries', 'y2_severe']),
    ('PAR_045', 'Declarations amended', 'par045_amended_entry_rate',
     '`amendment_flg`',
     'Share of declarations that were amended',
     'Frequent amendments point to declarations that are often wrong the first time.',
     'Traders whose declarations keep changing get a closer look, even when no top-up was raised.',
     ['y1_entries', 'y1_amended', 'y2_entries', 'y2_amended']),
    ('PAR_048', 'Top-ups as a share of tax', 'par048_top_up_share_final',
     '`original_tax_amt`, `final_amt`, `top_up_flg`',
     'Total top-ups divided by total final tax',
     'Measures how much money was missing, not just how often.',
     'Weighs the size of past under-declaration in shillings.',
     ['total_top_up', 'total_original_tax']),
    ('PAR_076', 'Value below benchmark', 'par076_shortfall_share',
     '`customs_value`, `net_weight`, `supplementary_qnty`, `hsc_cd`, `gds_org_cty`',
     'How far the taxpayer\'s prices fall below the middle price other importers declare for the same goods and origin, as a share of their value',
     'Catches undervaluation even where no check ever found it.',
     'Points officers at traders who declare cheaper than everyone else for the same goods.',
     ['items_benchmarked', 'par076_low_price_item_rate']),
    ('PAR_066', 'Tax reduced after assessment', 'par066_negative_top_up_rate',
     '`original_tax_amt`, `final_amt`',
     'Share of declarations whose final tax ended below the original',
     'Reductions after assessment deserve a look: they lower revenue.',
     'Repeated reductions for one trader become visible.',
     ['y1_entries', 'y1_tax_reduced', 'y2_entries', 'y2_tax_reduced']),
    ('PAR_105', 'Recent top-up', 'par105_top_up_180d',
     '`top_up_flg`, `assessment_dt_wid`',
     'Whether the taxpayer had a top-up in the last 180 days (yes or no)',
     'Recent behaviour says more about the next months than old behaviour.',
     'A trader caught recently stays in view for the next six months.',
     ['par105_days_since_last_top_up']),
    ('PAR_023', 'Station movement', 'par023_station_spread',
     '`clearance_station_cd`',
     'Share of declarations cleared away from the taxpayer\'s main station',
     'Moving between stations can be a way to avoid officers who know the trader.',
     'Shows traders who spread their declarations across stations.',
     ['stations_used_24m', 'main_station_share']),
]
NAMES = {'entries_24m': 'Declarations (24 months)',
         'y1_entries': 'Declarations, last year', 'y2_entries': 'Declarations, year before', 'y3_entries': 'Declarations, 2 years before',
         'y1_topped_up': 'Topped up, last year', 'y2_topped_up': 'Topped up, year before', 'y3_topped_up': 'Topped up, 2 years before',
         'y1_severe': 'Severe, last year', 'y2_severe': 'Severe, year before', 'y1_amended': 'Amended, last year',
         'y2_amended': 'Amended, year before', 'y1_tax_reduced': 'Tax reduced, last year', 'y2_tax_reduced': 'Tax reduced, year before',
         'total_top_up': 'Top-ups, UGX', 'total_original_tax': 'Original tax, UGX', 'items_benchmarked': 'Items compared with peers',
         'par076_low_price_item_rate': 'Share of items under half the peer price', 'par105_days_since_last_top_up': 'Days since last top-up',
         'stations_used_24m': 'Stations used', 'main_station_share': 'Share at main station'}
for code_, label, col, cols, how, why, customs, inputs in FEATS:
    md(f"""
#### {code_} {label}

| | |
|---|---|
| **Columns used** | {cols} |
| **How it is built** | {how} |
| **Why it is in** | {why} |
| **What it means for Customs** | {customs} |

**Example records: 10 taxpayers.** The first 5 get points for this feature (their value is above where
points start); the last 5 do not. Read each row from the counts the SQL builds, to the feature, to its points.
""")
    code(f"""
# What: 10 example taxpayers for {code_}: the inputs from the SQL, the feature, and its points.
code_, col_, inputs_ = '{code_}', '{col}', {inputs!r}
pool_ = d[d['entries_24m'] >= 5]                       # 5 taxpayers who get points for it, 5 who do not
base_ = d.loc[sorted(list(pool_.index[PTS.loc[pool_.index, code_] > 0][:5]) + list(pool_.index[PTS.loc[pool_.index, code_] == 0][:5]))].copy()
base_['points'] = PTS.loc[base_.index, code_]
base_['gets'] = np.where(base_['points'] > 0, 'Yes', 'No')
base_ = base_.sort_values(['gets', 'points'], ascending=[False, False])
mx_ = li[code_] / sum(li.values()) * 100
names_ = dict({NAMES!r})
names_.update({{col_ + '_raw': 'Feature before small-history weighting', col_: 'Feature used',
               'points': f'Points (most {{mx_:.0f}})', 'gets': 'Gets points for this feature?'}})
cols_ = ['gets', 'entries_24m'] + inputs_ + ([col_ + '_raw'] if col_ + '_raw' in base_ else []) + [col_, 'points']
fmt_ = {{names_[c]: '{{:,.0f}}' for c in cols_ if c in names_ and c not in (col_, col_ + '_raw', 'points', 'gets',
                                                                          'par076_low_price_item_rate', 'main_station_share')}}
fmt_.update({{names_[c]: '{{:.1%}}' for c in (col_, col_ + '_raw', 'par076_low_price_item_rate', 'main_station_share') if c in cols_}})
if code_ == 'PAR_105':
    fmt_[names_[col_]] = '{{:.0f}}'
fmt_[names_['points']] = '{{:.1f}}'
preview(base_, [c for c in cols_ if c in base_], names=names_, fmt=fmt_)
""")

md(r"""
Code: the counts are built in `src/ctrp/sql/features_outcomes.sql`; recency, credibility weighting and points
in `src/ctrp/core.py` (`apply_recency`, `derive`, `layer2_scorecard`).

### C4. The 20 agreed parameters: where each one stands

| Status | Parameters |
|---|---|
| **Scored: 7 parameters, 8 features** | PAR_045 (amendments, and the officers' top-up rule PAR_045T), PAR_077, PAR_048, PAR_076, PAR_066, PAR_105, PAR_023 |
| **Built, waiting for data pulls (2)** | PAR_067 unit value reduced (price against the taxpayer's own history); PAR_053 tax forgone through exemptions |
| **Need data that is not in the view (11)** | See the table below |

| Parameter | What it needs | Why it is not available | What it would add for Customs |
|---|---|---|---|
| PAR_012 Original vs final declaration | Earlier versions of each declaration | The view holds the final version only | See what traders changed between first and final declaration |
| PAR_016 Misclassification | HS changes between versions, or the misdeclaration flag | Neither is in the view | Point officers to traders whose goods were moved to a lower-duty HS code |
| PAR_054 Procedure codes amended | Procedure code changes between versions | Final version only | Point officers to switches to procedures that pay less |
| PAR_096 HS changes that lowered duty | HS changes between versions | Final version only | Measure the duty lost through reclassification |
| PAR_051 Preferential declarations amended | Declaration versions | Final version only (use of preference is shown) | Point officers to preference claims that had to be corrected |
| PAR_015 Undervaluation risk | Box 45 adjustment rate | Box 45 not in the view | Use the adjustments valuation already makes |
| PAR_075 Customs vs statistical value | Box 46 statistical value | Box 46 not in the view | Compare declared value with the statistical value |
| PAR_039, PAR_040 Penalties (number, value) | Penalty and seizure records | Separate system | Add offences found outside top-ups |
| PAR_078, PAR_173 Agent parameters | Agent TIN | Belongs to the Agent model | Bring the clearing agent's record into the picture |

**What it means for Customs.** None was dropped by choice. Each row is a precise request we can make to Data
Engineering. Several of them (misclassification, procedure changes, box 45 and 46) cover risks that top-ups
alone cannot show, so adding them would widen what the model can find.

---
## D. How did we choose and shape each feature?

Choosing a feature is only half the work. Each one also needs a **scale**: the level where it starts to count
(below it, 0 points) and the level where it gives full points. This part shows the evidence behind those
choices.

### D1. Where each feature sits, against its thresholds
""")

code(r"""
# What: distribution of each feature (taxpayers with 10+ declarations) with its thresholds.
fig, axes = plt.subplots(2, 4, figsize=(14, 5.8))
for ax, p in zip(axes.flat, M.PARAMS):
    x = ad[p['col']].dropna()
    top = max(p['one_at'] * 1.8, x.quantile(0.98))
    ax.hist(x.clip(upper=top), bins=40, color=BLUE, edgecolor=SURFACE, linewidth=0.5)
    ax.axvline(p['zero_at'], color=INK2, linestyle=':', linewidth=1.2)
    ax.axvline(p['one_at'], color=INK2, linestyle='--', linewidth=1.2)
    ax.set_title(f"{p['code']} {p['label']}", fontsize=10)
    ax.text(0.98, 0.95, f"above minimum {(x > p['zero_at']).mean():.0%}\nat maximum {(x >= p['one_at']).mean():.0%}",
            transform=ax.transAxes, ha='right', va='top', fontsize=9, color=INK2)
    ax.yaxis.set_major_formatter(big); ax.tick_params(labelsize=8); ax.grid(axis='x', visible=False)
fig.suptitle('Each feature, taxpayers with 10+ declarations (dotted = points start, dashed = full points)',
             x=0.01, ha='left', fontweight='bold')
plt.tight_layout(); plt.show()
""")

md(r"""
**How to read it.** Each panel shows how many taxpayers have each value. Taxpayers to the left of the dotted
line get no points for that feature; to the right of the dashed line they get full points.

### D2. PAR_045T: full points at 40%, not 10%

The officers first proposed full points when 10% of declarations were topped up. We tested both.

**Example records: 10 taxpayers between 10% and 40% topped up, and their points under each setting**
""")

code(r"""
# What: points for PAR_045T at 10% and at 40% for 10 example taxpayers.  Why: shows why 10% stops ranking.
p = next(p for p in M.PARAMS if p['code'] == 'PAR_045T'); mx = li['PAR_045T'] / sum(li.values()) * 100
e = ad[ad['top_up_entry_rate'].between(0.10, 0.40)].head(10).copy()
e['p10'] = ((e['top_up_entry_rate'] - p['zero_at']) / (0.10 - p['zero_at'])).clip(0, 1) * mx
e['p40'] = ((e['top_up_entry_rate'] - p['zero_at']) / (0.40 - p['zero_at'])).clip(0, 1) * mx
preview(e, ['entries_24m', 'top_up_entry_rate', 'p10', 'p40'],
        names={'entries_24m': 'Declarations', 'top_up_entry_rate': 'Share topped up', 'p10': 'Points if full at 10%',
               'p40': 'Points if full at 40% (adopted)'},
        fmt={'Share topped up': PCT, 'Points if full at 10%': '{:.1f}', 'Points if full at 40% (adopted)': '{:.1f}'})
""")

code(r"""
# What: the two settings over the six test dates.
def run(one_at):
    out = []
    with S.settings(levels={'PAR_045T': dict(one_at=one_at)}):
        for s in SIX:
            raw_ = ex[s]; dd_ = M.derive(raw_); total = M.layer2_scorecard(dd_)[0].sum(axis=1)
            hi = total.round().map(M.band_of).isin(['HIGH', 'VERY HIGH'])
            out.append(((dd_.loc[dd_['adequate'], 'top_up_entry_rate'] >= one_at).mean(), hi.mean(),
                        raw_.loc[hi, 'out_checked_hits'].sum() / raw_.loc[hi, 'out_checked'].sum(),
                        P.per_check(raw_, total.to_numpy())['Per check: ROC AUC']))
    return np.mean(out, axis=0)
t = pd.DataFrame([('10% (officers\' first proposal)', *run(0.10)), ('40% (adopted)', *run(0.40))],
                 columns=['Full points at', 'Regular traders at full points', 'Taxpayers in HIGH and above',
                          'Checks in HIGH and above that found a top-up', 'Ranking quality (0.50 = chance)'])
table(t, **{'Regular traders at full points': '{:.0%}', 'Taxpayers in HIGH and above': '{:.0%}',
            'Checks in HIGH and above that found a top-up': '{:.0%}', 'Ranking quality (0.50 = chance)': '{:.3f}'})
""")

md(r"""
**What we saw.** With full points at 10%, a trader topped up on 12% of declarations and one topped up on 35%
get the same points: the score cannot tell them apart. About 4 in 10 regular traders hit full points.

**Decision: full points at 40%; points still start at the officers' 3%.**

**What it means for Customs.** At 10%, HIGH and above would grow from about 8% to about 19% of all taxpayers,
and checks on them would find a top-up 32 times in 100 instead of 40. Officers would be asked to check more
than twice as many traders and would find less per check.

### D3. PAR_048: divide by final tax, not original tax

**Example records: taxpayers whose original tax was very small**
""")

code(r"""
# What: 10 taxpayers with a tiny original tax: the old ratio against the new share.  Why: the old ratio explodes.
e = d[(d['total_top_up'] > 0)].sort_values('total_original_tax').head(10).copy()
preview(e, ['total_original_tax', 'total_top_up', 'par048_top_up_ratio', 'par048_top_up_share_final'],
        names={'total_original_tax': 'Original tax, UGX', 'total_top_up': 'Top-ups, UGX',
               'par048_top_up_ratio': 'Top-ups / original tax (old)', 'par048_top_up_share_final': 'Top-ups / final tax (adopted)'},
        fmt={'Original tax, UGX': UGX, 'Top-ups, UGX': UGX, 'Top-ups / original tax (old)': '{:,.1f}',
             'Top-ups / final tax (adopted)': '{:.0%}'})
""")

code(r"""
# What: the two measures across all taxpayers.
rr = d[['par048_top_up_ratio', 'total_original_tax', 'group']].dropna()
rr = rr[rr['par048_top_up_ratio'] > 0]
fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
for g_, colr in zip(ORDER, [ORANGE, BLUE]):
    s_ = rr[rr['group'] == g_]
    axes[0].scatter(s_['total_original_tax'].clip(lower=1), s_['par048_top_up_ratio'], s=8, alpha=0.35, color=colr, label=g_, linewidths=0)
axes[0].set_xscale('log'); axes[0].set_yscale('log')
axes[0].set_xlabel('original tax, UGX'); axes[0].set_title('Over original tax: explodes when the tax is tiny', fontsize=12)
axes[0].legend(loc='lower left')
f = rr['par048_top_up_ratio'] / (1 + rr['par048_top_up_ratio'])
axes[1].hist(f, bins=40, color=BLUE, edgecolor=SURFACE, linewidth=0.5)
axes[1].xaxis.set_major_formatter(pct); axes[1].yaxis.set_major_formatter(big); axes[1].grid(axis='x', visible=False)
axes[1].set_title('Over final tax: always between 0 and 100%', fontsize=12)
plt.tight_layout(); plt.show()
""")

md(r"""
**What we saw.** When the original tax is tiny, dividing by it gives absurd numbers: a declaration with UGX 29
of original tax gave a ratio of 4,399. Dividing by the final tax keeps the same order of taxpayers but always
gives a share between 0 and 100%.

**Decision: PAR_048 = top-ups as a share of final tax.** The officers' 6% and 33% become 5.7% and
24.8% on the new measure, so their intent is kept.

**What it means for Customs.** A trader who declared almost no tax and was topped up a little would otherwise
look like the worst offender in the country. The new measure keeps attention on real money.

### D4. Small history: credibility weighting

**Example records: taxpayers with few and with many declarations, before and after weighting**
""")

code(r"""
# What: PAR_045T before and after weighting for small and large traders.  Why: shows who the protection affects.
e = pd.concat([d[(d['entries_24m'] <= 3) & (d['top_up_entry_rate_raw'] > 0)].head(5),
               d[(d['entries_24m'] >= 100) & (d['top_up_entry_rate_raw'] > 0)].head(5)])
e['kept'] = e['entries_24m'] / (e['entries_24m'] + M.SHRINK_K)
preview(e, ['entries_24m', 'top_up_entry_rate_raw', 'kept', 'top_up_entry_rate'],
        names={'entries_24m': 'Declarations', 'top_up_entry_rate_raw': 'Share topped up (own record)',
               'kept': 'How much of their own record is used', 'top_up_entry_rate': 'Share the model uses'},
        fmt={'Share topped up (own record)': PCT, 'How much of their own record is used': '{:.0%}', 'Share the model uses': PCT})
""")

code(r"""
# What: PAR_045T before and after weighting, every taxpayer with a top-up.
pp = d[d['top_up_entry_rate_raw'] > 0]
fig, ax = plt.subplots(figsize=(10, 3.8))
ax.scatter(pp['entries_24m'], pp['top_up_entry_rate_raw'], s=7, color=MUTED, alpha=0.6, linewidths=0, label='before')
ax.scatter(pp['entries_24m'], pp['top_up_entry_rate'], s=7, color=BLUE, alpha=0.6, linewidths=0, label='after')
ax.set_xscale('log'); ax.yaxis.set_major_formatter(pct); ax.xaxis.set_major_formatter(big)
ax.axhline(0.40, color=INK2, linestyle='--', linewidth=1); ax.text(1.1, 0.42, 'full points (40%)', fontsize=9, color=INK2)
ax.set_xlabel('declarations in 24 months'); ax.legend(loc='upper right', markerscale=3)
ax.set_title('PAR_045T per taxpayer, before and after weighting')
plt.show()
""")

md(r"""
**What we are doing, in plain words.** A taxpayer with only a few declarations has not shown us much. One
top-up on 2 declarations looks like a 50% rate, but it is one event. So for taxpayers with little history, the
model does not take their own rate at face value: it pulls it towards the rate of all taxpayers. The fewer
declarations, the harder the pull. Taxpayers with a long record keep almost all of their own rate.

Two rules keep it fair:

* It can only **lower** a rate, never raise it. A clean small trader never picks up risk from other people.
* It changes nothing for a taxpayer whose rate is already at or below the average.

| Declarations in 2 years | How much of their own record the model uses |
|---|---|
| 1 | about a tenth |
| 2 | about a sixth |
| 10 | half |
| 40 | four fifths |
| 100 | nine tenths |

**Decision.** We tested it: without it, almost half of the hits in the top 5% are lost, because the top fills
with one-off importers. Pulling harder lowers the results at the top. The setting above was the best balance.

**What it means for Customs.** A one-off importer with a single top-up is no longer treated as a habitual
offender, and a clean small trader is never given risk they did not show. Large traders with a long record
barely move. Checks go where the evidence is strongest, and small traders are treated fairly.

### D5. Do some features measure the same thing?
""")

code(r"""
# What: how closely the eight features move together (10+ declarations).
cols = [p['col'] for p in M.PARAMS]; labels = [p['code'] for p in M.PARAMS]
cm = ad[cols].astype(float).corr(method='spearman')
fig, ax = plt.subplots(figsize=(7, 5.6))
im = ax.imshow(cm.values, cmap=LinearSegmentedColormap.from_list('div', ['#e34948', '#f0efec', BLUE]), vmin=-1, vmax=1)
ax.set_xticks(range(8), labels, rotation=45, ha='right', fontsize=9); ax.set_yticks(range(8), labels, fontsize=9); ax.grid(False)
for i in range(8):
    for j in range(8):
        v = cm.values[i, j]
        ax.text(j, i, f'{v:.2f}', ha='center', va='center', fontsize=9, color='white' if abs(v) > 0.6 else INK)
fig.colorbar(im, ax=ax, shrink=0.8); ax.set_title('How closely the features move together (1 = always together)')
plt.tight_layout(); plt.show()
""")

md(r"""
**What we saw.** PAR_045T, PAR_077, PAR_048 and PAR_045 move together (0.6 to 0.8): a trader who is often
topped up is also often amended and often has large top-ups. PAR_066, PAR_105 and PAR_023 measure something
different.

**Decision.** Keep every agreed parameter that has data, and set the weights so the same behaviour is
not counted at full strength more than once: PAR_045T and PAR_077 carry the weight, PAR_048 stays at 4%.

**What it means for Customs.** Without this, a trader with one bad record would be counted four times over
and pushed to the top ahead of traders with different kinds of risk.

### D6. How much each feature contributes

We measured each feature three ways over six test dates:

* **Alone**: how well the feature on its own puts checks that found a top-up ahead of checks that did not.
  0.50 means no better than chance; 1.00 would be perfect.
* **If removed**: rescore without the feature and see how much the ranking changes.
* **Share of points**: how much of the score of HIGH and above taxpayers comes from the feature.
""")

code(r"""
# What: each feature alone, dropped, and its share of points, over six dates.
codes = [p['code'] for p in M.PARAMS]; col = {p['code']: p['col'] for p in M.PARAMS}
rows, full = [], []
for s in SIX:
    raw_ = ex[s].reset_index(drop=True); dd_ = M.derive(raw_)
    pts = M.layer2_scorecard(dd_)[0]; total = pts.sum(axis=1)
    base = P.per_check(raw_, total.to_numpy())['Per check: ROC AUC']; full.append(base)
    hi = total.map(M.band_of).isin(['HIGH', 'VERY HIGH'])
    for c in codes:
        with S.settings(scale={c: 0}):
            dropped = M.layer2_scorecard(M.derive(raw_))[0].sum(axis=1).to_numpy()
        rows.append(dict(code=c, alone=P.per_check(raw_, dd_[col[c]].fillna(0).to_numpy())['Per check: ROC AUC'],
                         change=P.per_check(raw_, dropped)['Per check: ROC AUC'] - base,
                         share=pts.loc[hi, c].sum() / pts.loc[hi].sum().sum()))
fa = pd.DataFrame(rows).groupby('code', sort=False).mean().reset_index()
fig, axes = plt.subplots(1, 2, figsize=(13, 3.8))
axes[0].barh(fa['code'][::-1], fa['alone'][::-1], color=BLUE, height=0.6); axes[0].set_xlim(0.3, 0.9)
axes[0].axvline(0.5, color=INK2, linestyle=':', linewidth=1)
for i, v in enumerate(fa['alone'][::-1]):
    axes[0].text(v + 0.005, i, f'{v:.2f}', va='center', fontsize=9, color=INK2)
axes[0].set_title('Each feature alone (0.50 = chance)', fontsize=12); axes[0].grid(axis='y', visible=False)
axes[1].barh(fa['code'][::-1], fa['share'][::-1], color=ORANGE, height=0.6); axes[1].xaxis.set_major_formatter(pct)
for i, v in enumerate(fa['share'][::-1]):
    axes[1].text(v + 0.005, i, f'{v:.0%}', va='center', fontsize=9, color=INK2)
axes[1].set_title('Share of points, HIGH and above', fontsize=12); axes[1].grid(axis='y', visible=False)
plt.tight_layout(); plt.show()
fa.columns = ['Feature', 'Alone', 'Change if removed', 'Share of points (HIGH and above)']
table(fa, **{'Alone': '{:.2f}', 'Change if removed': '{:+.3f}', 'Share of points (HIGH and above)': '{:.0%}'})
print(f'All eight together: {np.mean(full):.3f}')
""")

md(r"""
**What we saw.** The share of declarations topped up is the backbone of the score: it is the strongest alone and
the only one whose removal clearly hurts. The smaller five add little when we judge only by top-ups.

**Decision.** Keep all eight for now and bring this evidence to the weights session with the Risk
Officers.

**What it means for Customs.** Top-ups only show what checks already found. The smaller features (prices below
peers, tax reductions, station movement) are there to catch risks that top-ups cannot show, so a low score
here does not mean they are useless. The Risk Officers are best placed to set their weight.

### D7. Recency: how much each year of history counts

At first the model used the last 2 years, both counting equally. We tested other options on 18 dates since
2017.

**Example records: 10 taxpayers, with their yearly counts and the share topped up under the old and new rule**
""")

code(r"""
# What: old 2-year rate against the adopted 3-year weighted rate for 10 taxpayers.  Why: shows what recency changes.
e = raw[(raw['y1_entries'] > 0) & (raw['y2_entries'] > 0) & ((raw['y1_topped_up'] + raw['y2_topped_up'] + raw['y3_topped_up']) > 0)].head(10).copy()
e['old'] = (e['y1_topped_up'] + e['y2_topped_up']) / (e['y1_entries'] + e['y2_entries'])
e['new'] = (e['y1_topped_up'] + 0.5 * e['y2_topped_up'] + 0.25 * e['y3_topped_up']) / (e['y1_entries'] + 0.5 * e['y2_entries'] + 0.25 * e['y3_entries'])
preview(e, ['y1_entries', 'y1_topped_up', 'y2_entries', 'y2_topped_up', 'y3_entries', 'y3_topped_up', 'old', 'new'],
        names={'y1_entries': 'Declarations, last year', 'y1_topped_up': 'Topped up, last year',
               'y2_entries': 'Declarations, year before', 'y2_topped_up': 'Topped up, year before',
               'y3_entries': 'Declarations, 2 years before', 'y3_topped_up': 'Topped up, 2 years before',
               'old': 'Old rule (2 years, equal)', 'new': 'Adopted (3 years: 1, 0.5, 0.25)'},
        fmt={'Old rule (2 years, equal)': PCT, 'Adopted (3 years: 1, 0.5, 0.25)': PCT,
             **{k: '{:,.0f}' for k in ['Declarations, last year', 'Topped up, last year', 'Declarations, year before',
                                       'Topped up, year before', 'Declarations, 2 years before', 'Topped up, 2 years before']}})
""")

code(r"""
# What: the recency options tested on 18 dates since 2017.
f_ = RESULTS_DIR / 'CTRP_performance_since_2017.xlsx'
r3 = pd.read_excel(f_, sheet_name='Recency 3-year weights')
r2 = pd.read_excel(f_, sheet_name='Recency 2 or 3 years')
r2 = r2[r2['variant'].isin(['Last year only', '2 years, older year counts half'])]
rr_ = pd.concat([r3, r2])
ref = rr_[rr_['variant'].str.startswith('Now')].set_index('snap')
rows = []
for v, g_ in rr_.groupby('variant'):
    g_ = g_.set_index('snap')
    rows.append({'Option': v.replace('Now: last 2 years, equal', 'Old rule: last 2 years, equal'),
                 'Ranking quality (0.50 = chance)': g_['auc'].mean(),
                 'Better ranking than the old rule': f"{(g_['auc'] > ref['auc']).sum()} of {len(g_)}",
                 'More found per check in the top 5%': f"{(g_['prec5'] > ref['prec5']).sum()} of {len(g_)}",
                 'More found per check, HIGH and above': f"{(g_['hi_prec'] > ref['hi_prec']).sum()} of {len(g_)}"})
t = pd.DataFrame(rows).sort_values('Ranking quality (0.50 = chance)', ascending=False)
t.loc[t['Option'].str.startswith('Old'), t.columns[2:]] = 'reference'
table(t, **{'Ranking quality (0.50 = chance)': '{:.3f}'})
""")

md(r"""
**What we saw.** Every 3-year option ranks a little better than the old 2-year rule on almost every date. The
difference between them shows at the top of the list: halving finds more per check in the top 5% on 15 of 18
dates, more often than any other option.

**Decision: use 3 years, with the latest year counting fully, the year before half, and the one
before that a quarter.** Equal weights let old top-ups count as much as recent ones; steeper weights forget too
fast. Five years added nothing measurable.

**What it means for Customs.** A trader who was caught three years ago and has been clean since is gradually
let go: within about two years they move down the list. A trader caught recently stays in view. This matches
how officers already read a trader's history, and it rewards traders who improve.

---
## E. How do features become a score and a band?

### E1. The scorecard
""")

code(r"""
# What: the scorecard settings in force, straight from the code.
tot = sum(li.values())
sc_tab = pd.DataFrame([{'Feature': f"{p['code']} {p['label']}",
                        'Points start above': 'no' if p['fmt'] == 'yesno' else f"{p['zero_at']:.0%}",
                        'Full points at': 'yes' if p['fmt'] == 'yesno' else f"{p['one_at']:.0%}",
                        'Likelihood (1 to 5)': p['L'], 'Impact (1 to 5)': p['I'], 'Most points': round(li[p['code']] / tot * 100)} for p in M.PARAMS])
table(sc_tab)
print('Score = the points of the eight features added together, 0 to 100. Bands: '
      + ', '.join(f'{n} up to {u}' for u, n in M.BANDS) + '.')
""")

md(r"""
Each feature's weight is likelihood x impact. These are Data Science working values set from the evidence in
part D, to be confirmed by the Risk Officers.

**Example records: 10 taxpayers, two from each band, with their points per feature, score and band**
""")

code(r"""
# What: points per feature, score and band for 10 taxpayers.  Why: shows the whole calculation for real rows.
pts = PTS
sc_ = pts.sum(axis=1).round().map(M.band_of)
e = d.loc[sorted(i for b in [n for _, n in M.BANDS] for i in d.index[(sc_ == b) & (d['entries_24m'] >= 10)][:2])].copy()
for c in pts.columns:
    e[c] = pts.loc[e.index, c]
e['score'] = pts.loc[e.index].sum(axis=1).round()
e['band'] = e['score'].map(M.band_of)
e = e.sort_values('score', ascending=False)
preview(e, ['entries_24m'] + list(pts.columns) + ['score', 'band'],
        names={'entries_24m': 'Declarations', 'score': 'Score', 'band': 'Band'},
        fmt={**{c: '{:.1f}' for c in pts.columns}, 'Score': '{:.0f}'})
""")

md(r"""
### E2. Do the bands mean what they say?
""")

code(r"""
# What: per band, share of taxpayers, share of checks that found a top-up, share of top-up money (six dates pooled).
rows = []
for s in SIX:
    raw_ = ex[s]; total = M.layer2_scorecard(D[s])[0].sum(axis=1).round()
    rows.append(pd.DataFrame({'band': total.map(M.band_of), 'checks': raw_['out_checked'], 'hits': raw_['out_checked_hits'],
                              'money': raw_['out_top_up'].fillna(0)}))
bb = pd.concat(rows)
g = bb.groupby('band').agg(taxpayers=('band', 'size'), checks=('checks', 'sum'), hits=('hits', 'sum'), money=('money', 'sum'))
g = g.reindex([n for _, n in M.BANDS][::-1])
g['Share of taxpayers'] = g['taxpayers'] / g['taxpayers'].sum()
g['Checks that found a top-up'] = g['hits'] / g['checks']
g['Share of top-up money'] = g['money'] / g['money'].sum()
fig, ax = plt.subplots(figsize=(10, 3.4))
bars = ax.bar(g.index, g['Checks that found a top-up'], color=RAMP[::-1], width=0.6)
for b_, v in zip(bars, g['Checks that found a top-up']):
    ax.text(b_.get_x() + b_.get_width() / 2, v, f'{v:.0%}', ha='center', va='bottom', fontsize=10, color=INK2)
ax.yaxis.set_major_formatter(pct); ax.grid(axis='x', visible=False)
ax.set_title('Share of checks that found a top-up, by band (six dates, Sep 2023 to Mar 2026)')
plt.show()
table(g[['Share of taxpayers', 'Checks that found a top-up', 'Share of top-up money']].reset_index().rename(columns={'band': 'Band'}),
      **{'Share of taxpayers': '{:.1%}', 'Checks that found a top-up': '{:.0%}', 'Share of top-up money': '{:.0%}'})
""")

md(r"""
**What we saw.** Each band finds more than the one below it. Checks on VERY HIGH taxpayers found a top-up 45
times in 100; on VERY LOW, 3 times in 100. HIGH and above is under 8% of taxpayers but carries over half of the
top-up money.

**What it means for Customs.** Officers can plan around the bands: focus checks on HIGH and above where they
find the most, and give VERY LOW traders, about 7 in 10 of all taxpayers, a lighter touch. That means more
revenue per officer hour and faster clearance for compliant traders.

---
## F. What does Track B look at, for taxpayers with no record?

Track A can only score what customs has already found. A trader who undervalues and has never been caught has
no top-ups, so Track A gives them nothing. Track B looks at **how a taxpayer trades** (prices, goods, duty,
patterns), for taxpayers with **no top-up history**. It never uses what customs did to them (no top-ups, no
lanes), so it does not simply repeat past selection.
""")

code(r"""
# What: how many taxpayers have no top-up history, and their share of later hits.
raw_ = ex[latest]; nh = B.no_history(raw_)
table(pd.DataFrame([{'Taxpayers with no top-up history': nh.mean(),
                     'Their share of later hits': raw_.loc[nh, 'out_checked_hits'].sum() / raw_['out_checked_hits'].sum(),
                     'Track A points they can get from top-ups': 'none'}]),
      **{'Taxpayers with no top-up history': '{:.0%}', 'Their share of later hits': '{:.0%}'})
""")

md(r"""
### F1. Peer groups: who is compared with whom

"Unusual" only means something next to similar traders: a large fuel importer and a small car importer should
not be judged against each other. So every regular taxpayer (10 or more declarations in 2 years) is put in a
**peer group** made of two parts:

* **Main goods**: the section of the HS tariff where most of the taxpayer's customs value falls, for example
  "Vehicles" (chapters 86 to 89) or "Textiles" (chapters 50 to 63).
* **Size**: within that section, taxpayers are ranked by their total customs value over the last 2 years and
  split into three equal parts: the bottom third is **small**, the middle third **medium**, the top third
  **large**. Size is decided within each section, so a "large" textile importer is large for textiles, not
  next to fuel importers.

Groups with fewer than 30 taxpayers are joined into "Other goods" of the same size, so every group is big
enough to compare against. We also tried letting an algorithm find the groups by itself (clustering): it left
77% of traders without a group, so we kept this simpler rule, which officers can also read and check.

**Example records: 10 regular taxpayers and their peer group**
""")

code(r"""
# What: main goods, value, size and peer group for 10 taxpayers; the value range of each size in three sections.
pg = M.peers_section_size(d, [])
e = d.loc[pg.index].copy()
e['section'] = e['dominant_hs_chapter'].map(M.hs_section)
e['size'] = pg['peer_group_name'].str.split(', ').str[-1]
e['group'] = pg['peer_group_name']
preview(e, ['dominant_hs_chapter', 'section', 'total_customs_value', 'size', 'group'],
        names={'dominant_hs_chapter': 'Main HS chapter', 'section': 'Main goods', 'total_customs_value': 'Customs value, 2 years, UGX',
               'size': 'Size', 'group': 'Peer group'}, fmt={'Customs value, 2 years, UGX': UGX})
rng = (e[e['section'].isin(['Vehicles', 'Textiles', 'Machinery, electrical'])]
       .groupby(['section', 'size'])['total_customs_value'].agg(['min', 'max', 'count']).reset_index())
rng['size'] = pd.Categorical(rng['size'], ['small', 'medium', 'large']); rng = rng.sort_values(['section', 'size'])
display(Markdown('**Where the size lines fall in three sections** (customs value over 2 years)'))
table(rng.rename(columns={'section': 'Main goods', 'size': 'Size', 'min': 'From, UGX', 'max': 'To, UGX', 'count': 'Taxpayers'}),
      **{'From, UGX': UGX, 'To, UGX': UGX, 'Taxpayers': '{:,}'})
print(f"{pg['peer_group_name'].nunique()} peer groups at {latest}.")
""")

md(r"""
**What it means for Customs.** When Track B or the pattern note says a trader is unusual, it means unusual for
traders who import the same kind of goods at a similar scale. That is a comparison officers can check and
explain to the trader.

### F2. Track B features: columns used and how each is built

"v2" means built and tested on one date so far; it joins the model when older dates are pulled again in the
new format.

| Feature | Columns used | How it is built (per taxpayer) | What it points officers to |
|---|---|---|---|
| Declarations amended | `amendment_flg` | Share of declarations amended | Declarations often wrong the first time |
| Tax left unpaid | `pay_status` | Share of declarations not paid | Traders who leave tax unpaid |
| Prices that look like keying errors | `customs_value`, `net_weight`, `hsc_cd` | Share of items priced under 1% of the middle price for the HS code | Careless or deliberate wrong weights |
| Value below the HS benchmark | `customs_value`, `net_weight`, `supplementary_qnty`, `hsc_cd`, `gds_org_cty` | Shortfall against other importers' middle price, as a share of value (PAR_076) | Undervaluation |
| Items priced below half the benchmark | same | Share of items under half the middle price | Undervaluation |
| Prices far from other importers (v2) | same | How far prices typically sit from the middle price, either way | Unusual pricing |
| Price dropped against own history (v2) | `customs_value`, `net_weight`, `hsc_cd`, `assessment_dt_wid` | Share of value where the taxpayer's own price for the same goods fell (PAR_067) | A trader who starts declaring cheaper |
| Duty rate below HS peers (v2) | `tax_assessed`, `customs_value`, `hsc_cd`, `cpc_cd` | Share of value taxed under half the middle rate for the HS code (no exemption claimed) | Possible misclassification |
| Duty shortfall (v2) | same | Tax below the middle rate, as a share of value | Size of possible misclassification |
| Exemption codes (v2) | `cpc_cd`, `customs_value` | Share of value under an exemption code (PAR_053) | Heavy reliance on exemptions |
| Watch-list exemption codes (v2) | `cpc_cd`, `customs_value` | Share of value under codes the AC-Trade memo marks for abuse (PAR_053) | Use of codes known to be abused |
| Preferential treatment claimed | `preferential_treatment_flag` | Share of items claiming preference | Preference claims |
| Sudden rise in declarations | `assessment_dt_wid` | Last 90 days against the average quarter | Sudden changes in activity |
| Away from the main station | `clearance_station_cd` | Share of declarations away from the most used station | Station shopping |
| Many kinds of goods per declaration | `hsc_cd`, `instance_id` | HS headings used per declaration | Mixed consignments that hide items |
| Same-day splitting (v2) | `hsc_cd`, `assessment_dt_wid`, `instance_id` | Same goods, same day, separate declarations, above the norm for those goods (cement and fuel left out) | Splitting to stay under limits |
| Recently started (v2) | `assessment_dt_wid` | Days since the first declaration | New traders with no track record |

Each feature is then compared within the taxpayer's **peer group** (F1), so "high" means high for that kind
of importer. Code: `src/ctrp/discovery.py` (`FEATURES`, `build_features`).

**What these features can and cannot do.** They do not prove that a trader misclassified or undervalued.
They show patterns that go with it: paying a much lower duty rate than other importers of the same HS code,
or declaring much lower prices for the same goods. The model learns how likely a trader is to be found wrong,
and points officers to where an inspection or audit is most worth doing. Whether there was misclassification
is found by the officer at the check, and that finding is what the model then learns from.

**Example records: 10 taxpayers with no top-up history and some of their Track B features**
""")

code(r"""
# What: Track B features for 10 taxpayers with no top-up history.
raw_ = ex[latest].reset_index(drop=True); X = B.build_features(raw_)
nhm = B.no_history(raw_) & (raw_['entries_24m'] >= 3)
e = pd.concat([raw_[['taxpayer_tin', 'entries_24m']], X.drop(columns=[c for c in X if c in ('entries_24m',)])], axis=1)[nhm]
show = [c for c in ['par045_amended_entry_rate', 'ctx_unpaid_rate', 'par076_shortfall_share', 'par076_low_price_item_rate',
                    'station_spread', 'goods_spread', 'surge', 'ctx_preferential_use_rate'] if c in e]
preview(e, ['entries_24m'] + show, names={'entries_24m': 'Declarations', **{c: B.LABEL.get(c, c) for c in show}},
        fmt={B.LABEL.get(c, c): ('{:.2f}' if c in ('goods_spread', 'surge') else '{:.0%}') for c in show})
""")

md(r"""
### F3. Which features carry signal?
""")

code(r"""
# What: each Track B feature alone, among taxpayers with no top-up history, every date.
res = []
for s, raw_ in ex.items():
    raw_ = raw_.reset_index(drop=True); X = B.build_features(raw_); nh = B.no_history(raw_)
    for seg, cond in [('Regular traders', raw_['entries_24m'] >= M.ADEQUATE_ENTRIES), ('Small traders', raw_['entries_24m'] < M.ADEQUATE_ENTRIES)]:
        m_ = (nh & cond).to_numpy()
        for f_, sign, _, lab in B.FEATURES:
            if f_ in X and X.loc[m_, f_].notna().mean() > 0.5:
                res.append((seg, lab, s, B.auc_per_check(raw_[m_], sign * X.loc[m_, f_].to_numpy(float))))
res = pd.DataFrame(res, columns=['segment', 'feature', 'date', 'auc'])
every = res.groupby('feature')['date'].nunique() == len(ex)
fb = res[res['feature'].map(every)].groupby(['feature', 'segment'])['auc'].mean().unstack().sort_values('Regular traders')
fig, ax = plt.subplots(figsize=(10, 0.45 * len(fb) + 1))
yy = np.arange(len(fb))
ax.barh(yy + 0.2, fb['Regular traders'], height=0.38, color=BLUE, label='Regular traders (10+ declarations)')
ax.barh(yy - 0.2, fb['Small traders'], height=0.38, color=ORANGE, label='Small traders')
ax.set_yticks(yy, fb.index); ax.set_xlim(0.4, 0.65); ax.axvline(0.5, color=INK2, linestyle=':', linewidth=1)
ax.grid(axis='y', visible=False); ax.legend(loc='lower right')
ax.set_title(f'Each feature alone, no top-up history ({len(ex)} dates; 0.50 = chance)')
plt.show()
""")

md(r"""
**What we saw.** Station movement, goods per declaration and the price features carry the most. Every signal is
modest when judged by top-ups. That is expected: an undervaluation never caught never became a top-up, so
top-ups show only part of what Track B is looking for.

### F4. Results, and what must be fixed
""")

code(r"""
# What: Track B against Track A on the same taxpayers (models trained only on earlier dates).
tb = pd.read_excel(RESULTS_DIR / 'CTRP_track_b_per_check.xlsx', sheet_name='AUC per check')
keep = tb[tb['model'].str.contains('Track A|learned weights|monotone', case=False)]
keep = keep.rename(columns={'segment': 'Segment', 'model': 'Model', 'average': 'Average'})
table(keep, **{c: '{:.3f}' for c in keep.columns if c not in ('Segment', 'Model')})
""")

md(r"""
* Track B ranks better than chance on every test date, and better than Track A on the same taxpayers.
* **To fix before it goes live:** 506 of the 510 live flags are led by "many kinds of goods per
  declaration", and the typical flagged taxpayer has one declaration. We will cap how much any one feature can
  count, require two independent signals before a flag, and add the v2 features once older dates are pulled
  again.
* **Proof:** a blind review. Officers look at 25 flagged and 25 unflagged taxpayers without knowing which is
  which.

**What it means for Customs.** Track B is the part of the model that can find revenue the current process misses:
traders who undervalue or misclassify and have never been caught. Until it is proven, a Track B flag can raise a
taxpayer to HIGH at most, never to VERY HIGH.
""")

nb['cells'] = C
nb['metadata'] = {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
                  'language_info': {'name': 'python'}}
out = Path(__file__).with_name('CTRP_story.ipynb')
nbf.write(nb, out)
print(f'wrote {out} ({len(C)} cells)')
