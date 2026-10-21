#!/usr/bin/env python3
"""
gold.option_vol_features_daily builder
======================================
Implements qr_research GOLD_FEATURES_SPEC.md (deriv_equity_enrichment_v1
Task 5) for SPY + XLE (XLE once its chains land).

Grain: (underlying, feature_date). Features dated T use EOD marks of T only
(PIT); available_after = next chain trading day (decision-usable T+1).

Features built (spec scope — nothing else):
  mfiv_30    Model-free 30d constant-maturity IV, VIX white-paper methodology:
             OTM puts (K<K0) / calls (K>K0), both averaged at K0 (largest
             strike <= F); F from put-call parity at the strike pair with
             min |call-put| mid per expiry; two nearest listed expiries
             bracketing 30 calendar days; total-variance interpolation;
             vol pts. Rate r = DTB3 latest <= trade_date (percent/100).
             Quotes: mid IS NOT NULL and quality_flags not containing
             ZERO_BID.
  atm_iv_30  -> atm_iv_30d column. ATM constant-30d IV from
             silver.option_eod_greeks (greek_source='COMPUTED'), put/call
             implied_vol averaged at K0 nearest F per bracketing expiry,
             total-variance interpolated. Reporting/strike-selection only.
  rv_30      std(dlog close, trailing 21 trading days, ddof=1) * sqrt(252)
             * 100. Close series: options-chain underlying_close per
             trade_date (consistent dating with the quotes; declared per
             spec "state which and keep it fixed").
  vrp_30d    mfiv_30 - rv_30 (vol pts).
  iv_rank_1y count(trailing 252 TDs with mfiv_30 <= today's) / 252 * 100.
             SPEC DEVIATION (flagged to qr_research 2026-10-07): the spec's
             "minimum history 126 obs" clause conflicts with its own declared
             consequence ("first non-NULL SPY value ~ 2024-06-03" = 252 TDs
             after the 2023-06-01 chain start) and with the fixed /252
             denominator (with 126 obs the rank would cap at 50). This build
             requires the FULL 252-observation window, which satisfies the
             formula and the declared first-value date exactly.

Nightly mode (default): recompute the trailing 10 calendar days per
underlying (covers reverify-driven quote revisions), upsert idempotently.
Backfill mode: --start 2023-06-01.

Run: /usr/bin/python3 (psycopg2 via shared db.py; stdlib math only).
"""
import argparse
import math
import sys
from collections import defaultdict

sys.path.insert(0, "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts")
import db  # noqa: E402

UNDERLYINGS_DEFAULT = ["SPY", "XLE"]
TARGET_DTE = 30
MIN_DTE, MAX_DTE = 7, 60
RANK_WINDOW = 252
RV_WINDOW = 21
NIGHTLY_LOOKBACK_DAYS = 10


def interp_total_variance(t1, v1, t2, v2, target=TARGET_DTE):
    """t in calendar days, v ANNUALIZED variance. Total variance w = v * (t/365)
    is interpolated linearly in time between the bracketing expiries, then
    re-annualized at the target horizon. (Dimensionally equivalent to the
    spec's formula when its per-expiry sigma^2 is taken per-day.)"""
    w1 = v1 * t1 / 365.0
    w2 = v2 * t2 / 365.0
    w_t = (w1 * (t2 - target) + w2 * (target - t1)) / (t2 - t1)
    return w_t / (target / 365.0)


def expiry_variance(strikes_q, F, r, tau_years):
    """VIX-methodology variance for one expiry.
    strikes_q: sorted list of (K, Q) with Q already side-selected. Returns (var, n)."""
    n = len(strikes_q)
    if n < 3 or F <= 0:
        return None, n
    K0 = max((K for K, _ in strikes_q if K <= F), default=strikes_q[0][0])
    s = 0.0
    ert = math.exp(r * tau_years)
    for i, (K, Q) in enumerate(strikes_q):
        if i == 0:
            dk = strikes_q[1][0] - K
        elif i == n - 1:
            dk = K - strikes_q[i - 1][0]
        else:
            dk = (strikes_q[i + 1][0] - strikes_q[i - 1][0]) / 2.0
        s += dk / (K * K) * ert * Q
    var = (2.0 / tau_years) * s - (1.0 / tau_years) * (F / K0 - 1.0) ** 2
    return var, n


