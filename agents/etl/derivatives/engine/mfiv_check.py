#!/usr/bin/env python3
"""Model-free 30D IV (VIX methodology) from OUR SPY chain vs VIX close.

Tests whether the -3.1 vol pt H1 gap (our ATM IV vs VIX) is a data/model
problem or just the ATM-vs-model-free basis (VIX loads OTM puts -> skew).

Per date: bracketing listed expiries around 30D; per expiry compute
  sigma^2 = (2/T) * sum( dK/K^2 * exp(rT) * Q(K) ) - (1/T)*(F/K0 - 1)^2
over OTM puts (K<F) + OTM calls (K>F), Q = mid, bid>0 required.
Linear variance interpolation to T30 = 30/365 (CBOE-style).

Sample: every monthly roll date + all dates in 2024-07-24..2024-08-09 and
2025-03-01..2025-04-30. Prints spread stats; exit 1 on empty.
"""
import sys, math, datetime as dt, traceback
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/silver/thetadata')
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
import db
from computed_greeks import load_rates, rate_on

T30 = 30.0 / 365.0
WIN_START = dt.date(2023, 6, 1)
WIN_END = dt.date(2026, 10, 1)


def third_friday(y, m):
    d = dt.date(y, m, 15)
    while d.weekday() != 4:
        d += dt.timedelta(days=1)
    return d


