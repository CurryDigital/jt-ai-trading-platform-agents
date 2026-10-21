#!/usr/bin/env python3
"""IV-level diagnosis for the computed-greeks IV flag (H1 showed our SPY 30D ATM
IV runs ~3 vol pts under VIX, and 28.8% vs the 35-55% anchor on 2024-08-05).

PART A - timestamp alignment (option NBBO last <=16:15 ET, report 17:15; stock
close 16:00). Via put-call parity at the forward-ATM strike, nearest-30D expiry:
    residual = (C_mid - P_mid) - (S - PV(divs) - K*exp(-rT))   [$ / share]
residual != 0 measures option-vs-stock timestamp (and microstructure) mismatch.
IV impact = residual / (vega_C + vega_P)  [vol pts; vega is per 1 vol pt].
Also: last_trade_at time-of-day distribution for those ATM options.

PART B - inputs actually used on 2024-08-05: DTB3 value/date, discrete
dividends in the 30D window, forward vs spot ATM strike selection, IV at each.

PART C - forward-vs-spot ATM selection across all dates: how often K*(F) != K*(S).
"""
import sys, math, datetime as dt, traceback
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/silver/thetadata')
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
import db
from computed_greeks import load_rates, rate_on

WIN_START = dt.date(2023, 6, 1)
WIN_END = dt.date(2026, 10, 1)


def pctiles(xs, ps=(50, 90, 99)):
    xs = sorted(xs)
    n = len(xs)
    return {p: xs[min(n - 1, int(p / 100 * n))] for p in ps}