def bracket_expiries(expiry_rows, trade_date):
    """expiry_rows: {expiry: rows}. Return (near_expiry, far_expiry) bracketing 30 cal days."""
    near = far = None
    for exp in sorted(expiry_rows):
        dte = (exp - trade_date).days
        if dte < MIN_DTE or dte > MAX_DTE:
            continue
        if dte < TARGET_DTE:
            near = exp if near is None or exp > near else near
        else:
            far = exp if far is None or exp < far else far
    return near, far


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--underlying', default=None, help='default: SPY,XLE (skips underlyings with no chain data)')
    ap.add_argument('--start', default=None, help='first feature_date to WRITE (default: trailing 10 days)')
    ap.add_argument('--end', default=None)
    args = ap.parse_args()

    conn = db.get_connection()
    cur = conn.cursor()
    db.require_table(conn, 'gold', 'option_vol_features_daily')

    underlyings = [args.underlying] if args.underlying else UNDERLYINGS_DEFAULT

    for U in underlyings:
        # ── full quote history for this underlying (PIT inputs only) ──────────
        cur.execute("""
            SELECT q.trade_date, c.expiry, c.strike, c.option_right, q.mid, q.underlying_close
            FROM silver.option_eod_quotes q
            JOIN silver.option_contracts c USING (contract_id)
            WHERE c.underlying = %s
              AND q.mid IS NOT NULL
              AND NOT (q.quality_flags @> ARRAY['ZERO_BID']::text[])
            ORDER BY q.trade_date, c.expiry, c.strike
        """, (U,))
        rows = cur.fetchall()
        if not rows:
            print(f"{U}: no chain data — skipped")
            continue

        days = defaultdict(lambda: defaultdict(lambda: {'C': {}, 'P': {}}))
        uclose = {}
        for td, exp, K, right, mid, ucl in rows:
            days[td][exp][right][float(K)] = float(mid)
            uclose[td] = float(ucl)
        tdates = sorted(days)
        print(f"{U}: {len(tdates)} trade days {tdates[0]}..{tdates[-1]}")

        # DTB3 series (percent -> decimal), latest <= trade_date
        cur.execute("""SELECT date, value FROM bronze.fred_macro_indicators
                       WHERE series_id='DTB3' ORDER BY date""")
        rates = cur.fetchall()
        rate_dates = [r[0] for r in rates]
        rate_vals = {r[0]: float(r[1]) / 100.0 for r in rates}

        def rate_on(td):
            import bisect
            i = bisect.bisect_right(rate_dates, td)
            return rate_vals[rate_dates[i - 1]] if i > 0 else None

        # realized vol series (21TD log-return std on chain underlying_close)
        logret = {}
        for i in range(1, len(tdates)):
            logret[tdates[i]] = math.log(uclose[tdates[i]] / uclose[tdates[i - 1]])

        # greeks (COMPUTED IV) for atm_iv: load per day on demand below.
        mfiv = {}     # td -> mfiv_30 (vol pts) or None
        atmiv = {}
        strikes_used = {}
        flags = {}
        for td in tdates:
            r = rate_on(td)
            if r is None:
                mfiv[td] = atmiv[td] = None
                strikes_used[td] = 0
                flags[td] = 'NO_RATE'
                continue
            near, far = bracket_expiries(days[td], td)
            if near is None or far is None:
                mfiv[td] = atmiv[td] = None
                strikes_used[td] = 0
                flags[td] = 'NO_BRACKET'
                continue
            per_exp = {}
            for exp in (near, far):
                calls, puts = days[td][exp]['C'], days[td][exp]['P']
                common = sorted(set(calls) & set(puts))
                if not common:
                    per_exp[exp] = (None, 0, None)
                    continue
                tau = (exp - td).days / 365.0
                kstar = min(common, key=lambda K: abs(calls[K] - puts[K]))
                F = kstar + math.exp(r * tau) * (calls[kstar] - puts[kstar])
                K0 = max((K for K in sorted(set(calls) | set(puts)) if K <= F),
                         default=min(set(calls) | set(puts)))
                allK = sorted(set(calls) | set(puts))
                sq = []
                for K in allK:
                    if K < K0 and K in puts:
                        sq.append((K, puts[K]))
                    elif K > K0 and K in calls:
                        sq.append((K, calls[K]))
                    elif K == K0:
                        both = [x for x in (puts.get(K), calls.get(K)) if x is not None]
                        if both:
                            sq.append((K, sum(both) / len(both)))
                var, nused = expiry_variance(sq, F, r, tau)
                per_exp[exp] = (var, nused, F)

            t1 = (near - td).days
            t2 = (far - td).days
            v1, n1, F1 = per_exp[near]
            v2, n2, F2 = per_exp[far]
            strikes_used[td] = (n1 or 0) + (n2 or 0)
            if v1 is not None and v2 is not None and v1 > 0 and v2 > 0:
                var30 = interp_total_variance(t1, v1, t2, v2)
                mfiv[td] = math.sqrt(var30) * 100.0 if var30 > 0 else None
            else:
                mfiv[td] = None

            # atm_iv_30 from COMPUTED greeks at K0 nearest F
            atm_by_exp = {}
            for exp, (_, _, F) in per_exp.items():
                if F is None:
                    continue
                cur.execute("""
                    SELECT c.option_right, g.implied_vol
                    FROM silver.option_eod_greeks g
                    JOIN silver.option_contracts c USING (contract_id)
                    WHERE g.trade_date = %s AND c.expiry = %s
                      AND g.greek_source = 'COMPUTED' AND g.implied_vol IS NOT NULL
                      AND c.strike = (
                          SELECT c2.strike FROM silver.option_contracts c2
                          JOIN silver.option_eod_quotes q2 USING (contract_id)
                          WHERE q2.trade_date = %s AND c2.expiry = %s
                            AND c2.underlying = %s AND q2.mid IS NOT NULL
                          ORDER BY ABS(c2.strike - %s) LIMIT 1)
                """, (td, exp, td, exp, U, F))
                ivs = [float(x[1]) for x in cur.fetchall()]
                if ivs:
                    atm_by_exp[exp] = sum(ivs) / len(ivs)
            if near in atm_by_exp and far in atm_by_exp:
                var_atm = interp_total_variance(t1, atm_by_exp[near] ** 2,
                                                t2, atm_by_exp[far] ** 2)
                atmiv[td] = math.sqrt(var_atm) * 100.0 if var_atm > 0 else None
            else:
                atmiv[td] = None
            flags[td] = 'OK' if mfiv[td] is not None else 'NO_BRACKET_LEG'

        # rv_30
        rv = {}
        for i, td in enumerate(tdates):
            if td not in logret:
                continue
            window = [logret[tdates[j]] for j in range(max(1, i - RV_WINDOW + 1), i + 1)
                      if tdates[j] in logret]
            if len(window) >= RV_WINDOW:
                m = sum(window) / len(window)
                var = sum((x - m) ** 2 for x in window) / (len(window) - 1)
                rv[td] = math.sqrt(var) * math.sqrt(252) * 100.0
            else:
                rv[td] = None

        # iv_rank_1y: full 252-observation window (see header note)
        mfiv_series = [(td, mfiv[td]) for td in tdates]
        rank = {}
        for i, (td, v) in enumerate(mfiv_series):
            lo = max(0, i - RANK_WINDOW + 1)
            window = [x[1] for x in mfiv_series[lo:i + 1] if x[1] is not None]
            if v is None or len(window) < RANK_WINDOW:
                rank[td] = None
            else:
                rank[td] = sum(1 for x in window if x <= v) / RANK_WINDOW * 100.0

        # write window
        import datetime as dt
        start = dt.date.fromisoformat(args.start) if args.start else \
            tdates[-1] - dt.timedelta(days=NIGHTLY_LOOKBACK_DAYS)
        end = dt.date.fromisoformat(args.end) if args.end else tdates[-1]
        write_dates = [td for td in tdates if start <= td <= end]
        ins = 0
        for i, td in enumerate(tdates):
            if td not in write_dates:
                continue
            nxt = tdates[i + 1] if i + 1 < len(tdates) else td + dt.timedelta(days=1)
            m = mfiv[td]
            rvv = rv.get(td)
            cur.execute("""
                INSERT INTO gold.option_vol_features_daily
                  (underlying, feature_date, mfiv_30, atm_iv_30d, iv_rank_1y,
                   rv_30, vrp_30d, n_strikes_used, quality_flag,
                   available_after, computed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (underlying, feature_date) DO UPDATE SET
                  mfiv_30 = EXCLUDED.mfiv_30,
                  atm_iv_30d = EXCLUDED.atm_iv_30d,
                  iv_rank_1y = EXCLUDED.iv_rank_1y,
                  rv_30 = EXCLUDED.rv_30,
                  vrp_30d = EXCLUDED.vrp_30d,
                  n_strikes_used = EXCLUDED.n_strikes_used,
                  quality_flag = EXCLUDED.quality_flag,
                  available_after = EXCLUDED.available_after,
                  computed_at = now()
            """, (U, td, m, atmiv[td], rank[td], rvv,
                  (m - rvv) if (m is not None and rvv is not None) else None,
                  strikes_used[td], flags[td], nxt))
            ins += cur.rowcount
        conn.commit()
        n_mfiv = sum(1 for td in write_dates if mfiv[td] is not None)
        print(f"{U}: upserted {ins} rows [{write_dates[0]}..{write_dates[-1]}], "
              f"mfiv non-null {n_mfiv}/{len(write_dates)}")

    conn.close()
    print("DONE")


if __name__ == '__main__':
    main()
