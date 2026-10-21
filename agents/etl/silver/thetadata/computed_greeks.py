#!/usr/bin/env python3
"""
In-house IV + greeks for silver.option_eod_quotes -> silver.option_eod_greeks
(greek_source='COMPUTED').

MODEL (documented, deterministic):
- Cox-Ross-Rubinstein binomial tree, N=200 steps, AMERICAN early exercise
  (SPY options are American/physical per silver.option_contracts).
- Discrete cash dividends via the escrowed-dividend model: the tree runs on
  S* = S0 - PV(divs with ex-date in (t, T]); at each node the exercise value
  is computed on spot = S*_node + PV_t(remaining divs). Dividend amounts and
  ex-dates come from deriv.underlying_dividends (source YAHOO_CHART_API).
- Risk-free rate: FRED DTB3 (3-month T-bill, secondary market, discount
  basis, percent) for the trade_date from bronze.fred_macro_indicators,
  carried forward over publication gaps (weekends/holidays), max 5 days.
  ACT/365 day count.
- Price basis: silver mid = (bid+ask)/2 (only where 0 < bid <= ask).

IV INVERSION: vectorized bisection on sigma in [1e-4, 5.0], 45 iterations
(sigma resolution ~1.4e-13; price tolerance effectively < 1e-6 near ATM).
Monotonicity of the American price in sigma makes bisection exact-safe.
- mid <= price(sigma_min) -> NO_SOLUTION_LOW (deep ITM / stale quote)
- mid >= price(sigma_max) -> NO_SOLUTION_HIGH
Failed solves store implied_vol/greeks NULL with the reason in model_params.

GREEKS (per share, from the same tree at the solved IV, finite differences):
- delta, gamma: dS = 0.5% of S0 central difference.
- vega:  (P(sigma+1pt) - P(sigma-1pt))/2  -> per 1 vol point (0.01).
- rho:   (P(r+1pt)     - P(r-1pt))/2      -> per 1 rate point (0.01), r floored.
- theta: P(T - 1 calendar day) - P(T), one-sided (S, sigma, r, divs fixed).
iv_error = |model_price(solved IV) - mid| (solver residual; ~0 by construction).

Idempotent: ON CONFLICT (contract_id, trade_date, greek_source) DO NOTHING and
only contract-days without a COMPUTED row are processed. One run registry row
per invocation in bronze.thetadata_ingest_runs (loader='computed_greeks.py').

Run with /usr/bin/python3 (needs numpy + db.py deps).
Usage: computed_greeks.py --symbol SPY [--start 2023-06-01] [--end 2026-10-02]
"""
import argparse
import datetime as dt
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
import db  # noqa: E402

N_STEPS = 200
SIG_LO, SIG_HI = 1e-4, 5.0
BISECT_ITERS = 32  # sigma resolution 5/2^32 ~ 1e-9; price tol < 1e-6 near ATM
DAY_COUNT = 365.0
MODEL_VERSION = 'CRR_ESCROWED_DIV_AMERICAN_V1'


def load_rates(cur) -> list:
    cur.execute("""SELECT date, value FROM bronze.fred_macro_indicators
                   WHERE series_id='DTB3' ORDER BY date""")
    return [(d, float(v) / 100.0) for d, v in cur.fetchall()]


def rate_on(rates, d: dt.date) -> float:
    """DTB3 on d, else latest within prior 5 calendar days."""
    best = None
    for rd, rv in rates:
        if rd > d:
            break
        best = (rd, rv)
    if best is None or (d - best[0]).days > 5:
        raise RuntimeError(f'no DTB3 rate within 5 days of {d}')
    return best[1]