def main():
    conn = db.get_connection()
    cur = conn.cursor()
    rates = load_rates(cur)
    cur.execute("SELECT ex_date, amount FROM deriv.underlying_dividends WHERE underlying='SPY' ORDER BY 1")
    div_rows = [(d, float(a)) for d, a in cur.fetchall()]

    cur.execute("""
        SELECT g.trade_date, c.expiry, c.strike, c.option_right,
               g.implied_vol, g.vega, q.mid, q.underlying_close,
               (q.last_trade_at AT TIME ZONE 'America/New_York')::time AS lt_local,
               q.bid, q.ask
        FROM silver.option_eod_greeks g
        JOIN silver.option_contracts c USING (contract_id)
        JOIN silver.option_eod_quotes q
          ON q.contract_id = g.contract_id AND q.trade_date = g.trade_date
        WHERE g.trade_date BETWEEN %s AND %s
          AND c.underlying = 'SPY' AND g.greek_source = 'COMPUTED'
          AND g.implied_vol IS NOT NULL AND q.mid IS NOT NULL
          AND q.underlying_close IS NOT NULL
          AND (c.expiry - g.trade_date) BETWEEN 25 AND 35
        ORDER BY g.trade_date, c.expiry, c.strike
    """, (WIN_START, WIN_END))
    rows = cur.fetchall()
    print(f'ATM-band candidate rows (25-35 DTE, solved): {len(rows)}')

    by_de = {}
    for (d, expiry, K, right, iv, vega, mid, S, lt, bid, ask) in rows:
        by_de.setdefault((d, expiry), []).append(
            {'K': float(K), 'right': right, 'iv': float(iv), 'vega': float(vega),
             'mid': float(mid), 'S': float(S), 'lt': lt, 'bid': float(bid), 'ask': float(ask)})

    recs = []
    fwd_spot_diff = 0
    for (d, expiry), chain in sorted(by_de.items()):
        S = chain[0]['S']
        T = (expiry - d).days / 365.0
        r = rate_on(rates, d)
        pv = sum(a * math.exp(-r * ((ex - d).days / 365.0))
                 for ex, a in div_rows if d < ex <= expiry)
        F = (S - pv) * math.exp(r * T)
        strikes = {}
        for c in chain:
            strikes.setdefault(c['K'], {})[c['right']] = c
        both = {K: v for K, v in strikes.items() if 'C' in v and 'P' in v}
        if not both:
            continue
        Kf = min(both, key=lambda k: abs(k - F))
        Ks = min(both, key=lambda k: abs(k - S))
        if Kf != Ks:
            fwd_spot_diff += 1
        c, p = both[Kf]['C'], both[Kf]['P']
        parity_fwd = S - pv - Kf * math.exp(-r * T)
        resid = (c['mid'] - p['mid']) - parity_fwd
        vega_sum = c['vega'] + p['vega']
        iv_pts = resid / vega_sum if vega_sum > 0 else None
        recs.append({'date': d, 'expiry': expiry, 'T': T, 'S': S, 'F': F, 'K': Kf,
                     'Ks': Ks, 'r': r, 'pv_divs': pv,
                     'C': c['mid'], 'P': p['mid'], 'resid': resid,
                     'iv_pts': iv_pts, 'iv_C': c['iv'], 'iv_P': p['iv'],
                     'lt_C': c['lt'], 'lt_P': p['lt'],
                     'bidC': c['bid'], 'askC': c['ask'],
                     'bidP': p['bid'], 'askP': p['ask']})

    n = len(recs)
    print(f'ATM parity points: {n}')
    abs_r = [abs(x['resid']) for x in recs]
    abs_iv = [abs(x['iv_pts']) for x in recs if x['iv_pts'] is not None]
    pr = pctiles(abs_r)
    piv = pctiles(abs_iv)
    print('PART A - parity residual |C-P - forward_parity| ($/share): '
          f'mean={sum(abs_r)/n:.3f} p50={pr[50]:.3f} p90={pr[90]:.3f} p99={pr[99]:.3f}')
    print(f'        signed mean={sum(x["resid"] for x in recs)/n:+.3f} '
          f'(positive => option-implied underlying ABOVE 16:00 stock close)')
    print('PART A - same in vol pts (resid / straddle vega): '
          f'mean={sum(abs_iv)/len(abs_iv):.2f} p50={piv[50]:.2f} p90={piv[90]:.2f} p99={piv[99]:.2f}')

    close1600 = dt.time(16, 0)
    lts = [x['lt_C'] for x in recs if x['lt_C']] + [x['lt_P'] for x in recs if x['lt_P']]
    before = sum(1 for t in lts if t < close1600)
    at_or_after = sum(1 for t in lts if t >= close1600)
    med_t = sorted(lts)[len(lts) // 2]
    print(f'PART A - ATM option last_trade_at (ET): n={len(lts)} median={med_t} '
          f'before 16:00: {before} ({before/len(lts):.1%}), >=16:00: {at_or_after} ({at_or_after/len(lts):.1%})')

    for label, lo, hi in (('2024-07-24..2024-08-05', dt.date(2024, 7, 24), dt.date(2024, 8, 5)),
                          ('2025-03..2025-04', dt.date(2025, 3, 1), dt.date(2025, 4, 30))):
        w = [x for x in recs if lo <= x['date'] <= hi]
        if w:
            wa = [abs(x['resid']) for x in w]
            wi = [abs(x['iv_pts']) for x in w if x['iv_pts'] is not None]
            wp = pctiles(wa)
            wpi = pctiles(wi)
            print(f'  {label}: n={len(w)} |resid|$ mean={sum(wa)/len(wa):.3f} p50={wp[50]:.3f} p90={wp[90]:.3f}; '
                  f'|IV pts| mean={sum(wi)/len(wi):.2f} p90={wpi[90]:.2f}')

    # 2024-08-05 detail
    x = next((r for r in recs if r['date'] == dt.date(2024, 8, 5)), None)
    if x:
        print('\n2024-08-05 ATM detail:')
        print(f"  S(16:00 close)={x['S']:.2f}  F(30D)={x['F']:.2f}  K*={x['K']:.2f} "
              f"(K*_spot={x['Ks']:.2f})  expiry={x['expiry']}  r={x['r']:.4f}  PV(divs)={x['pv_divs']:.3f}")
        print(f"  C_mid={x['C']:.2f} (bid/ask {x['bidC']:.2f}/{x['askC']:.2f}, last {x['lt_C']})  "
              f"P_mid={x['P']:.2f} (bid/ask {x['bidP']:.2f}/{x['askP']:.2f}, last {x['lt_P']})")
        print(f"  parity residual={x['resid']:+.3f}$/share  ->  IV impact={x['iv_pts']:+.2f} vol pts")
        print(f"  solved IV: call={x['iv_C']*100:.2f}% put={x['iv_P']*100:.2f}%")
        print(f"  implied: option market traded as if SPY were {x['S']+x['resid']:.2f} "
              f"({(x['resid']/x['S'])*100:+.2f}% vs 16:00 close)")

    # PART B - inputs on 2024-08-05
    print('\nPART B - model inputs on 2024-08-05:')
    cur.execute("""SELECT date, value FROM bronze.fred_macro_indicators
                   WHERE series_id='DTB3' AND date <= '2024-08-05'
                   ORDER BY date DESC LIMIT 3""")
    print('  DTB3 latest<=2024-08-05:', [(str(d), float(v)) for d, v in cur.fetchall()])
    cur.execute("""SELECT DISTINCT model_params->>'rate_value' AS rv,
                          model_params->'dividends_in_window' AS dw
                   FROM silver.option_eod_greeks g
                   JOIN silver.option_contracts c USING (contract_id)
                   WHERE g.trade_date='2024-08-05' AND c.underlying='SPY'
                     AND (c.expiry - g.trade_date) BETWEEN 25 AND 35
                     AND g.greek_source='COMPUTED' LIMIT 5""")
    for rv, dw in cur.fetchall():
        print(f'  model_params rate_value={rv} dividends_in_window={dw}')
    cur.execute("""SELECT ex_date, amount FROM deriv.underlying_dividends
                   WHERE underlying='SPY' AND ex_date > '2024-08-05'
                   ORDER BY 1 LIMIT 2""")
    print('  next SPY divs after 2024-08-05:', [(str(d), float(a)) for d, a in cur.fetchall()])

    print(f'\nPART C - forward-vs-spot ATM strike selection: K*(F)!=K*(S) on '
          f'{fwd_spot_diff}/{n} dates ({fwd_spot_diff/n:.1%})')
    conn.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
