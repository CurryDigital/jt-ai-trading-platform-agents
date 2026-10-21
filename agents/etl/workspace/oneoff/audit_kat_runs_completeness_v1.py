#!/usr/bin/env python3
"""
gap_remediation_v1 step 4b: retroactive completeness audit of ALL deriv.kat_runs
+ independent roll-calendar cross-check (NO engine code).

For each run:
  A1. every calendar month in [first settled expiry, last settled expiry] has
      a settled leg (kat_trades.settle_value NOT NULL)
  A2. every roll_date/expiry has an underlying mark in gold.daily_ohlcv
      (^GSPC for SPX runs, SPY for SPY runs) and an SOQ input (open NOT NULL)
  A3. every trading day (underlying closes) in [first NAV, last NAV] has a
      kat_daily row
  B.  independent roll calendar: expected standard monthlies = 3rd Friday of
      each month in the window (minus weekday shifts for known US holidays via
      gold ^GSPC/SPY presence: expected expiry = last trading day on/before
      3rd Friday that is a Friday or the Thursday before a holiday Friday),
      compared against the run's actual trade list.

Output: printed report + JSON to workspace/ohlcv_gap_audit_v1/kat_runs_audit.json
"""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"))
import db

OUT = os.path.expanduser("~/.hermes/profiles/qr_etl/workspace/ohlcv_gap_audit_v1")

def third_fridays(y0, m0, y1, m1, trading_days=None):
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        d = dt.date(y, m, 15)
        while d.weekday() != 4:
            d += dt.timedelta(days=1)
        # holiday shift: if the 3rd Friday is not a trading day (Good Friday,
        # Juneteenth-observed...), standard monthlies expire the prior
        # trading day
        if trading_days is not None:
            while d not in trading_days and d > dt.date(y, m, 1):
                d -= dt.timedelta(days=1)
        out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out

def main():
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT run_id, index_name, params, status, verdict, finished_at
                   FROM deriv.kat_runs ORDER BY finished_at""")
    runs = cur.fetchall()
    print(f"{len(runs)} kat_runs")

    # underlying date sets for marks/trading-day expectations
    cur.execute("""SELECT date, open IS NOT NULL FROM gold.daily_ohlcv
                   WHERE ticker='^GSPC' AND close IS NOT NULL""")
    spx = {d: has_open for d, has_open in cur.fetchall()}
    cur.execute("""SELECT date, open IS NOT NULL FROM gold.daily_ohlcv
                   WHERE ticker='SPY' AND close IS NOT NULL""")
    spy = {d: has_open for d, has_open in cur.fetchall()}

    report = []
    for run_id, idx, params, status, verdict, fin in runs:
        p = params if isinstance(params, dict) else json.loads(params)
        symbol = p.get('symbol', 'SPY')
        under = spx if symbol == 'SPX' else spy
        win = p.get('window')
        cur.execute("""SELECT roll_date, expiry, settle_value FROM deriv.kat_trades
                       WHERE run_id=%s ORDER BY roll_date""", (run_id,))
        trades = cur.fetchall()
        # early-assigned legs (SPY runs): the leg for detail->>'expiry'
        # terminated before expiry via assignment — counts as covered.
        cur.execute("SELECT event_date, detail FROM deriv.kat_events WHERE run_id=%s", (run_id,))
        assigned_expiry_months = set()
        for _ed, det in cur.fetchall():
            det = det if isinstance(det, dict) else json.loads(det or '{}')
            ex = det.get('expiry')
            if ex:
                e = dt.date.fromisoformat(ex)
                assigned_expiry_months.add((e.year, e.month))
        cur.execute("""SELECT trade_date FROM deriv.kat_daily
                       WHERE run_id=%s ORDER BY trade_date""", (run_id,))
        nav_days = [r[0] for r in cur.fetchall()]

        missing = []
        settled = [t for t in trades if t[2] is not None]
        if settled:
            exps = sorted(t[1] for t in settled)
            have = {(e.year, e.month) for e in exps} | assigned_expiry_months
            # coverage extends through the last monthly expiry inside the
            # declared window (independent calendar) so a truncated trade
            # list cannot shrink the checked span
            y, m = exps[0].year, exps[0].month
            if win:
                w1d = dt.date.fromisoformat(win[1])
                cal = third_fridays(exps[0].year, exps[0].month,
                                    w1d.year, w1d.month,
                                    trading_days=set(under))
                cov_end = max(e for e in cal if e <= w1d)
            else:
                cov_end = exps[-1]
            while (y, m) <= (cov_end.year, cov_end.month):
                if (y, m) not in have:
                    missing.append(f"month {y:04d}-{m:02d} has no settled leg")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        elif trades:
            missing.append("no settled legs")
        else:
            missing.append("no trades at all")
        for rd, ex, sv in trades:
            if rd not in under:
                missing.append(f"roll {rd} no underlying close ({symbol})")
            # SOQ input only required for legs that actually settle in-window;
            # the final still-open leg needs no settlement input.
            if sv is not None and (ex not in under or not under[ex]):
                missing.append(f"expiry {ex} no SOQ input ({symbol} open)")
        if nav_days:
            ns = set(nav_days)
            for d in sorted(under):
                if nav_days[0] <= d <= nav_days[-1] and d not in ns:
                    missing.append(f"trading day {d} no NAV row")
        # B: independent roll calendar
        cal_note = None
        if win and trades:
            w0 = dt.date.fromisoformat(win[0]); w1 = dt.date.fromisoformat(win[1])
            expected = third_fridays(w0.year, w0.month, w1.year, w1.month,
                                     trading_days=set(under))
            actual_exps = sorted({t[1] for t in trades})
            # engine rolls INTO expiry at the previous expiry: expected traded
            # expiries = monthlies strictly after first roll, <= last monthly
            # at/after window end
            first_roll = min(t[0] for t in trades)
            exp_expected = [e for e in expected if e > first_roll]
            # the last leg may expire after the window; compare intersection
            in_win = [e for e in exp_expected if e <= max(actual_exps)]
            extra = [e for e in actual_exps if e not in expected]
            missed = [e for e in in_win if e not in actual_exps]
            # final open leg (expiry after window end) is expected, not extra
            extra = [e for e in extra if e <= w1]
            if extra or missed:
                cal_note = f"calendar mismatch: missed={missed} extra={extra}"
        retro = 'PASS' if not missing else 'FAIL'
        report.append({
            'run_id': str(run_id), 'index': idx, 'symbol': symbol,
            'window': win, 'recorded_status': status, 'verdict': verdict,
            'finished_at': str(fin), 'n_trades': len(trades),
            'n_nav_days': len(nav_days), 'retro_completeness': retro,
            'missing_items': missing[:50], 'n_missing': len(missing),
            'roll_calendar_check': cal_note or 'consistent',
        })
        flag = '' if retro == 'PASS' and not cal_note else '  <<< REVIEW'
        print(f"{fin:%Y-%m-%d} {idx:4s} {symbol} n_trades={len(trades)} "
              f"status={status} retro={retro} missing={len(missing)} "
              f"cal={cal_note or 'ok'}{flag}")

    with open(f"{OUT}/kat_runs_audit.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    n_fail = sum(1 for r in report if r['retro_completeness'] == 'FAIL')
    n_cal = sum(1 for r in report if r['roll_calendar_check'] != 'consistent')
    print(f"\nSUMMARY: {len(report)} runs; retro-FAIL={n_fail}; "
          f"calendar-mismatch={n_cal} -> {OUT}/kat_runs_audit.json")
    conn.close()

if __name__ == '__main__':
    main()
