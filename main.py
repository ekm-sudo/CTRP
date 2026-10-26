"""
Customs Taxpayer Risk Profiling Model: the one entry point for every job.

What: one command per task, run from the project folder (Git Bash or PowerShell).

  Getting the data
    python main.py sql                                 write the Hue queries into sql/
    python main.py sql --split 2025-03-31              the same query cut in parts, for a snapshot
                                                       whose full query will not finish in Hue
    python main.py sql --plan | --long-run | --addon   the run-order checklist, the long-run query,
                                                       the long-run add-on queries
    python main.py merge                               glue the split parts into data/<name>.csv
    python main.py check "data/*.csv"                  test every downloaded extract
    python main.py long-run                            snapshots from the long-run download
    python main.py v3 --archive | --run-order | --rebuild   the version 3 redo (entry key, no vehicles)
    python main.py zeppelin                            the Zeppelin note (and script) that pulls every extract
    python main.py pull --test | <query> | --run-order  run queries on the data lake, results straight into data/
    python main.py eda-report [--sql]                  the EDA numbers through Hue, as one workbook
    python main.py eda-note                            the Zeppelin note for sign-off: EDA and the 22 features
    python main.py eda-excel data/zeppelin_eda         that note's results as Excel workbooks in results/
    python main.py issues [--sql]                      EDA issue workbooks for the Risk Officers (or the queries)

  Scoring and testing the model
    python main.py score data/live_2026-09-30.csv      the officers' workbook in results/
        [--evidence data/evidence/review_<date>.csv]   adds the Entry evidence sheet
    python main.py backtest                            lift and band hit rates, every data/bt_*.csv
    python main.py performance [--long-run]            precision, recall and ROC AUC on the back-tests
    python main.py discovery                           Track B: how well behaviour finds first-time cases
    python main.py sensitivity                         Track A settings moved one at a time
    python main.py challengers                         challengers and ensembles (about 10 minutes)
    python main.py candidates                          candidate parameters tested against Track A

  Reviews and other outputs
    python main.py review results/CTRP_scores_<date>.xlsx   Hue query: evidence for the officers' review
    python main.py blind-pack <evidence.csv> <key.csv> the officers' blind review workbook
    python main.py audit                               missed-revenue workbook for NTC
    python main.py pca [--sql]                         post-clearance audit list (or write its Hue queries)
    python main.py view                                officer view: one HTML file with the results
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
    if args.long_run:
        from ctrp import longrun
        longrun.write_queries()
    elif args.addon:
        from ctrp import addon
        addon.write_queries()
    elif args.plan:
        extract.write_hue_plan()
    elif args.split:
        extract.write_split_queries(args.split, parts=args.parts)
    else:
        extract.write_queries()


def cmd_long_run(args):
    """Build a snapshot file for every date the long-run download covers."""
    from ctrp import longrun
    longrun.write_snapshots()
    longrun.add_years_to_extracts()


def cmd_merge(args):
    from ctrp import extract
    extract.merge_split()


def cmd_check(args):
    from ctrp import extract
    extract.check_files(args.files)


def cmd_zeppelin(args):
    from ctrp import zeppelin
    zeppelin.write_script()
    zeppelin.write_note()
    zeppelin.write_paste_files()


def cmd_discovery(args):
    import pandas as pd
    from ctrp import discovery as B
    from ctrp.utils import RESULTS_DIR, backtest_extracts
    if args.compare_without:
        avg, wide = B.compare_without(backtest_extracts(args.pattern), args.compare_without)
        out = RESULTS_DIR / f'CTRP_behavioural_risk_without_{args.compare_without}.xlsx'
        with pd.ExcelWriter(out) as w:
            avg.to_excel(w, sheet_name='Average', index=False)
            wide.to_excel(w, sheet_name='Per snapshot', index=False)
        pd.set_option('display.width', 250)
        print(avg.round(4).to_string(index=False))
        print(f'written {out}')
        return
    table, detail, weights = B.evaluate(backtest_extracts(args.pattern))
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / 'CTRP_track_b.xlsx'
    with pd.ExcelWriter(out) as w:
        table.to_excel(w, sheet_name='Average of tests')
        detail.to_excel(w, sheet_name='Per snapshot', index=False)
        weights.to_excel(w, sheet_name='Learned weights')
    pd.set_option('display.width', 250)
    print(table[['group_size', 'group_hits', 'disc_lift_top5', 'disc_hits_top5', 'disc_lift_top10',
                 'tests_beating_track_A']].round(2).to_string())
    print(f'written {out}')


def cmd_performance(args):
    """Precision, recall, ROC AUC and accuracy on every back-test snapshot."""
    from ctrp import performance
    table, bands, out = performance.run(long_run=args.long_run)
    print(table.round(3).T.to_string())
    print(f'written {out}')


def cmd_sensitivity(args):
    import pandas as pd
    from ctrp import sensitivity as S
    from ctrp.utils import RESULTS_DIR, backtest_extracts
    table, detail = S.run(backtest_extracts(args.pattern))
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / 'CTRP_sensitivity.xlsx'
    with pd.ExcelWriter(out) as w:
        table.to_excel(w, sheet_name='Average of snapshots')
        detail.to_excel(w, sheet_name='Per snapshot', index=False)
    pd.set_option('display.width', 250)
    print(table.round(3).to_string())
    print(f'written {out}')


def cmd_review(args):
    from ctrp import review
    if args.blind:
        review.write_blind_review_sql(args.workbook, args.blind, args.per_taxpayer, args.extract)
    else:
        review.write_review_sql(args.workbook, args.regular, args.small, args.per_taxpayer)


def cmd_blind_pack(args):
    from ctrp import review
    from ctrp.utils import RESULTS_DIR
    snap = Path(args.key).stem.split('_')[1]
    review.write_blind_pack(args.evidence, args.key, RESULTS_DIR / f'CTRP_blind_review_{snap}.xlsx')


def cmd_score(args):
    from ctrp import pipeline
    pipeline.score_file(args.file, args.evidence)


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


def cmd_pca(args):
    from ctrp import pca
    if args.sql:
        pca.write_queries()
    else:
        pca.build()


def cmd_view(args):
    from ctrp import officer_view
    officer_view.write()


def cmd_audit(args):
    from ctrp import audit as A
    out, res = A.run()
    s = res['summary'].set_index('Measure')['Value']
    declarations = s['Underpriced declarations not topped up (items under half the peer price)']
    missed_ugx = s['Estimated missed top-up (tax on the potential undervaluation), UGX']
    print(f"{declarations:,} declarations, {s['Taxpayers']:,} taxpayers; "
          f"estimated missed top-up UGX {missed_ugx / 1e9:,.1f}bn")
    print(f'written {out}')


def cmd_v3(args):
    from ctrp import v3
    from ctrp.utils import DATA_DIR
    if args.archive:
        v3.archive()
    if args.run_order:
        v3.write_run_order()
    if not args.rebuild:
        return
    steps = []
    if list((DATA_DIR / 'long_run').glob('long_run_*.csv')):
        steps += [['long-run'], ['performance', '--long-run'], ['candidates']]
    if list(DATA_DIR.glob('bt_*.csv')):
        steps += [['check'], ['backtest'], ['performance'], ['discovery'], ['sensitivity']]
        if args.with_challengers:
            steps += [['challengers']]
    live = sorted(DATA_DIR.glob('live_*.csv'))
    if live:
        steps += [['score', str(live[-1])]]
    if (DATA_DIR / 'audit' / 'below_peers_since_july.csv').exists():
        steps += [['audit']]
    failed = []
    for st in steps:
        print(f'\n=== python main.py {" ".join(st)}')
        try:
            main(st)
        except (Exception, SystemExit) as e:          # one failed step must not stop the others
            failed.append((' '.join(st), str(e)[:200]))
            print(f'FAILED: {e}')
    print('\n=== version 2 against version 3')
    v3.compare()
    for st, e in failed:
        print(f'failed step: python main.py {st}: {e}')


def cmd_pull(args):
    """Run saved queries on the data lake and save the results in data/ (from the jump server)."""
    from ctrp import datalake
    if args.test:
        datalake.test_connection()
    elif args.run_order:
        datalake.pull_run_order(force=args.force)
    elif args.query:
        query = args.query
        if not query.endswith('.sql'):                 # a short name such as bt_2023-09-30
            query = f'sql/{query}.sql'
        out = args.out or 'data/' + Path(query).stem + '.csv'
        datalake.pull(query, out)
    else:
        raise SystemExit('Say what to pull: --test, --run-order, or a query (for example bt_2023-09-30)')


def cmd_eda_report(args):
    from ctrp import eda_hue
    if args.sql:
        eda_hue.write_queries()
    else:
        eda_hue.build()


def cmd_issues(args):
    from ctrp import issues as I
    if args.sql:
        I.write_queries()
    else:
        print(f'{len(I.build())} workbooks written in results/eda_issues/')


def cmd_eda_note(args):
    from ctrp import eda_note as N
    N.write_note()
    N.write_paste_files()
    from ctrp import eda_note_mine
    eda_note_mine.write_note()


def cmd_eda_excel(args):
    from ctrp import eda_note as N
    if args.from_extract:                       # no Zeppelin export: build the final dataset from a Hue extract
        N.final_dataset_from_extract(args.from_extract, args.folder)
    written = N.build_excel(args.folder)
    print(f'{len(written)} workbooks written in results/')


def cmd_candidates(args):
    from ctrp import candidates as C
    summary, _, ch, out = C.run()
    print(summary[['Candidate', 'Dates', 'AUC alone (average)', 'Best gain in AUC', 'Dates better (best weight)',
                   'Dates worse (best weight)']].round(4).to_string(index=False))
    print(f'written {out}')


def cmd_test(args):
    try:
        import pytest  # noqa: F401
    except ImportError:
        raise SystemExit('pytest is not installed. Run: python -m pip install pytest   '
                         '(if pip cannot reach the internet, see "When something goes wrong" in the Model Guide)')
    raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q', str(ROOT / 'tests')]))


BACKTEST_FILES = 'bt_*.csv'          # the default file pattern for commands that read every back-test


def build_parser():
    """Every command and option. Each command calls the cmd_ function of the same name above."""
    ap = argparse.ArgumentParser(prog='python main.py', description='Customs Taxpayer Risk Profiling Model')
    sub = ap.add_subparsers(dest='command', required=True)

    p = sub.add_parser('sql', help='write one Hue query per snapshot into sql/')
    p.add_argument('--split', nargs='+', metavar='DATE', help='write the smaller part queries for these snapshots')
    p.add_argument('--parts', nargs='+', choices=['core', 'items', 'own_duty', 'split_new', 'years'],
                   help='only these parts (e.g. --parts years for the six dates already pulled)')
    p.add_argument('--plan', action='store_true',
                   help='write every Hue query since 2017 in run order, with a checklist')
    p.add_argument('--long-run', action='store_true',
                   help='write the ONE LONG RUN query (half-year counts since 2014)')
    p.add_argument('--addon', action='store_true',
                   help='write the long-run add-on queries (candidate parameters, one per year)')
    p.set_defaults(fn=cmd_sql)

    p = sub.add_parser('v3', help='redo the analysis with the entry key and no motor vehicles '
                                  '(--archive, --run-order, --rebuild)')
    p.add_argument('--archive', action='store_true',
                   help='move version 2 downloads to data/archive_v2/ (nothing is deleted)')
    p.add_argument('--run-order', action='store_true', help='write sql/V3_RUN_ORDER.txt')
    p.add_argument('--rebuild', action='store_true',
                   help='rebuild every result from the version 3 downloads, then compare')
    p.add_argument('--with-challengers', action='store_true',
                   help='also rerun the challenger comparison (about ten minutes)')
    p.set_defaults(fn=cmd_v3)

    p = sub.add_parser('pull', help='run saved queries on the data lake and save the results in data/')
    p.add_argument('query', nargs='?', help='a short name (bt_2023-09-30) or a .sql file')
    p.add_argument('out', nargs='?', help='where to save it (default data/<name>.csv)')
    p.add_argument('--test', action='store_true', help='check the connection with a tiny query')
    p.add_argument('--run-order', action='store_true', help='every query in sql/V3_RUN_ORDER.txt not yet in data/')
    p.add_argument('--force', action='store_true', help='with --run-order: pull again even if the file exists')
    p.set_defaults(fn=cmd_pull)
    p = sub.add_parser('eda-report', help='the EDA numbers through Hue (--sql writes the queries)')
    p.add_argument('--sql', action='store_true', help='write the Hue queries into sql/eda_report/')
    p.set_defaults(fn=cmd_eda_report)
    p = sub.add_parser('issues', help='EDA issue workbook for the Risk Officers (or --sql to write the Hue queries)')
    p.add_argument('--sql', action='store_true', help='write the Hue queries into sql/eda_issues/')
    p.set_defaults(fn=cmd_issues)

    p = sub.add_parser('eda-note', help='write the Zeppelin note for EDA and features')
    p.set_defaults(fn=cmd_eda_note)

    p = sub.add_parser('eda-excel', help='Excel workbooks from the EDA note results')
    p.add_argument('folder', nargs='?', default='data/zeppelin_eda', help='folder holding the downloaded tables')
    p.add_argument('--from-extract', metavar='CSV',
                   help='build the final dataset from a Hue extract instead (for example data/live_2026-09-30.csv)')
    p.set_defaults(fn=cmd_eda_excel)

    p = sub.add_parser('candidates', help='test candidate parameters from the NTC lists against Track A')
    p.set_defaults(fn=cmd_candidates)

    p = sub.add_parser('long-run', help='build snapshots from the long-run download in data/long_run/')
    p.set_defaults(fn=cmd_long_run)

    p = sub.add_parser('merge', help='glue split parts in data/split/ into one extract')
    p.set_defaults(fn=cmd_merge)

    p = sub.add_parser('check', help='test downloaded extracts')
    p.add_argument('files', nargs='?', default='data/*.csv')
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser('zeppelin', help='write the Zeppelin extract script')
    p.set_defaults(fn=cmd_zeppelin)

    p = sub.add_parser('discovery', help='Track B evaluation')
    p.add_argument('--compare-without', metavar='FEATURE', default=None,
                   help='run the evaluation with and without one behaviour, e.g. goods_spread')
    p.add_argument('pattern', nargs='?', default=BACKTEST_FILES)
    p.set_defaults(fn=cmd_discovery)

    p = sub.add_parser('performance', help='precision, recall, AUC on the back-tests')
    p.add_argument('--long-run', action='store_true', help='the 18 dates since Sep 2017 from the long run')
    p.set_defaults(fn=cmd_performance)

    p = sub.add_parser('sensitivity', help='Track A sensitivity check')
    p.add_argument('pattern', nargs='?', default=BACKTEST_FILES)
    p.set_defaults(fn=cmd_sensitivity)

    p = sub.add_parser('review', help='evidence query for the discovery-list review')
    p.add_argument('workbook')
    p.add_argument('--regular', type=int, default=50)
    p.add_argument('--small', type=int, default=50)
    p.add_argument('--per-taxpayer', type=int, default=5)
    p.add_argument('--blind', type=int, metavar='N', help='blind review: N flagged mixed with N comparison taxpayers')
    p.add_argument('--extract', help='the extract the workbook was scored from (default data/live_<date>.csv)')
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser('blind-pack', help='the officers\' blind review workbook from the evidence CSV')
    p.add_argument('evidence')
    p.add_argument('key')
    p.set_defaults(fn=cmd_blind_pack)

    p = sub.add_parser('score', help='score one extract (the production run)')
    p.add_argument('file')
    p.add_argument('--evidence', help='CSV from the review query, added as the Entry evidence sheet')
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser('backtest', help='back-test every data/bt_*.csv')
    p.add_argument('pattern', nargs='?', default=BACKTEST_FILES)
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser('challengers', help='compare challengers and ensembles')
    p.add_argument('pattern', nargs='?', default=BACKTEST_FILES)
    p.set_defaults(fn=cmd_challengers)

    p = sub.add_parser('notebook', help='rebuild and run the notebook')
    p.add_argument('--no-run', action='store_true', help='rebuild only')
    p.set_defaults(fn=cmd_notebook)

    p = sub.add_parser('docs', help='rebuild the Word documents')
    p.set_defaults(fn=cmd_docs)

    p = sub.add_parser('pca', help='post-clearance audit list from data/pca/ (--sql writes the Hue queries)')
    p.add_argument('--sql', action='store_true', help='write the Hue queries into sql/pca/')
    p.set_defaults(fn=cmd_pca)

    p = sub.add_parser('view', help='officer view: one HTML file with the scores and the post-clearance audit list')
    p.set_defaults(fn=cmd_view)

    p = sub.add_parser('audit', help='missed-revenue workbook for NTC from data/audit/')
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser('test', help='run the automatic tests')
    p.set_defaults(fn=cmd_test)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == '__main__':
    main()
