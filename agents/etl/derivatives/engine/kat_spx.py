#!/usr/bin/env python3
"""
SPX KAT runner — the unchanged KAT on the TRUE underlying (decision
2026-10-05: early-assignment fix -> audit -> free SPX probe -> KAT re-run
UNCHANGED). BXM/PUT are SPX indexes: European, cash-settled, AM-settled
standard monthlies. This runner replicates them on quoted SPX chains
(free window 2023-06-01+) with the SAME frozen tolerances (KAT_PLAN.md),
same fill model, same commissions, same roll/strike conventions as the
audited SPY runner (kat_bxm_put.py, EEP2 round-5 — untouched here).

Differences vs the SPY runner (all forced by the instrument, not tuning):
- Underlying closes: gold.daily_ohlcv ticker='^GSPC' (ThetaData stock
  endpoint carries no index symbols — HTTP 472, verified 2026-10-07).
- EUROPEAN exercise: NO early-assignment model at all (engine.py's
  early_assignment is never invoked).
- BXM dividends: S&P 500 aggregate dividend approximated as SPY dividend
  x (SPX_close/SPY_close) at each SPY ex-date, reinvested. Documented
  approximation (SPY expense drag ~0.09%/yr included in the wedge);
  flagged in run params. PUT needs no dividends (cash-secured).
- bug_fix citation: 'UNCHANGED_SPX_KAT_2026-10-07' — the engine code is
  byte-identical to the EEP2-audited state; only the instrument differs.

Run with /usr/bin/python3. Usage: kat_spx.py [--index BXM,PUT] [--fills 1.0,0.0]
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
from engine import Engine, COMMISSION_PER_CONTRACT, MIN_COMMISSION, MULT  # noqa: E402
from kat_bxm_put import (metrics, judge, load_ref, TOL, REF_DIR,  # noqa: E402
                         WINDOW_START, WINDOW_END)
import db  # noqa: E402
import engine_version  # noqa: E402

BUGFIX_TAG = 'UNCHANGED_SPX_KAT_2026-10-07'


class SPXEngine(Engine):
    """Engine with index-level closes from gold.daily_ohlcv ^GSPC."""

    def __init__(self, *a, **kw):
        super().__init__(*a, symbol='SPX', **kw)
        self._opens = None

    def closes(self) -> dict:
        if self._closes is None:
            cur = self.conn.cursor()
            cur.execute("""SELECT date, close FROM gold.daily_ohlcv
                           WHERE ticker='^GSPC' AND close IS NOT NULL ORDER BY date""")
            # 2026-10-09: 2 all-NULL ^GSPC rows (holidays 2026-05-25 Memorial
            # Day, 2026-06-19 Juneteenth) crashed float(None); both are
            # market-closed dates with no SPX quotes — exclude them.
            self._closes = {d: float(c) for d, c in cur.fetchall()}
            cur.close()
        return self._closes

    def opens(self) -> dict:
        """Expiry-day OPEN per date — SOQ proxy for AM-settled standard
        monthly SPX. 9 of 2180 ^GSPC rows have NULL open; the settle path
        falls back to the close and flags it."""
        if self._opens is None:
            cur = self.conn.cursor()
            cur.execute("""SELECT date, open FROM gold.daily_ohlcv
                           WHERE ticker='^GSPC' ORDER BY date""")
            self._opens = {d: (float(o) if o is not None else None)
                           for d, o in cur.fetchall()}
            cur.close()
        return self._opens


def spx_dividends(conn, spy_closes: dict, spx_closes: dict) -> dict:
    """ex_date -> SPX-index-point dividend, scaled from SPY dividends."""
    cur = conn.cursor()
    cur.execute("""SELECT ex_date, amount FROM deriv.underlying_dividends
                   WHERE underlying='SPY'""")
    out = {}
    for ex, amt in cur.fetchall():
        s_spy = spy_closes.get(ex)
        s_spx = spx_closes.get(ex)
        if s_spy and s_spx:
            out[ex] = float(amt) * (s_spx / s_spy)
    cur.close()
    return out


def spy_closes(conn) -> dict:
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (trade_date) trade_date, payload->>'close'
                   FROM bronze.thetadata_stock_eod_raw
                   WHERE symbol='SPY' ORDER BY trade_date, ingested_at DESC""")
    out = {d: float(c) for d, c in cur.fetchall()}
    cur.close()
    return out


