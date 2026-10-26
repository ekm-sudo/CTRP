"""
Connect to the Data Lake from VS Code.

Hue runs its Spark SQL on a Spark Thrift Server. This module talks to the same server, so a
query that works in Hue works here, and the SQL files in this folder run unchanged.

The heavy work stays in the cluster: Spark reads the millions of item rows and returns one
row per taxpayer. Only that small result comes back to your machine. This is also how the
production run will work, so development and production use the same path.

SETUP (once)
  1. pip install -r requirements.txt
  2. Copy .env.example to .env and fill in the connection details from Data Engineering
     (host, port, authentication). These are the same details Hue uses.
  3. python ctrp_db.py          # runs a connection test
The password is asked for when you connect and is never written to disk.

USE
  from ctrp_db import Lake
  lake = Lake()
  df = lake.query("SELECT ...")                         # any single SQL statement
  df = lake.pull("features_2026-03-31", sql)            # same, but saved to data/ as a
                                                        # dated snapshot and reused next time
"""
import getpass
import os
import time
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATA_DIR = Path(__file__).parent / 'data'
VIEW = 'dm_modeled_ura_datascience.vw_cstm_AEO_model'

# CTRP_AUTH value -> impyla auth_mechanism
AUTH = {'LDAP': 'PLAIN', 'NONE': 'PLAIN', 'NOSASL': 'NOSASL', 'KERBEROS': 'GSSAPI'}


class Lake:
    def __init__(self):
        from impala.dbapi import connect

        auth = os.getenv('CTRP_AUTH', 'LDAP').upper()
        kwargs = dict(
            host=os.environ['CTRP_HOST'],
            port=int(os.getenv('CTRP_PORT', '10000')),
            auth_mechanism=AUTH[auth],
            use_ssl=os.getenv('CTRP_SSL', 'false').lower() == 'true',
            timeout=int(os.getenv('CTRP_TIMEOUT', '3600')),
        )
        if os.getenv('CTRP_TRANSPORT', 'binary').lower() == 'http':
            kwargs.update(use_http_transport=True, http_path=os.getenv('CTRP_HTTP_PATH', 'cliservice'))
        if auth in ('LDAP', 'NONE'):
            kwargs['user'] = os.environ['CTRP_USER']
        if auth == 'LDAP':
            kwargs['password'] = getpass.getpass(f"Password for {kwargs['user']}: ")
        if auth == 'KERBEROS':
            kwargs['kerberos_service_name'] = os.getenv('CTRP_KRB_SERVICE', 'hive')
        self.conn = connect(**kwargs)

    def query(self, sql, chunk=200_000):
        """Run ONE SQL statement and return the result as a DataFrame."""
        sql = sql.strip().rstrip(';')
        t0 = time.time()
        cur = self.conn.cursor()
        cur.execute(sql)
        cols = [c[0].split('.')[-1].lower() for c in cur.description]
        parts = []
        while True:
            rows = cur.fetchmany(chunk)
            if not rows:
                break
            parts.append(pd.DataFrame(rows, columns=cols))
        cur.close()
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
        print(f'  {len(df):,} rows in {time.time() - t0:,.0f}s')
        return df

    def pull(self, name, sql, refresh=False):
        """Run a query once and keep the result as a dated snapshot in data/<name>.parquet.

        Development works from these frozen files, so two experiments run on the same day
        or a week apart compare like with like. Pass refresh=True to fetch again.
        """
        DATA_DIR.mkdir(exist_ok=True)
        path = DATA_DIR / f'{name}.parquet'
        if path.exists() and not refresh:
            print(f'  using saved {path.name}')
            return pd.read_parquet(path)
        df = self.query(sql)
        df.to_parquet(path, index=False)
        return df


if __name__ == '__main__':
    print('Connecting...')
    lake = Lake()
    print('Test 1: the connection answers')
    print(lake.query('SELECT 1 AS ok'))
    print('Test 2: the view is readable (declarations in September 2026)')
    print(lake.query(f"SELECT COUNT(DISTINCT instance_id) AS declarations FROM {VIEW} "
                     f"WHERE assessment_dt_wid > '20260831' AND assessment_dt_wid <= '20260930'"))
    print('Connection works.')
