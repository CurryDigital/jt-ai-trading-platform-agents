#!/usr/bin/env python3
"""H1 (fixed): daily SPY constant-30D ATM IV (COMPUTED greeks, forward-ATM strike,
variance-interpolated across bracketing expiries) vs VIX close, 2023-06 -> 2026-10.

Method:
- For each trade_date d with SPY quotes: S = underlying_close, r = DTB3 (rate_on).
- Target tenor T30 = 30/365. Pick expiries bracketing d+30d (nearest below/above,
  must have quoted contracts that day). If 30D is outside the listed range, skip.
- Per expiry: forward F = (S - PV(dividends in (d, expiry])) * exp(r*T);
  strike K* = nearest listed to F with BOTH call and put COMPUTED IV present;
  iv_expiry = mean(iv_call, iv_put) at K*.
- Constant maturity: linear interpolation of total variance v = iv^2 * T to T30;
  iv30 = sqrt(v30 / T30).
- VIX = VIXCLS close on d (else nearest prior within 3 calendar days).
- spread = iv30*100 - VIX (vol points).

Failure policy: ANY empty input or >20% of trade dates skipped -> exit 1 with a
loud message. Exceptions -> traceback + exit 2. Summary ALWAYS prints.
Output CSV: workspace/deriv_options_schema_v1/h1_spy_atm30_vs_vix.csv
"""
import sys, os, csv, math, datetime as dt, traceback
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/silver/thetadata')
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
import db
from computed_greeks import load_rates, rate_on

WIN_START = dt.date(2023, 6, 1)
WIN_END = dt.date(2026, 10, 1)
T30 = 30.0 / 365.0
OUT_CSV = '/home/ubuntu/.hermes/profiles/qr_etl/workspace/deriv_options_schema_v1/h1_spy_atm30_vs_vix.csv'


def fail(msg, rc=1):
    print(f'H1 FAIL: {msg}', file=sys.stderr)
    sys.exit(rc)