def run_index(engine: SPXEngine, index: str, days: list, divs: dict,
              ref: dict) -> dict:
    """European replication: identical mechanics to the audited SPY runner
    minus every American early-assignment path."""
    is_call = index == 'BXM'
    right = 'C' if is_call else 'P'
    expiries = engine.monthly_expiries()
    rolls = [e for e in expiries if WINDOW_START <= e <= WINDOW_END]

    closes = engine.closes()
    daily, trades, skips = [], [], []
    soq_fallbacks = []
    shares = 0.0
    cash = 0.0
    leg = None
    nav0 = None
    ref0 = None
    prev_day = None
    roll_set = set(rolls)

    for i, d in enumerate(days):
        if d < rolls[0]:
            continue
        S = closes[d]
        if prev_day is not None:
            gap = (d - prev_day).days
            r = engine.rate_on(prev_day)
            cash *= (1.0 + r / 360.0) ** gap
        note = ''

        # settle expiring leg at intrinsic — AM-settled standard monthly SPX:
        # settlement = expiry-morning ^GSPC OPEN as SOQ proxy (not close).
        if leg is not None and d == leg['expiry']:
            o = engine.opens().get(d)
            if o is None:
                o = S  # NULL open fallback — flagged in run notes
                soq_fallbacks.append(d.isoformat())
            intrinsic = max(o - leg['strike'], 0.0) if is_call \
                else max(leg['strike'] - o, 0.0)
            cash -= intrinsic * MULT
            trades[-1]['settle_value'] = intrinsic
            trades[-1]['note'] = (trades[-1]['note'] + ' SOQ_PROXY_OPEN'
                                  + ('' if engine.opens().get(d) is not None
                                     else '|OPEN_NULL_FELL_BACK_TO_CLOSE')).strip()
            leg = None

        # roll into new leg
        if leg is None and d in roll_set:
            nxt = [e for e in expiries if e > d]
            if nxt:
                expiry = nxt[0]
                sel, why = engine.select_atm(d, expiry, right, S)
                if sel is None:
                    skips.append((d.isoformat(), why))
                else:
                    fill = engine.sell_fill(sel)
                    comm = max(COMMISSION_PER_CONTRACT * 1, MIN_COMMISSION)
                    cash += fill * MULT - comm
                    leg = {'contract_id': sel['contract_id'], 'expiry': expiry,
                           'strike': sel['strike'], 'right': right}
                    trades.append({'roll_date': d, 'expiry': expiry,
                                   'strike': sel['strike'], 'right': right,
                                   'contract_id': sel['contract_id'],
                                   'fill_price': fill, 'commission': comm,
                                   'settle_value': None, 'note': ''})
                    if nav0 is None:
                        if is_call:
                            shares = 100.0
                            nav0 = 100.0 * S
                        else:
                            cash += sel['strike'] * MULT
                            nav0 = sel['strike'] * MULT
                        ref_candidates = [rd for rd in ref if rd <= d]
                        ref0 = ref[max(ref_candidates)] if ref_candidates else None

        # BXM: index dividends reinvested at close on ex-date
        if is_call and d in divs and shares > 0:
            shares += (divs[d] * shares) / S

        # mark to market
        nav = cash + shares * S
        if leg is not None:
            q = engine.quote_series(leg['contract_id']).get(d)
            intrinsic = max(S - leg['strike'], 0.0) if is_call \
                else max(leg['strike'] - S, 0.0)
            if leg['expiry'] == d:
                mark_v, mnote = intrinsic, 'EXPIRY_SETTLE'
            else:
                mark_v, mnote = engine.mark(q, -1, intrinsic)
            nav -= mark_v * MULT
            if mnote:
                note = mnote

        if nav0 is None:
            prev_day = d
            continue
        level = nav / nav0 * ref0 if ref0 else None
        ref_level = ref.get(d)
        daily.append({'date': d, 'nav': nav, 'level': level,
                      'ref': ref_level, 'note': note})
        prev_day = d

    for j in range(1, len(daily)):
        daily[j]['ret'] = daily[j]['nav'] / daily[j - 1]['nav'] - 1.0
        if daily[j]['ref'] and daily[j - 1]['ref']:
            daily[j]['ref_ret'] = daily[j]['ref'] / daily[j - 1]['ref'] - 1.0
        else:
            daily[j]['ref_ret'] = None
    daily[0]['ret'] = None
    daily[0]['ref_ret'] = None
    return {'daily': daily, 'trades': trades, 'skips': skips, 'events': [],
            'soq_fallbacks': soq_fallbacks}


