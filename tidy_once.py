"""
One-off clean-up of the project folder (22 October 2026). Run once from the project folder:

    python tidy_once.py

What: moves files that are superseded, duplicated or no longer used into _to_delete/ (same sub-folders), and
      deletes Python caches. Nothing else is deleted: look through _to_delete/, then delete that folder and this
      script yourself.
Why:  the folder had collected old versions, duplicate copies and stale generated files (about 0.6 GB).
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN = ROOT / '_to_delete'

MOVE = {
    # superseded code and layout (kept in git history)
    'archive': 'pre-src layout and old scripts, all replaced by src/ctrp',
    'CTRP_features_in_python.ipynb': 'older copy of a notebook at the root',
    'notebooks/CTRP_features_in_python.ipynb': 'needed raw item rows that were never pulled; the EDA notebook Part 6 '
                                               'now builds the features from the extract',
    'notebooks/build_features_nb.py': 'builder of the notebook above',
    'sql/python_features': 'queries for the notebook above',
    'notebooks/zeppelin/eda_paste': 'old paste files with the old feature names; eda_paragraphs/ is current',
    'sql/hue_plan': 'the 66-query plan replaced by the yearly long run and the full extracts',
    'sql/split': 'version 2 split parts for 2025; python main.py sql --split <date> rewrites them if needed',
    'sql/analysis': 'early EDA queries from the old layout',
    # old data
    'data/old': 'version 1 extracts',
    'data/archive_v2/v2 extracts': 'duplicate "(1)" downloads of version 2 extracts',
    'data/archive_v2/long_run/lr_*.csv': 'version 2 long run by date, replaced by the yearly pieces',
    'data/eda_issues/E12.csv': 'issue E12 is not part of the EDA report',
    'data/eda_final/production_check': 'check output the EDA notebook rewrites on every run',
    # superseded documents and outputs
    'docs/build_stella_note.js': 'builder of the first one-page note, replaced by build_stella_one_page.js',
    'results/CTRP_EDA_note_for_Stella.docx': 'first one-page note, replaced',
    'results/CTRP_EDA_for_Stella': 'copies of the report, numbers and workbooks; the package sent is in EDA Report/',
    'results/~$CTRP_missed_revenue_since_july_2026.xlsx': 'Excel lock file',
    'results/archive_v2/~$CTRP_missed_revenue_since_july_2026.xlsx': 'Excel lock file',
    'presentations/CTRP_progress_review_2026-10-15.pptx': 'earlier version of the review deck',
    'presentations/CTRP_progress_review_2026-10-15_URA.pptx': 'earlier version of the review deck (v2 is current)',
}
CACHES = ['.pytest_cache', '**/__pycache__']


def size(p):
    return p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob('*') if f.is_file())


moved, total = 0, 0
for pattern, why in MOVE.items():
    for src in sorted(ROOT.glob(pattern)):
        if BIN in src.parents:
            continue
        mb = size(src)
        dst = BIN / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved += 1
        total += mb
        print(f'moved  {src.relative_to(ROOT)}  ({mb / 1e6:.1f} MB): {why}')

for pattern in CACHES:
    for c in ROOT.glob(pattern):
        if c.is_dir() and BIN not in c.parents:
            shutil.rmtree(c, ignore_errors=True)

print(f'\n{moved} items moved to _to_delete/ ({total / 1e9:.2f} GB). Python caches deleted.')
print('Look through _to_delete/, then delete it and this script.')