def price_batch(sig, K, is_call, S0, r, T, divs, capture_k=None):
    """Vectorized CRR American price. sig/K/is_call: (M,) arrays; S0,r,T scalars;
    divs: list of (t_years, amount). Returns (M,) prices.
    If capture_k is not None, also returns (V_k, spot_k): the option-value and
    spot rows at tree step capture_k (shapes (capture_k+1, M)) for node-based
    delta/gamma extraction (Hull binomial greeks — avoids lattice ripple
    artifacts of S0-bump finite differences)."""
    M = sig.shape[0]
    dt_ = T / N_STEPS
    u = np.exp(sig * np.sqrt(dt_))
    d = 1.0 / u
    growth = np.exp(r * dt_)
    p = np.clip((growth - d) / (u - d), 0.0, 1.0)
    disc = np.exp(-r * dt_)

    pv_total = sum(D * np.exp(-r * ti) for ti, D in divs)
    Sstar0 = S0 - pv_total
    if Sstar0 <= 0:  # dividends exceed spot — degenerate; return intrinsic floor
        intr = np.where(is_call, np.maximum(S0 - K, 0.0), np.maximum(K - S0, 0.0))
        return intr.astype(float)

    jT = np.arange(N_STEPS + 1)[:, None]                      # (N+1, 1)
    Sstar_T = Sstar0 * (u[None, :] ** jT) * (d[None, :] ** (N_STEPS - jT))
    Kb = K[None, :]
    V = np.where(is_call[None, :], np.maximum(Sstar_T - Kb, 0.0),
                 np.maximum(Kb - Sstar_T, 0.0))

    # PV of remaining dividends per step k (scalar per k)
    pv_rem = np.zeros(N_STEPS + 1)
    for ti, D in divs:
        ks = np.where(np.arange(N_STEPS + 1) * dt_ < ti - 1e-12)[0]
        if len(ks):
            pv_rem[ks] += D * np.exp(-r * (ti - np.arange(N_STEPS + 1)[ks] * dt_))

    Srow = Sstar_T  # row for current k (starts at k=N)
    Vcap = Scap = None
    for k in range(N_STEPS - 1, -1, -1):
        V = disc * (p[None, :] * V[1:] + (1.0 - p[None, :]) * V[:-1])
        Srow = Srow[:-1] / d[None, :]                          # S*_{k,j}, j=0..k
        spot = Srow + pv_rem[k]
        ex = np.where(is_call[None, :], np.maximum(spot - Kb, 0.0),
                      np.maximum(Kb - spot, 0.0))
        V = np.maximum(V, ex)
        if capture_k is not None and k == capture_k:
            Vcap, Scap = V.copy(), spot.copy()
    if capture_k is not None:
        return V[0], Vcap, Scap
    return V[0]


def solve_group(S0, r, T, divs, K, is_call, mid):
    """Bisection IV solve for one (date, expiry) group. Returns
    (sigma, iv_err, status) arrays; sigma NaN where unsolved."""
    M = K.shape[0]
    lo = np.full(M, SIG_LO)
    hi = np.full(M, SIG_HI)
    p_lo = price_batch(lo, K, is_call, S0, r, T, divs)
    p_hi = price_batch(hi, K, is_call, S0, r, T, divs)
    status = np.array(['OK'] * M, dtype=object)
    status[mid <= p_lo] = 'NO_SOLUTION_LOW'
    status[mid >= p_hi] = 'NO_SOLUTION_HIGH'
    solvable = status == 'OK'
    for _ in range(BISECT_ITERS):
        if not solvable.any():
            break
        mids = np.where(solvable, (lo + hi) / 2.0, SIG_LO)
        pm = price_batch(mids, K, is_call, S0, r, T, divs)
        up = pm < mid
        lo = np.where(solvable & up, mids, lo)
        hi = np.where(solvable & ~up, mids, hi)
    sig = np.where(solvable, (lo + hi) / 2.0, np.nan)
    return sig, status