def completeness_gate(out, days, rolls, closes, opens, ref):
    """gap_remediation_v1 step 4 (2026-10-14): a KAT run may end SUCCESS only
    if the run is COMPLETE, not merely within tolerances. Returns a list of
    missing-item strings; empty list = complete.

    Assertions:
      1. every calendar month in [first roll, last expiry] has a settled leg
         (the final still-open leg, expiry > WINDOW_END, is exempt),
      2. every roll date has an underlying close (mark input) and every
         SETTLED expiry has an SOQ input (^GSPC open; NULL-open close fallback
         counts as missing SOQ input). The final still-open leg (expiry >
         WINDOW_END) is exempt — it has no expiry inside the window yet,
      3. every trading day in [first NAV day, last NAV day] has a NAV row.
    """
    missing = []
    trades = out['trades']
    settled = [t for t in trades if t.get('settle_value') is not None]
    # 1. monthly settled-leg coverage: every month from the first settled
    # expiry through the last monthly expiry <= WINDOW_END (a truncated trade
    # list must NOT shorten the checked span)
    if settled:
        expiries_s = sorted(t['expiry'] for t in settled)
        m0 = (expiries_s[0].year, expiries_s[0].month)
        in_win = sorted(e for e in (rolls or expiries_s) if e <= WINDOW_END)
        last_cov = in_win[-1] if in_win else expiries_s[-1]
        m1 = (last_cov.year, last_cov.month)
        have = {(t['expiry'].year, t['expiry'].month) for t in settled}
        y, mth = m0
        while (y, mth) <= m1:
            if (y, mth) not in have:
                missing.append(f"month {y:04d}-{mth:02d} has no settled leg")
            y, mth = (y + 1, 1) if mth == 12 else (y, mth + 1)
    else:
        missing.append("no settled legs at all")
    # months covered only by an open (unsettled) leg: fine iff it is the last
    open_leg = [t for t in trades if t.get('settle_value') is None]
    if open_leg and open_leg[-1]['expiry'] <= WINDOW_END:
        missing.append(f"leg expiring {open_leg[-1]['expiry']} never settled "
                       f"inside the window")
    # 2. roll/expiry inputs
    for t in trades:
        if t['roll_date'] not in closes:
            missing.append(f"roll {t['roll_date']} has no underlying close")
        if t.get('settle_value') is not None and opens.get(t['expiry']) is None:
            missing.append(f"expiry {t['expiry']} has no SOQ input "
                           f"(^GSPC open NULL — close fallback)")
    for d, why in out['skips']:
        missing.append(f"roll {d} skipped: {why}")
    # 3. NAV-row contiguity over trading days
    daily_dates = {d['date'] for d in out['daily']}
    if daily_dates:
        d_lo, d_hi = min(daily_dates), max(daily_dates)
        for d in days:
            if d_lo <= d <= d_hi and d not in daily_dates:
                missing.append(f"trading day {d} has no NAV row")
    return missing


