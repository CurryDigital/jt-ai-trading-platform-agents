#!/usr/bin/env python3
"""Quantify the early-exercise premium (EEP) embedded in the engine's fills.

The engine SELLS American SPY options at market prices (which include EEP)
but models them as European (hold to expiry, settle at intrinsic). EEP per
roll = american_price - european_price at fill IV. Annualized vs nav0 this is
the structural overcollection candidate for the KAT residual.

European price: Black-Scholes on S_adj = S - PV(discrete divs) (escrowed
model, consistent with the CRR build). American: computed_greeks.price_batch.
IV: our COMPUTED implied_vol at that contract/date; fallback: solve off fill.
"""
import sys, math, traceback
from math import log, sqrt, exp, erf
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/silver/thetadata')
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
import db
from computed_greeks import load_rates, rate_on, price_batch
import numpy as np

MULT = 100
N = lambda x: 0.5 * (1.0 + erf(x / sqrt(2.0)))


def bs(S, K, T, r, sig, is_call, pv_divs):
    Sa = S - pv_divs
    if Sa <= 0 or sig <= 0 or T <= 0:
        intr = max(Sa - K, 0) if is_call else max(K - Sa, 0)
        return intr
    d1 = (log(Sa / K) + (r + sig * sig / 2) * T) / (sig * sqrt(T))
    d2 = d1 - sig * sqrt(T)
    if is_call:
        return Sa * N(d1) - K * exp(-r * T) * N(d2)
    return K * exp(-r * T) * N(-d2) - Sa * N(-d1)


def main():
    conn = db.get_connection()
    cur = conn.cursor()
    rates = load_rates(cur)
    cur.execute("SELECT ex_date, amount FROM deriv.underlying_dividends WHERE underlying='SPY' ORDER BY 1")
    div_rows = [(d, float(a)) for d, a in cur.fetchall()]
    cur.execute("""SELECT trade_date, payload->>'close' FROM bronze.thetadata_stock_eod_raw
                   WHERE symbol='SPY'""")
    close = {d: float(c) for d, c in cur.fetchall()}

    cur.execute("""
        SELECT DISTINCT ON (index_name, params->>'fill_frac') run_id, index_name
        FROM deriv.kat_runs WHERE verdict IS NOT NULL AND params->>'fill_frac'='1.0'
        ORDER BY index_name, params->>'fill_frac', created_at DESC""")
    runs = cur.fetchall()

    for run_id, idx in runs:
        is_call = idx == 'BXM'
        cur.execute("""SELECT roll_date, expiry, strike, contract_id, fill_price
                       FROM deriv.kat_trades WHERE run_id=%s ORDER BY roll_date""", (run_id,))
        trades = cur.fetchall()
        cur.execute("SELECT nav FROM deriv.kat_daily WHERE run_id=%s ORDER BY trade_date LIMIT 1", (run_id,))
        nav0 = float(cur.fetchone()[0])
        cur.execute("SELECT min(trade_date), max(trade_date) FROM deriv.kat_daily WHERE run_id=%s", (run_id,))
        d0, d1 = cur.fetchone()
        yrs = (d1 - d0).days / 365.25

        total_eep = 0.0
        n_ok = 0
        details = []
        for roll, expiry, K, cid, fill in trades:
            K = float(K)
            S = close.get(roll)
            if S is None:
                continue
            T = (expiry - roll).days / 365.0
            r = rate_on(rates, roll)
            divs = [((ex - roll).days / 365.0, a) for ex, a in div_rows if roll < ex <= expiry]
            pv = sum(a * exp(-r * t) for t, a in divs)
            cur.execute("""SELECT implied_vol FROM silver.option_eod_greeks
                           WHERE contract_id=%s AND trade_date=%s AND greek_source='COMPUTED'""",
                        (cid, roll))
            row = cur.fetchone()
            if not row or row[0] is None:
                continue
            iv = float(row[0])
            am = price_batch(np.array([iv]), np.array([K]), np.array([is_call]),
                             S, r, T, divs)[0]
            eu = bs(S, K, T, r, iv, is_call, pv)
            eep = am - eu
            total_eep += eep * MULT
            n_ok += 1
            details.append((roll, eep, iv))
        ann = total_eep / nav0 / yrs
        print(f'{idx}: trades priced={n_ok}/{len(trades)} EEP total=${total_eep:.0f} '
              f'-> {ann*100:+.2f}%/yr of nav0 (vs KAT residual +3.77 BXM / +2.78 PUT)')
        top = sorted(details, key=lambda x: -x[1])[:3]
        for roll, eep, iv in top:
            print(f'    max EEP: {roll} ${eep:.3f}/share (iv={iv*100:.1f}%)')
    conn.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