def main():
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute("""SELECT ex_date, amount FROM deriv.underlying_dividends
                   WHERE underlying='SPY' ORDER BY ex_date""")
    div_rows = [(d, float(a)) for d, a in cur.fetchall()]
    if not div_rows:
        fail('no SPY dividends loaded')

    rates = load_rates(cur)
    if not rates:
        fail('no DTB3 rates loaded')

    cur.execute("""SELECT date, value FROM bronze.fred_macro_indicators
                   WHERE series_id='VIXCLS' AND value IS NOT NULL ORDER BY date""")
    vix_rows = [(d, float(v)) for d, v in cur.fetchall()]
    if not vix_rows:
        fail('VIXCLS empty — spread cannot be computed')

    cur.execute("""SELECT DISTINCT trade_date FROM silver.option_eod_quotes
                   WHERE trade_date BETWEEN %s AND %s ORDER BY 1""",
                (WIN_START, WIN_END))
    dates = [r[0] for r in cur.fetchall()]
    if not dates:
        fail('no trade dates in silver.option_eod_quotes window')

    rows_out, skipped = [], {}
    for d in dates:
        cur.execute("""
            SELECT c.expiry, c.strike, c.option_right, g.implied_vol,
                   q.underlying_close
            FROM silver.option_eod_greeks g
            JOIN silver.option_contracts c USING (contract_id)
            JOIN silver.option_eod_quotes q
              ON q.contract_id = g.contract_id AND q.trade_date = g.trade_date
            WHERE g.trade_date = %s AND c.underlying = 'SPY'
              AND g.greek_source = 'COMPUTED' AND g.implied_vol IS NOT NULL
              AND q.underlying_close IS NOT NULL
            ORDER BY c.expiry, c.strike""", (d,))
        recs = cur.fetchall()
        if not recs:
            skipped[d.isoformat()] = 'no computed IVs'
            continue
        S = float(recs[0][4])
        r = rate_on(rates, d)
        by_exp = {}
        for expiry, strike, right, iv, _ in recs:
            T = (expiry - d).days / 365.0
            if T <= 0:
                continue
            by_exp.setdefault(expiry, []).append((float(strike), right, float(iv)))
        target = d + dt.timedelta(days=30)
        exps = sorted(by_exp)
        below = [e for e in exps if e <= target]
        above = [e for e in exps if e > target]
        chosen = []
        if below:
            chosen.append(below[-1])
        if above:
            chosen.append(above[0])
        if not chosen:
            skipped[d.isoformat()] = 'no expiries'
            continue

        def expiry_iv(expiry):
            T = (expiry - d).days / 365.0
            pv = sum(a * math.exp(-r * ((ex - d).days / 365.0))
                     for ex, a in div_rows if d < ex <= expiry)
            F = (S - pv) * math.exp(r * T)
            strikes = {}
            for K, right, iv in by_exp[expiry]:
                strikes.setdefault(K, {})[right] = iv
            both = [(K, v) for K, v in strikes.items()
                    if 'C' in v and 'P' in v]
            if not both:
                return None, None, None
            K, v = min(both, key=lambda kv: abs(kv[0] - F))
            return (v['C'] + v['P']) / 2.0, T, K

        pts = []
        for e in chosen:
            iv_e, T_e, K_e = expiry_iv(e)
            if iv_e is not None:
                pts.append((T_e, iv_e, e, K_e))
        if not pts:
            skipped[d.isoformat()] = 'no two-sided ATM strike'
            continue
        if len(pts) == 1:
            iv30 = pts[0][1]
        else:
            (T1, iv1, _, _), (T2, iv2, _, _) = pts[0], pts[-1]
            v1, v2 = iv1 * iv1 * T1, iv2 * iv2 * T2
            w = (T30 - T1) / (T2 - T1)
            v30 = v1 + w * (v2 - v1)
            iv30 = math.sqrt(max(v30, 0.0) / T30)

        vix_d = None
        for vd, vv in vix_rows:
            if vd > d:
                break
            vix_d = (vd, vv)
        if vix_d is None or (d - vix_d[0]).days > 3:
            skipped[d.isoformat()] = 'no VIX within 3d'
            continue
        rows_out.append((d, iv30 * 100.0, vix_d[1], iv30 * 100.0 - vix_d[1], S))

    cov = len(rows_out) / len(dates)
    if cov < 0.80:
        fail(f'coverage {cov:.1%} of trade dates < 80% '
             f'({len(rows_out)}/{len(dates)}); skip reasons: {dict(list(skipped.items())[:5])}')

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['date', 'spy_atm30_iv_pct', 'vix_close', 'spread_vol_pts', 'spy_close'])
        for r_ in rows_out:
            w.writerow([r_[0].isoformat(), f'{r_[1]:.3f}', f'{r_[2]:.2f}',
                        f'{r_[3]:+.3f}', f'{r_[4]:.2f}'])

    sp = sorted(r_[3] for r_ in rows_out)
    n = len(sp)
    mean = sum(sp) / n
    median = sp[n // 2] if n % 2 else (sp[n // 2 - 1] + sp[n // 2]) / 2
    print(f'H1 OK: {n} daily obs ({cov:.1%} of {len(dates)} trade dates), '
          f'skipped={len(skipped)}')
    print(f'spread SPY_ATM30_IV - VIX (vol pts): mean={mean:+.2f} median={median:+.2f} '
          f'min={sp[0]:+.2f} max={sp[-1]:+.2f}')
    for target_d, label in ((dt.date(2024, 8, 5), '2024-08-05'),
                            (dt.date(2024, 8, 2), '2024-08-02'),
                            (dt.date(2024, 7, 24), '2024-07-24')):
        hit = [r_ for r_ in rows_out if r_[0] == target_d]
        if hit:
            _, iv, vx, s_, S_ = hit[0]
            print(f'{label}: SPY_IV={iv:.2f} VIX={vx:.2f} spread={s_:+.2f} (S={S_:.2f})')
    w45 = [r_[3] for r_ in rows_out if dt.date(2025, 3, 1) <= r_[0] <= dt.date(2025, 4, 30)]
    if w45:
        w45s = sorted(w45)
        m = len(w45s)
        med = w45s[m // 2] if m % 2 else (w45s[m // 2 - 1] + w45s[m // 2]) / 2
        print(f'2025-03..2025-04 window: n={m} mean={sum(w45s)/m:+.2f} median={med:+.2f} '
              f'min={w45s[0]:+.2f} max={w45s[-1]:+.2f}')
    apr = [r_[3] for r_ in rows_out if dt.date(2025, 4, 1) <= r_[0] <= dt.date(2025, 4, 30)]
    if apr:
        aprs = sorted(apr)
        m = len(aprs)
        med = aprs[m // 2] if m % 2 else (aprs[m // 2 - 1] + aprs[m // 2]) / 2
        print(f'2025-04 alone: n={m} mean={sum(aprs)/m:+.2f} median={med:+.2f}')
    print(f'wrote {OUT_CSV}')
    conn.close()


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(2)