def main():
    global WINDOW_START, WINDOW_END
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', default='BXM,PUT')
    ap.add_argument('--fills', default='1.0,0.0')
    ap.add_argument('--window-start', default=None,
                    help='Override WINDOW_START (YYYY-MM-DD); default comes from kat_bxm_put.py')
    ap.add_argument('--window-end', default=None,
                    help='Override WINDOW_END (YYYY-MM-DD); default comes from kat_bxm_put.py')
    ap.add_argument('--round-label', default=None)
    args = ap.parse_args()
    engine_sha256 = engine_version.assert_engine_matches()
    if args.window_start:
        WINDOW_START = dt.date.fromisoformat(args.window_start)
    if args.window_end:
        WINDOW_END = dt.date.fromisoformat(args.window_end)

    conn = db.get_connection()
    results = {}
    for index in [x.strip() for x in args.index.split(',')]:
        ref = load_ref(index)
        for f in [float(x) for x in args.fills.split(',')]:
            engine = SPXEngine(fill_frac=f, mark_mode='mid')
            days = sorted(d for d in engine.closes()
                          if WINDOW_START <= d <= WINDOW_END)
            divs = {}
            if index == 'BXM':
                divs = spx_dividends(conn, spy_closes(conn), engine.closes())
            out = run_index(engine, index, days, divs, ref)
            m = metrics(out['daily'])
            verdict, fails = judge(m)
            # gap_remediation_v1 step 4: completeness gate — a run with
            # silently dropped periods is FAILED regardless of tolerances.
            missing_items = completeness_gate(out, days,
                                              rolls=engine.monthly_expiries(),
                                              closes=engine.closes(),
                                              opens=engine.opens(), ref=ref)
            m['missing_items'] = missing_items
            if missing_items:
                verdict = 'FAIL_INCOMPLETE'
                fails = fails + [f'INCOMPLETE: {x}' for x in missing_items]
            status = 'SUCCESS' if not missing_items else 'FAILED'
            m['skips'] = out['skips']
            m['n_intrinsic_marks'] = sum(1 for d in out['daily']
                                         if d['note'] == 'INTRINSIC_MARK')
            m['n_assignment_events'] = 0
            m['soq_settlement'] = 'expiry-morning ^GSPC open (SOQ proxy)'
            m['soq_open_fallbacks'] = out['soq_fallbacks']

            cur = conn.cursor()
            cur.execute(
                """INSERT INTO deriv.kat_runs (index_name, params, status, metrics,
                                               verdict, finished_at, round_label)
                   VALUES (%s,%s,%s,%s,%s,now(),%s) RETURNING run_id""",
                (index, json.dumps({'fill_frac': f, 'mark_mode': 'mid',
                                    'symbol': 'SPX', 'european': True,
                                    'underlying_source': 'gold.daily_ohlcv:^GSPC',
                                    'gold_data_tag': 'gapfix_v1_20261014',
                                    'gold_data_load': 'heal_gold_from_silver_v1.py 2026-10-14, +2,501,173 rows; ^GSPC 24/24 March-2026 sessions',
                                    'bxm_dividend_approx': 'SPY_div x (SPX/SPY) at ex-date',
                                    'window': [str(WINDOW_START), str(WINDOW_END)],
                                    'tolerances': TOL,
                                    'bug_fix': BUGFIX_TAG,
                                    'engine_sha256': engine_sha256,
                                    'round_label': args.round_label,
                                    'harness_fix': '2026-10-15 completeness_gate: SOQ-input check applies to settled legs only; final open leg (expiry > WINDOW_END) exempt'}),
                 status, json.dumps(m), verdict, args.round_label))
            run_id = cur.fetchone()[0]
            for d in out['daily']:
                cur.execute(
                    """INSERT INTO deriv.kat_daily
                       (run_id, trade_date, nav, engine_level, ref_level,
                        ret_engine, ret_ref, note)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, d['date'], d['nav'], d['level'], d['ref'],
                     d['ret'], d['ref_ret'], d['note'] or None))
            for t in out['trades']:
                cur.execute(
                    """INSERT INTO deriv.kat_trades
                       (run_id, roll_date, expiry, strike, option_right,
                        contract_id, fill_price, settle_value, commission, note)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, t['roll_date'], t['expiry'], t['strike'],
                     t['right'], t['contract_id'], t['fill_price'],
                     t['settle_value'], t['commission'], t['note']))
            conn.commit()
            engine.close()

            key = f'SPX:{index}@f={f}'
            results[key] = {'run_id': str(run_id), 'verdict': verdict,
                            'fails': fails, 'cagr_diff': m['cagr_diff'],
                            'monthly_corr': m['monthly_corr'],
                            'worst_month_diff': m['worst_month_diff'],
                            'n_months_over_band': m['n_months_over_band'],
                            'maxdd_diff': m['maxdd_diff'],
                            'cagr_engine': m['cagr_engine'],
                            'cagr_ref': m['cagr_ref'],
                            'n_intrinsic_marks': m['n_intrinsic_marks'],
                            'skips': m['skips']}
            print(f"{key}: {verdict} cagr_diff={m['cagr_diff']} "
                  f"corr={m['monthly_corr']} worst={m['worst_month_diff']} "
                  f"n_over={m['n_months_over_band']} dd_diff={m['maxdd_diff']}",
                  flush=True)
            if fails:
                print('  FAILS:', fails, flush=True)

    conn.close()
    summary_path = os.path.expanduser(
        '~/.hermes/profiles/qr_etl/workspace/deriv_engine_kat/kat_results_spx.json')
    with open(summary_path, 'w') as fh:
        json.dump(results, fh, indent=2)
    print('wrote', summary_path)


if __name__ == '__main__':
    main()
