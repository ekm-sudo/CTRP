"""A synthetic customs view (item rows) for testing: repeated rows, re-lodged entries, cancelled declarations,
vehicles, APC 483, blank original tax, same-day splits. No real data."""
import numpy as np, pandas as pd
def make(seed=3, n_tp=300, n_decl=40000):
    rng = np.random.default_rng(seed)
    tins = [f'10{rng.integers(10**7, 10**8)}' for _ in range(n_tp)]
    tins[0] = '12345'                                  # invalid TIN
    act = rng.lognormal(0, 1.2, n_tp); act /= act.sum()
    start_day = pd.Timestamp('2014-10-01'); days = (pd.Timestamp('2026-09-30') - start_day).days
    # some taxpayers start late (new traders)
    first = {t: rng.integers(0, days) if rng.random() < .25 else 0 for t in tins}
    hs = ['04011000000','17011490000','72139110000','87032390000','85171200000','25232900000','27101900000',
          '39269090000','84713000000','62034200000','30049000000','10063000000','73170000000','85044000000','87032390000','87089900000','87112000000']
    D = []
    for i in range(n_decl):
        t = tins[rng.choice(n_tp, p=act)]
        dd = start_day + pd.Timedelta(days=int(rng.integers(first[t], days + 1)))
        D.append((str(5000000 + i), t, dd.strftime('%Y%m%d')))
    decl = pd.DataFrame(D, columns=['instance_id', 'taxpayer_tin', 'assessment_dt_wid'])
    # same-day splits: copy some declarations to the same day/tin
    extra = decl.sample(3000, random_state=seed).copy(); extra['instance_id'] = [str(9000000 + i) for i in range(len(extra))]
    decl = pd.concat([decl, extra], ignore_index=True)
    decl['entry_num'] = ['C' + str(100000 + i) for i in range(len(decl))]
    decl['dec_ref_yer'] = decl['assessment_dt_wid'].str[:4]
    # re-lodged entries: the same entry number, station and year under a second, higher declaration ID
    re = decl.sample(400, random_state=seed + 1).copy(); re['instance_id'] = [str(9500000 + i) for i in range(len(re))]
    decl = pd.concat([decl, re], ignore_index=True)
    n = len(decl)
    decl['regime_cd'] = rng.choice(['IM4', 'IM7', 'EX1'], n, p=[.75, .2, .05])
    decl['decl_status'] = rng.choice(['Paid', 'Totally exited', 'Cancelled', None], n, p=[.6, .35, .04, .01])
    decl['top_up_flg'] = np.where(rng.random(n) < .15, 'Y', 'N')
    decl['amendment_flg'] = np.where(rng.random(n) < .12, 'Y', 'N')
    st = rng.choice(['UGKLA', 'UGEB1', 'UGMAL', 'UGBUS', None], n, p=[.6, .15, .12, .12, .01])
    keep_st = decl.groupby('entry_num').cumcount() > 0          # a re-lodged entry keeps its station
    decl['clearance_station_cd'] = st
    first_st = decl.groupby('entry_num')['clearance_station_cd'].transform('first')
    decl.loc[keep_st, 'clearance_station_cd'] = first_st[keep_st]
    decl['is_red_flg'] = (rng.random(n) < .3).astype(int); decl['is_yellow_flg'] = (rng.random(n) < .4).astype(int)
    decl['pay_status'] = rng.choice(['FULLY_PAID', 'NOT_PAID'], n, p=[.93, .07])
    decl['extended_proc_cd'] = rng.choice(['4000', '4071', '7181', '4080'], n, p=[.7, .15, .1, .05])
    decl['preferential_treatment_flag'] = np.where(rng.random(n) < .1, 'Y', 'N')
    orig = rng.integers(1e5, 5e7, n).astype(float)
    final = np.where(rng.random(n) < .2, orig * rng.uniform(1.05, 1.8, n), orig)
    final = np.where(rng.random(n) < .03, orig * .8, final)
    decl['final_amt'] = final
    decl['original_tax_amt'] = np.where(rng.random(n) < .4, np.nan, orig)          # blank = unchanged
    decl['top_up_amt'] = np.where(decl['top_up_flg'] == 'Y', final - orig, final)
    decl['taxpayer_nm'] = 'NAME ' + decl['taxpayer_tin'].str[-3:]
    decl['consignee_nm'] = decl['taxpayer_nm']
    rows = []
    for r in decl.itertuples(index=False):
        k = int(rng.integers(1, 5))
        for j in range(1, k + 1):
            h = hs[int(rng.integers(len(hs)))]
            w = float(rng.integers(1, 20000)) if rng.random() > .02 else 0.0
            v = float(rng.integers(1e5, 2e8)) * (0.3 if rng.random() < .08 else 1) * (0.005 if rng.random() < .01 else 1)
            q = float(rng.integers(1, 500)) if rng.random() < .6 else (0.0 if rng.random() < .5 else np.nan)
            cpc = rng.choice(['000', '000', '000', '000', '405', '451', '483', '492'])
            tax = 0.0 if cpc == '405' else v * rng.uniform(0.1, 0.5) * (0.3 if rng.random() < .05 else 1)
            row = dict(r._asdict(), consignee_tin=r.taxpayer_tin, key_itm_nbr=str(j), hsc_cd=h if rng.random() > .005 else None,
                       gds_org_cty=rng.choice(['CN', 'IN', 'AE', 'KE', 'DE', None], p=[.4, .2, .15, .15, .09, .01]),
                       customs_value=v, net_weight=w, supplementary_qnty=q, tax_assessed=tax, cpc_cd=cpc)
            rows.append(row)
            if rng.random() < .05: rows.append(dict(row))                          # repeated row
    return pd.DataFrame(rows)