def main():
    conn = db.get_connection()
    cur = conn.cursor()
    rates = load_rates(cur)
    cur.execute("SELECT ex_date, amount FROM deriv.underlying_dividends WHERE underlying='SPY' ORDER BY 1")
    div_rows = [(d, float(a)) for d, a in cur.fetchall()]
    cur.execute("""SELECT date, value FROM bronze.fred_macro_indicators
                   WHERE series_id='VIXCLS' AND value IS NOT NULL ORDER BY date""")
    vix = {d: float(v) for d, v in cur.fetchall()}

    # sample dates
    cur.execute("""SELECT DISTINCT trade_date FROM silver.option_eod_quotes
                   WHERE trade_date BETWEEN %s AND %s ORDER BY 1""",
                (WIN_START, WIN_END))
    all_dates = [r[0] for r in cur.fetchall()]
    monthly = [d for d in all_dates
               if d == third_friday(d.year, d.month)
               or (d == third_friday(d.year, d.month) - dt.timedelta(days=1)
                   and third_friday(d.year, d.month).weekday() == 4)]
    stress = [d for d in all_dates
              if dt.date(2024, 7, 24) <= d <= dt.date(2024, 8, 9)
              or dt.date(2025, 3, 1) <= d <= dt.date(2025, 4, 30)]
    sample = sorted(set(monthly) | set(stress))
    print(f'sample dates: {len(sample)} ({len(monthly)} monthly + {len(stress)} stress)')

    out = []
    for d in sample:
        cur.execute("""
            SELECT c.expiry, c.strike, c.option_right, q.mid, q.bid,
                   q.underlying_close
            FROM silver.option_eod_quotes q
            JOIN silver.option_contracts c USING (contract_id)
            WHERE q.trade_date = %s AND c.underlying = 'SPY'
              AND q.mid IS NOT NULL AND q.bid > 0
              AND q.underlying_close IS NOT NULL
            ORDER BY c.expiry, c.strike""", (d,))
        rows = cur.fetchall()
        if not rows:
            continue
        S = float(rows[0][5])
        r = rate_on(rates, d)
        by_exp = {}
        for expiry, K, right, mid, bid, _ in rows:
            T = (expiry - d).days / 365.0
            if T <= 5 / 365.0:
                continue
            by_exp.setdefault(expiry, []).append((float(K), right, float(mid)))
        target = d + dt.timedelta(days=30)
        exps = sorted(by_exp)
        below = [e for e in exps if e <= target]
        above = [e for e in exps if e > target]
        chosen = ([below[-1]] if below else []) + ([above[0]] if above else [])
        if not chosen:
            continue

        def mf_var(expiry):
            T = (expiry - d).days / 365.0
            pv = sum(a * math.exp(-r * ((ex - d).days / 365.0))
                     for ex, a in div_rows if d < ex <= expiry)
            F = (S - pv) * math.exp(r * T)
            chain = sorted(by_exp[expiry])
            Ks = sorted({k for k, _, _ in chain})
            # F via parity at K0: use strike nearest F with both sides
            K0 = min(Ks, key=lambda k: abs(k - F))
            q = {}
            for k, right, mid in chain:
                q.setdefault(k, {})[right] = mid
            Ks = sorted(q)
            contrib = 0.0
            for i, K in enumerate(Ks):
                dK = (Ks[i + 1] - Ks[i - 1]) / 2 if 0 < i < len(Ks) - 1 else (
                    Ks[1] - Ks[0] if i == 0 and len(Ks) > 1 else
                    (Ks[-1] - Ks[-2] if len(Ks) > 1 else 0.0))
                if dK <= 0:
                    continue
                if K < K0 and 'P' in q[K]:
                    price = q[K]['P']
                elif K > K0 and 'C' in q[K]:
                    price = q[K]['C']
                elif K == K0:
                    if 'C' in q[K] and 'P' in q[K]:
                        price = (q[K]['C'] + q[K]['P']) / 2
                    else:
                        continue
                else:
                    continue
                contrib += dK / (K * K) * price
            return (2.0 / T) * math.exp(r * T) * contrib - (1.0 / T) * (F / K0 - 1.0) ** 2, T

        pts = []
        for e in chosen:
            v, T = mf_var(e)
            if v and v > 0:
                pts.append((T, v, e))
        if not pts:
            continue
        if len(pts) == 1:
            v30 = pts[0][1]
        else:
            (T1, v1, _), (T2, v2, _) = pts[0], pts[-1]
            w = (T30 - T1) / (T2 - T1)
            v30 = v1 + w * (v2 - v1)
        if v30 <= 0:
            continue
        mfiv = math.sqrt(v30) * 100.0
        vx = vix.get(d)
        out.append({'date': d, 'mfiv': mfiv, 'vix': vx,
                    'spread': (mfiv - vx) if vx else None})

    have_vix = [o for o in out if o['vix'] is not None]
    if not have_vix:
        print('MFIV FAIL: no overlapping VIX dates', file=sys.stderr)
        sys.exit(1)
    sp = sorted(o['spread'] for o in have_vix)
    n = len(sp)
    med = sp[n // 2] if n % 2 else (sp[n // 2 - 1] + sp[n // 2]) / 2
    print(f'MFIV vs VIX: n={n} spread mean={sum(sp)/n:+.2f} median={med:+.2f} '
          f'min={sp[0]:+.2f} max={sp[-1]:+.2f} vol pts')
    for lab, lo, hi in (('2024-07-24..2024-08-09', dt.date(2024, 7, 24), dt.date(2024, 8, 9)),
                        ('2025-03..2025-04', dt.date(2025, 3, 1), dt.date(2025, 4, 30))):
        w = [o['spread'] for o in have_vix if lo <= o['date'] <= hi]
        if w:
            ws = sorted(w)
            m = len(ws)
            wmed = ws[m // 2] if m % 2 else (ws[m // 2 - 1] + ws[m // 2]) / 2
            print(f'  {lab}: n={m} mean={sum(ws)/m:+.2f} median={wmed:+.2f}')
    x = next((o for o in have_vix if o['date'] == dt.date(2024, 8, 5)), None)
    if x:
        print(f"  2024-08-05: MFIV(SPY chain)={x['mfiv']:.2f} VIX={x['vix']:.2f} "
              f"spread={x['spread']:+.2f}  [vs ATM IV 28.84]")
    conn.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
