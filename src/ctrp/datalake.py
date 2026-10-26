"""
Pull query results straight from the data lake into data/, instead of downloading them from Hue.

What: runs one of our saved queries (a file in sql/) on the Spark Thrift Server through the Simba Spark ODBC
      driver, and writes the result as a CSV under the name the project expects. Rows are written in batches,
      so a large result never has to fit in memory, and there is no 100,000-row cap.
Why:  every Hue download had to be started, saved and renamed by hand, and Hue stops a download at 100,000 rows.
Where: on the jump server. The Thrift Server port (2304) is closed to laptops; Hue is not, which is why Hue
      worked from the laptop and this does not.

Login: your own data lake username and password (not the shared mapr account). Either set them for the session:
           set CTRP_DATALAKE_USER=yourname
           set CTRP_DATALAKE_PASSWORD=...
       or leave them unset and the command asks (the password is not shown as you type). Never put them in code.

    python main.py pull --test                        check the connection (a tiny query)
    python main.py pull bt_2023-09-30                 sql/bt_2023-09-30.sql -> data/bt_2023-09-30.csv
    python main.py pull sql/audit/audit_02_below_peers_since_july.sql data/audit/below_peers_since_july.csv
    python main.py pull --run-order                   every query in sql/V3_RUN_ORDER.txt whose file is not in data/ yet
"""
import csv
import getpass
import os
import re
import time
from pathlib import Path

from ctrp.utils import PROJECT_ROOT, SQL_DIR

HOST = 'uradfnode5.ura.go.ug'
PORT = 2304
DRIVER = 'Simba Spark ODBC Driver'      # the driver name as Windows lists it in "ODBC Data Sources (64-bit)"
BATCH = 50_000                          # rows fetched and written at a time
RUN_ORDER = SQL_DIR / 'V3_RUN_ORDER.txt'


def connect():
    """Open a connection to the Spark Thrift Server with your own login."""
    import pyodbc                                       # only needed on the machine that pulls data
    user = os.environ.get('CTRP_DATALAKE_USER') or input('Data lake username: ')
    password = os.environ.get('CTRP_DATALAKE_PASSWORD') or getpass.getpass('Data lake password: ')
    settings = {
        'Driver': '{%s}' % DRIVER,
        'Host': HOST,
        'Port': PORT,
        'SparkServerType': 3,       # Spark Thrift Server
        'AuthMech': 3,              # user name and password
        'ThriftTransport': 1,       # SASL, as in the jump server's DSN
        'UseNativeQuery': 1,        # send our Spark SQL as it is (the driver would otherwise rewrite it)
        'UID': user,
        'PWD': password,
    }
    return pyodbc.connect(';'.join(f'{k}={v}' for k, v in settings.items()), autocommit=True)


def run_to_csv(conn, sql, out_path):
    """Run one query and write every row to out_path, in batches. Returns the number of rows."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.name + '.part')      # renamed only when complete
    cursor = conn.cursor()
    cursor.execute(sql)
    header = [col[0].split('.')[-1] for col in cursor.description]
    rows = 0
    with open(partial, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        while True:
            batch = cursor.fetchmany(BATCH)
            if not batch:
                break
            writer.writerows(batch)
            rows += len(batch)
            print(f'  {rows:,} rows', end='\r')
    partial.replace(out_path)
    return rows


def pull(sql_file, out_file, conn=None):
    """Run sql_file and save the result as out_file (paths relative to the project folder)."""
    sql_path, out_path = PROJECT_ROOT / sql_file, PROJECT_ROOT / out_file
    sql = sql_path.read_text().strip().rstrip(';')
    own = conn is None
    conn = conn or connect()
    start = time.time()
    print(f'{sql_file} -> {out_file}')
    try:
        rows = run_to_csv(conn, sql, out_path)
    finally:
        if own:
            conn.close()
    print(f'  {rows:,} rows in {(time.time() - start) / 60:.1f} minutes')
    return rows


def run_order_jobs(text=None):
    """The (sql file, output file) pairs listed in sql/V3_RUN_ORDER.txt, in order."""
    text = RUN_ORDER.read_text() if text is None else text
    return re.findall(r'\[ \] (sql/\S+)\s+save as (data/\S+)', text)


def pull_run_order(force=False):
    """Every query in the run order whose output is not in data/ yet (all of them with force=True)."""
    jobs = [(s, o) for s, o in run_order_jobs() if force or not (PROJECT_ROOT / o).exists()]
    print(f'{len(jobs)} queries to run')
    conn = connect()
    try:
        for sql_file, out_file in jobs:
            try:
                pull(sql_file, out_file, conn)
            except Exception as e:                     # carry on with the rest, report at the end
                print(f'  FAILED: {str(e)[:300]}')
    finally:
        conn.close()


def test_connection():
    """A tiny query on the view: proves the login, the driver and the route to the server all work."""
    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM (SELECT 1 FROM dm_modeled_ura_datascience.vw_cstm_AEO_model LIMIT 10) t')
        print('Connected. Test query returned', cursor.fetchone()[0], 'rows (expected 10).')
    finally:
        conn.close()
