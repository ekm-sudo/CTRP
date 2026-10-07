"""
Customs Taxpayer Risk Profiling Model: the one entry point for every job.

What: one command per task, run from the project folder (Git Bash or PowerShell):

    python main.py sql                                 write the Hue queries into sql/
    python main.py sql --split 2025-03-31              the same query cut in three, for a snapshot
                                                       whose full query will not finish in Hue
    python main.py merge                               glue the three parts into data/<name>.csv
    python main.py check "data/*.csv"                  test every downloaded extract
    python main.py score data/live_2026-09-30.csv      the officers' workbook in results/
    python main.py backtest                            lift and band hit rates, every data/bt_*.csv
    python main.py challengers                         challengers and ensembles (about 10 minutes)
    python main.py notebook                            rebuild and run the notebook (about 15 minutes)
    python main.py docs                                rebuild the Word documents in docs/
    python main.py test                                run the automatic tests

Why:  one place to start anything, so nobody has to remember which script does what. The model
      itself lives in src/ctrp; this file only reads the command and calls it.
"""
import argparse
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))            # works with or without "pip install -e ."


def cmd_sql(args):
    from ctrp import extract
    if args.split:
        extract.write_split_queries(args.split)
    else:
        extract.write_queries()


def cmd_merge(args):
    from ctrp import extract
    extract.merge_split()


def cmd_check(args):
    from ctrp import extract
    extract.check_files(args.files)


def cmd_score(args):
    from ctrp import pipeline
    pipeline.score_file(args.file)


def cmd_backtest(args):
    from ctrp import pipeline
    pipeline.backtest_files(args.pattern)


def cmd_challengers(args):
    import pandas as pd
    from ctrp.models import challengers as CH
    from ctrp.utils import RESULTS_DIR, backtest_extracts
    ex = backtest_extracts(args.pattern)
    print(f'{len(ex)} extracts; running {len(CH.CHALLENGERS)} models and the ensembles (about ten minutes)...')
    table, detail, weights = CH.compare(ex)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / 'CTRP_challengers.xlsx'
    with pd.ExcelWriter(out) as w:
        table.to_excel(w, sheet_name='Average of tests')
        detail.to_excel(w, sheet_name='Per snapshot', index=False)
        weights.to_excel(w, sheet_name='Weights')
        CH.compare.stack_weights.to_excel(w, sheet_name='Stacked blend weights')
    pd.set_option('display.width', 250)
    print(table.round(3).to_string())
    print(f'written {out}')


def cmd_notebook(args):
    runpy.run_path(str(ROOT / 'notebooks' / 'build_notebook.py'), run_name='__main__')
    if not args.no_run:
        nb = ROOT / 'notebooks' / 'CTRP_release1.ipynb'
        subprocess.run([sys.executable, '-m', 'jupyter', 'nbconvert', '--to', 'notebook', '--execute', str(nb),
                        '--output', nb.name, '--ExecutePreprocessor.timeout=3000'], check=True)
        print(f'ran {nb}; charts saved in results/charts/')


def cmd_docs(args):
    for f in ['build_decision_record.py', 'build_model_guide.py']:
        runpy.run_path(str(ROOT / 'docs' / 'builders' / f), run_name='__main__')


def cmd_test(args):
    try:
        import pytest  # noqa: F401
    except ImportError:
        raise SystemExit('pytest is not installed. Run: python -m pip install pytest   '
                         '(if pip cannot reach the internet, see "When something goes wrong" in the Model Guide)')
    raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q', str(ROOT / 'tests')]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python main.py', description='Customs Taxpayer Risk Profiling Model')
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('sql', help='write one Hue query per snapshot into sql/')
    p.add_argument('--split', nargs='+', metavar='DATE', help='write three smaller queries for these snapshots')
    p.set_defaults(fn=cmd_sql)
    sub.add_parser('merge', help='glue split parts in data/split/ into one extract').set_defaults(fn=cmd_merge)
    p = sub.add_parser('check', help='test downloaded extracts'); p.add_argument('files', nargs='?', default='data/*.csv'); p.set_defaults(fn=cmd_check)
    p = sub.add_parser('score', help='score one extract (the production run)'); p.add_argument('file'); p.set_defaults(fn=cmd_score)
    p = sub.add_parser('backtest', help='back-test every data/bt_*.csv'); p.add_argument('pattern', nargs='?', default='bt_*.csv'); p.set_defaults(fn=cmd_backtest)
    p = sub.add_parser('challengers', help='compare challengers and ensembles'); p.add_argument('pattern', nargs='?', default='bt_*.csv'); p.set_defaults(fn=cmd_challengers)
    p = sub.add_parser('notebook', help='rebuild and run the notebook'); p.add_argument('--no-run', action='store_true', help='rebuild only'); p.set_defaults(fn=cmd_notebook)
    sub.add_parser('docs', help='rebuild the Word documents').set_defaults(fn=cmd_docs)
    sub.add_parser('test', help='run the automatic tests').set_defaults(fn=cmd_test)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == '__main__':
    main()
