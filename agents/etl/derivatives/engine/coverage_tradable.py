#!/usr/bin/env python3
"""Solve coverage restricted to the tradable region (10-40 delta puts,
7-60 DTE), and NO_SOLUTION_LOW breakdown by moneyness/DTE.

Overall 90.64% is the wrong number. This reports:
- delta-band solved puts: moneyness (K/F) quantiles of the 10-40d band
- estimated tradable-region membership for ALL put rows via that K/F band,
  and % solved inside it
- NO_SOLUTION_LOW counts by K/F bucket x DTE bucket
- whether failed rows have bid=0 (zero-bid microstructure, not model failure)
"""
import sys, math, datetime as dt, traceback
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/silver/thetadata')
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
import db
from computed_greeks import load_rates, rate_on


def main():
    conn = db.get_connection()
    cur = conn.cursor()
    rates = load_rates(cur)
    cur.execute("SELECT ex_date, amount FROM deriv.underlying_dividends WHERE underlying='SPY' ORDER BY 1")
    div_rows = [(d, float(a)) for d, a in cur.fetchall()]

    cur.execute("""
        SELECT g.trade_date, c.expiry, c.strike, g.delta, g.implied_vol,
               COALESCE(g.model_params->>'solve_status','OK') AS status,
               q.mid, q.bid, q.ask, q.underlying_close
        FROM silver.option_eod_greeks g
        JOIN silver.option_contracts c USING (contract_id)
        JOIN silver.option_eod_quotes q
          ON q.contract_id = g.contract_id AND q.trade_date = g.trade_date
        WHERE c.underlying='SPY' AND c.option_right='P'
          AND g.greek_source='COMPUTED'
          AND (c.expiry - g.trade_date) BETWEEN 7 AND 60
          AND q.underlying_close IS NOT NULL
    """)
    rows = cur.fetchall()
    n_all = len(rows)
    print(f'puts 7-60 DTE rows: {n_all}')

    # forward per (date, expiry) for moneyness K/F
    fwd_cache = {}
    def fwd(d, expiry, S):
        key = (d, expiry)
        if key not in fwd_cache:
            T = (expiry - d).days / 365.0
            r = rate_on(rates, d)
            pv = sum(a * math.exp(-r * ((ex - d).days / 365.0))
                     for ex, a in div_rows if d < ex <= expiry)
            fwd_cache[key] = (S - pv) * math.exp(r * T)
        return fwd_cache[key]

    recs = []
    for d, expiry, K, delta, iv, status, mid, bid, ask, S in rows:
        K, S = float(K), float(S)
        F = fwd(d, expiry, S)
        dte = (expiry - d).days
        recs.append({'d': d, 'dte': dte, 'KF': K / F, 'delta': float(delta) if delta is not None else None,
                     'status': status, 'mid': float(mid) if mid is not None else None,
                     'bid': float(bid) if bid is not None else None})

    solved = [r for r in recs if r['status'] == 'OK']
    band = [r for r in solved if r['delta'] is not None and -0.40 <= r['delta'] <= -0.10]
    kfs = sorted(r['KF'] for r in band)
    if not kfs:
        print('FAIL: no solved 10-40d puts', file=sys.stderr)
        sys.exit(1)
    q = lambda p: kfs[min(len(kfs) - 1, int(p * len(kfs)))]
    kf_lo, kf_hi = q(0.01), q(0.99)
    print(f'10-40d puts (solved): n={len(band)}; K/F p1={q(0.01):.4f} p5={q(0.05):.4f} '
          f'p50={q(0.5):.4f} p95={q(0.95):.4f} p99={q(0.99):.4f}')

    # estimated region for ALL rows by K/F band
    region = [r for r in recs if kf_lo <= r['KF'] <= kf_hi]
    region_ok = [r for r in region if r['status'] == 'OK']
    print(f'estimated tradable region (K/F in [{kf_lo:.4f},{kf_hi:.4f}]): '
          f'{len(region)} rows, solved {len(region_ok)} = {len(region_ok)/len(region):.2%}')

    # stricter core: K/F in p5..p95
    core_lo, core_hi = q(0.05), q(0.95)
    core = [r for r in recs if core_lo <= r['KF'] <= core_hi]
    core_ok = [r for r in core if r['status'] == 'OK']
    print(f'core band (K/F p5-p95 [{core_lo:.4f},{core_hi:.4f}]): '
          f'{len(core)} rows, solved {len(core_ok)} = {len(core_ok)/len(core):.2%}')

    # NO_SOLUTION_LOW breakdown
    low = [r for r in recs if r['status'] == 'NO_SOLUTION_LOW']
    print(f'\nNO_SOLUTION_LOW total: {len(low)} ({len(low)/n_all:.2%} of puts 7-60 DTE)')
    zero_bid = sum(1 for r in low if r['bid'] is not None and r['bid'] <= 0)
    print(f'  of which bid=0: {zero_bid} ({zero_bid/max(len(low),1):.1%})')
    mb = [('<0.80', lambda x: x < 0.80), ('0.80-0.90', lambda x: 0.80 <= x < 0.90),
          ('0.90-0.95', lambda x: 0.90 <= x < 0.95), ('0.95-1.00', lambda x: 0.95 <= x < 1.00),
          ('1.00-1.05', lambda x: 1.00 <= x < 1.05), ('1.05-1.15', lambda x: 1.05 <= x < 1.15),
          ('>1.15', lambda x: x >= 1.15)]
    db_ = [('7-21', lambda x: 7 <= x <= 21), ('22-45', lambda x: 22 <= x <= 45),
           ('46-60', lambda x: 46 <= x <= 60)]
    print('  K/F bucket x DTE bucket (count, % of LOW):')
    header = '  {:10s}'.format('') + ''.join(f'{bl:>8s}' for bl, _ in db_)
    print(header)
    for ml, mf in mb:
        cells = []
        for dl, df in db_:
            c = sum(1 for r in low if mf(r['KF']) and df(r['dte']))
            cells.append(f'{c:>8d}')
        print('  {:10s}'.format(ml) + ''.join(cells))
    # all-rows reference: same buckets across ALL puts for context
    print('\n  all-puts distribution for reference (count):')
    print(header)
    for ml, mf in mb:
        cells = []
        for dl, df in db_:
            c = sum(1 for r in recs if mf(r['KF']) and df(r['dte']))
            cells.append(f'{c:>8d}')
        print('  {:10s}'.format(ml) + ''.join(cells))
    conn.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