def greeks_group(S0, r, T, divs, K, is_call, sig):
    """Finite-difference greeks at solved sigma. NaN sigma -> NaN greeks."""
    ok = ~np.isnan(sig)
    out = {k: np.full(K.shape[0], np.nan)
           for k in ('price', 'delta', 'gamma', 'theta', 'vega', 'rho')}
    if not ok.any():
        return out
    s = np.where(ok, sig, 0.2)
    P0, V2, S2 = price_batch(s, K, is_call, S0, r, T, divs, capture_k=2)
    # Hull binomial greeks from the three step-2 nodes (per contract)
    v0, v1, v2 = V2[0], V2[1], V2[2]
    s0_, s1_, s2_ = S2[0], S2[1], S2[2]
    d_down = (v1 - v0) / (s1_ - s0_)
    d_up = (v2 - v1) / (s2_ - s1_)
    out['price'] = np.where(ok, P0, np.nan)
    out['delta'] = np.where(ok, (v2 - v0) / (s2_ - s0_), np.nan)
    out['gamma'] = np.where(ok, (d_up - d_down) / ((s2_ - s0_) / 2.0), np.nan)
    s_up = s + 0.01
    s_dn = np.maximum(s - 0.01, 1e-4)
    out['vega'] = np.where(
        ok, (price_batch(s_up, K, is_call, S0, r, T, divs)
             - price_batch(s_dn, K, is_call, S0, r, T, divs))
        / (s_up - s_dn) * 0.01, np.nan)  # per 1 vol point
    r_up, r_dn = r + 0.01, max(r - 0.01, 0.0)
    out['rho'] = np.where(
        ok, (price_batch(s, K, is_call, S0, r_up, T, divs)
             - price_batch(s, K, is_call, S0, r_dn, T, divs))
        / (r_up - r_dn) * 0.01, np.nan)  # per 1 rate point
    T1 = T - 1.0 / DAY_COUNT
    if T1 > 1e-6:
        # shift dividend times by the elapsed day (t_i measured from trade date)
        divs1 = [(ti - 1.0 / DAY_COUNT, D) for ti, D in divs
                 if ti - 1.0 / DAY_COUNT > 0]
        P1 = price_batch(s, K, is_call, S0, r, T1, divs1)
        out['theta'] = np.where(ok, P1 - P0, np.nan)  # per calendar day
    else:
        intr = np.where(is_call, np.maximum(S0 - K, 0.0), np.maximum(K - S0, 0.0))
        out['theta'] = np.where(ok, intr - P0, np.nan)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbol', default='SPY')
    ap.add_argument('--start', default=None)
    ap.add_argument('--end', default=None)
    args = ap.parse_args()

    conn = db.get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    rates = load_rates(cur)
    cur.execute("""SELECT ex_date, amount FROM deriv.underlying_dividends
                   WHERE underlying=%s ORDER BY ex_date""", (args.symbol,))
    div_rows = [(d, float(a)) for d, a in cur.fetchall()]

    where, params = 'c.underlying = %s', [args.symbol]
    if args.start:
        where += ' AND q.trade_date >= %s'
        params.append(args.start)
    if args.end:
        where += ' AND q.trade_date <= %s'
        params.append(args.end)
    cur.execute(
        f"""SELECT q.contract_id, q.trade_date, c.expiry, c.strike, c.option_right,
                   q.mid, q.underlying_close
            FROM silver.option_eod_quotes q
            JOIN silver.option_contracts c USING (contract_id)
            WHERE {where} AND q.mid IS NOT NULL AND q.underlying_close IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM silver.option_eod_greeks g
                              WHERE g.contract_id = q.contract_id
                                AND g.trade_date = q.trade_date
                                AND g.greek_source = 'COMPUTED')
            ORDER BY q.trade_date, c.expiry""", params)
    rows = cur.fetchall()
    print(f'{len(rows)} contract-days to compute', flush=True)
    if not rows:
        conn.close()
        return

    cur.execute(
        """INSERT INTO bronze.thetadata_ingest_runs
           (loader, source_endpoint, request_params) VALUES (%s,%s,%s)
           RETURNING ingest_run_id""",
        ('computed_greeks.py', 'COMPUTED_CRR_V1',
         json.dumps({'symbol': args.symbol, 'start': args.start, 'end': args.end,
                     'model': MODEL_VERSION, 'steps': N_STEPS,
                     'rate_type': 'FRED_DTB3', 'day_count': 'ACT/365',
                     'price_basis': 'mid'})))
    run_id = cur.fetchone()[0]
    conn.commit()

    inserted = failed = 0
    fail_reasons = {}
    i = 0
    # group by (trade_date, expiry)
    from itertools import groupby
    rows_sorted = sorted(rows, key=lambda r: (r[1], r[2]))
    for (tdate, expiry), grp in groupby(rows_sorted, key=lambda r: (r[1], r[2])):
        g = list(grp)
        S0 = float(g[0][6])
        r = rate_on(rates, tdate)
        T = (expiry - tdate).days / DAY_COUNT
        divs = [((ex - tdate).days / DAY_COUNT, amt) for ex, amt in div_rows
                if tdate < ex <= expiry]
        K = np.array([float(x[3]) for x in g])
        is_call = np.array([x[4] == 'C' for x in g])
        mid = np.array([float(x[5]) for x in g])

        sig, status = solve_group(S0, r, T, divs, K, is_call, mid)
        gr = greeks_group(S0, r, T, divs, K, is_call, sig)
        iv_err = np.where(np.isnan(sig), np.nan, np.abs(gr['price'] - mid))

        for idx, x in enumerate(g):
            mp = {'model': MODEL_VERSION, 'steps': N_STEPS,
                  'rate_type': 'FRED_DTB3', 'rate_value': round(r, 6),
                  'dividend_model': 'escrowed_discrete',
                  'dividends_in_window': [d[1] for d in divs],
                  'day_count': 'ACT/365', 'price_basis': 'mid',
                  'vega_per': '1pt', 'rho_per': '1pt', 'theta_per': 'calendar_day'}
            if status[idx] != 'OK':
                mp['solve_status'] = status[idx]
                failed += 1
                fail_reasons[status[idx]] = fail_reasons.get(status[idx], 0) + 1
            cur.execute(
                """INSERT INTO silver.option_eod_greeks
                   (contract_id, trade_date, implied_vol, delta, gamma, theta,
                    vega, rho, iv_error, underlying_price, greek_source,
                    model_params, ingest_run_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'COMPUTED',%s,%s)
                   ON CONFLICT (contract_id, trade_date, greek_source) DO NOTHING""",
                (x[0], tdate,
                 None if np.isnan(sig[idx]) else round(float(sig[idx]), 6),
                 None if np.isnan(gr['delta'][idx]) else round(float(gr['delta'][idx]), 6),
                 None if np.isnan(gr['gamma'][idx]) else round(float(gr['gamma'][idx]), 6),
                 None if np.isnan(gr['theta'][idx]) else round(float(gr['theta'][idx]), 6),
                 None if np.isnan(gr['vega'][idx]) else round(float(gr['vega'][idx]), 6),
                 None if np.isnan(gr['rho'][idx]) else round(float(gr['rho'][idx]), 6),
                 None if np.isnan(iv_err[idx]) else float(iv_err[idx]),
                 S0, json.dumps(mp), run_id))
            inserted += cur.rowcount
        conn.commit()
        i += len(g)
        if i % 20000 < len(g):
            print(f'progress {i}/{len(rows)} ({tdate})', flush=True)

    cur.execute(
        """UPDATE bronze.thetadata_ingest_runs
           SET finished_at=now(), status='SUCCESS', rows_fetched=%s,
               rows_inserted=%s
           WHERE ingest_run_id=%s""",
        (len(rows), inserted, run_id))
    conn.commit()
    print(json.dumps({'run_id': str(run_id), 'considered': len(rows),
                      'inserted': inserted, 'solve_failed': failed,
                      'fail_reasons': fail_reasons}, indent=2))
    conn.close()


if __name__ == '__main__':
    main()
