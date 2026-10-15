#!/usr/bin/env python3
"""
BXM/PUT known-answer test runner (sequencing step 2).

Replicates CBOE BXM and PUT methodology on SPY quoted chains (free window,
2023-06-16 first roll -> 2026-09-30) and judges the result against the
tolerances pre-declared in workspace/deriv_engine_kat/KAT_PLAN.md.

Per index x fill_frac in {1.0, 0.0}: one deriv.kat_runs row + daily series +
roll trades. Metrics vs official CBOE daily levels (reference/*.csv).

Run with /usr/bin/python3.
Usage: kat_bxm_put.py [--index BXM,PUT] [--fills 1.0,0.0]
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/silver/thetadata'))
from engine import (Engine, COMMISSION_PER_CONTRACT, MIN_COMMISSION, MULT,
                    early_assignment, BUGFIX_TAG)  # noqa: E402
import db  # noqa: E402
import engine_version  # noqa: E402

REF_DIR = os.path.expanduser(
    '~/.hermes/profiles/qr_etl/workspace/deriv_engine_kat/reference')
WINDOW_START = dt.date(2023, 6, 1)
WINDOW_END = dt.date(2026, 9, 30)

# FROZEN tolerances — mirror KAT_PLAN.md exactly. Do not edit without editing
# the plan first (plan is the declaration, this is the execution of it).
TOL = {'cagr_abs': 0.0150, 'monthly_corr': 0.970, 'worst_month': 0.020,
       'n_months_over': 3, 'month_over_band': 0.010, 'maxdd_abs': 0.025}


def load_ref(index: str) -> dict:
    out = {}
    with open(os.path.join(REF_DIR, f'{index}_History.csv')) as f:
        for row in csv.DictReader(f):
            d = dt.datetime.strptime(row['DATE'], '%m/%d/%Y').date()
            out[d] = float(row[index])
    return out


def trading_days(closes: dict) -> list:
    return sorted(d for d in closes if WINDOW_START <= d <= WINDOW_END)


def dividends(conn) -> dict:
    cur = conn.cursor()
    cur.execute("""SELECT ex_date, amount FROM deriv.underlying_dividends
                   WHERE underlying='SPY'""")
    out = {d: float(a) for d, a in cur.fetchall()}
    cur.close()
    return out


def run_index(engine: Engine, index: str, days: list, divs: dict,
              ref: dict) -> dict:
    """Run one replication. Returns daily rows + trade rows + skip log."""
    is_call = index == 'BXM'
    right = 'C' if is_call else 'P'
    expiries = engine.monthly_expiries()
    rolls = [e for e in expiries if WINDOW_START <= e <= WINDOW_END]

    closes = engine.closes()
    daily, trades, skips = [], [], []
    shares = 0.0
    cash = 0.0
    pending_rebuy = 0.0  # EEP-2: BXM shares delivered on assignment, re-bought at the roll
    leg = None          # dict(contract_id, expiry, strike, right)
    nav0 = None
    ref0 = None
    prev_day = None

    roll_set = set(rolls)
    # EEP-1: call-assignment eval days = last trading day before each ex-date
    ex_eval = {}
    if is_call:
        for ex, amt in divs.items():
            prior = [x for x in days if x < ex]
            if prior:
                ex_eval[prior[-1]] = amt
    events = []

    def leg_time_value(leg_, d_, S_):
        """Time value of the live short leg. Quoted mid when available; the
        7-60 DTE pull has no final-week quotes, so fall back to the CRR
        American model at the contract's last COMPUTED IV (fallback 0.15).
        Returns (tv, source)."""
        intrinsic_ = (max(S_ - leg_['strike'], 0.0) if is_call
                      else max(leg_['strike'] - S_, 0.0))
        q_leg = engine.quote_series(leg_['contract_id']).get(d_)
        if q_leg and q_leg['mid'] is not None:
            return q_leg['mid'] - intrinsic_, 'QUOTED'
        cur_ = engine.conn.cursor()
        cur_.execute("""SELECT implied_vol FROM silver.option_eod_greeks
                        WHERE contract_id=%s AND trade_date < %s
                          AND greek_source='COMPUTED' AND implied_vol IS NOT NULL
                        ORDER BY trade_date DESC LIMIT 1""",
                     (leg_['contract_id'], d_))
        row_ = cur_.fetchone()
        cur_.close()
        iv_ = float(row_[0]) if row_ else 0.15
        T_ = (leg_['expiry'] - d_).days / 365.0
        r_ = engine.rate_on(d_)
        divs_ = [((ex - d_).days / 365.0, a) for ex, a in divs.items()
                 if d_ < ex <= leg_['expiry']]
        import numpy as _np
        from computed_greeks import price_batch as _pb
        p_ = _pb(_np.array([iv_]), _np.array([leg_['strike']]),
                 _np.array([is_call]), S_, r_, T_, divs_)[0]
        return float(p_) - intrinsic_, 'MODEL'

    for i, d in enumerate(days):
        if d < rolls[0]:
            continue
        S = closes[d]
        # accrue interest on cash for calendar days since prev day
        if prev_day is not None:
            gap = (d - prev_day).days
            r = engine.rate_on(prev_day)
            cash *= (1.0 + r / 360.0) ** gap
        note = ''

        # settle expiring leg at intrinsic vs close
        settle = None
        if leg is not None and d == leg['expiry']:
            intrinsic = max(S - leg['strike'], 0.0) if is_call \
                else max(leg['strike'] - S, 0.0)
            settle = intrinsic
            cash -= intrinsic * MULT
            trades[-1]['settle_value'] = intrinsic
            leg = None

        # roll into new leg
        if leg is None and d in roll_set:
            # EEP-2: unwind the assigned stock leg at the scheduled roll
            # (ENGINE_SPEC §4). PUT: sell the assigned shares. BXM: re-buy
            # the delivered shares to re-form the buy-write (unconditional —
            # the reference holds the stock leg whether or not a new call
            # can be sold).
            if not is_call and shares > 0:
                cash += shares * S
                shares = 0.0
            if is_call and pending_rebuy > 0:
                cash -= pending_rebuy * S
                shares += pending_rebuy
                pending_rebuy = 0.0
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
                        # establish base: BXM buys 100 sh; PUT posts collateral
                        if is_call:
                            shares = (100.0 * S) / S  # exactly 100 shares
                            nav0 = 100.0 * S
                        else:
                            cash += sel['strike'] * MULT  # collateral posted
                            nav0 = sel['strike'] * MULT
                        ref_candidates = [rd for rd in ref if rd <= d]
                        ref0 = ref[max(ref_candidates)] if ref_candidates else None

        # dividends reinvested (BXM) at close on ex-date; assigned PUT shares
        # collect the dividend as cash while held (EEP-2)
        if is_call and d in divs and shares > 0:
            cash_div = divs[d] * shares
            shares += cash_div / S
        elif not is_call and d in divs and shares > 0:
            cash += divs[d] * shares

        # EEP-1 early assignment (ENGINE_SPEC section 4, user directive
        # 2026-10-02): daily check on the live short leg. Time value is the
        # quoted mid when present, else the CRR model at last known IV (the
        # 7-60 DTE pull has no final-week quotes — and SPY ex-dates coincide
        # with quarterly expiry Fridays, so the binding cases are exactly
        # those 0-1 DTE legs). Stock flows settle at the strike immediately;
        # the short option is then re-established if a sellable quote exists.
        if leg is not None and d < leg['expiry']:
            tv_leg, tv_src = leg_time_value(leg, d, S)
            intrinsic_now = (max(S - leg['strike'], 0.0) if is_call
                             else max(leg['strike'] - S, 0.0))
            trig = early_assignment(
                is_call, leg['strike'], S, intrinsic_now + tv_leg,
                leg['expiry'], d, engine.rate_on(d), ex_eval.get(d))
            if trig:
                etype, tval = trig
                events.append({
                    'event_date': d, 'event_type': etype,
                    'contract_id': leg['contract_id'], 'right': right,
                    'strike': leg['strike'], 'spot': S,
                    'intrinsic': intrinsic_now,
                    'time_value': tv_leg,
                    'trigger_value': tval,
                    'detail': {'expiry': str(leg['expiry']),
                               'tv_source': tv_src,
                               'fill_frac': engine.fill_frac}})
                # EEP-2 (2026-10-07, ENGINE_SPEC §4: "Assignment creates the
                # synthetic STOCK leg"): the assigned stock flow is HELD to
                # the next scheduled roll — no liquidation at the
                # assignment-day close, no same-day re-establishment.
                # Put: pay the strike, hold the 100 shares (economically the
                # same delta exposure as the deep-ITM short put the European
                # reference still carries -> path attribution survives).
                # Call: deliver the covered 100 at the strike, hold cash to
                # the roll, re-buy there. The assigned option leg settles at
                # intrinsic on the event date.
                if is_call:
                    shares -= 100.0
                    cash += leg['strike'] * MULT
                    pending_rebuy += 100.0
                else:
                    cash -= leg['strike'] * MULT
                    shares += 100.0
                trades[-1]['settle_value'] = intrinsic_now
                leg = None

        # mark to market (EEP-2: shares held after PUT assignment count in nav)
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

    # returns
    for j in range(1, len(daily)):
        daily[j]['ret'] = daily[j]['nav'] / daily[j - 1]['nav'] - 1.0
        if daily[j]['ref'] and daily[j - 1]['ref']:
            daily[j]['ref_ret'] = daily[j]['ref'] / daily[j - 1]['ref'] - 1.0
        else:
            daily[j]['ref_ret'] = None
    daily[0]['ret'] = None
    daily[0]['ref_ret'] = None
    return {'daily': daily, 'trades': trades, 'skips': skips, 'events': events}


def metrics(daily: list) -> dict:
    """Compute comparison metrics over fully-covered calendar months."""
    eng = [(d['date'], d['ret']) for d in daily if d['ret'] is not None]
    both = [(d['date'], d['ret'], d['ref_ret']) for d in daily
            if d['ret'] is not None and d['ref_ret'] is not None]
    if not both:
        return {'error': 'no overlapping dates'}

    # CAGR
    d0, d1 = daily[0]['date'], daily[-1]['date']
    yrs = (d1 - d0).days / 365.25
    nav_end = daily[-1]['nav'] / daily[0]['nav']
    ref_first = next(d for d in daily if d['ref'])
    ref_last = next(d for d in reversed(daily) if d['ref'])
    ref_end = ref_last['ref'] / ref_first['ref']
    cagr_eng = nav_end ** (1 / yrs) - 1
    cagr_ref = ref_end ** (1 / yrs) - 1

    # monthly returns (complete months only)
    def monthly(pairs):
        out = {}
        for d_, r in pairs:
            key = (d_.year, d_.month)
            out.setdefault(key, []).append(r)
        return {k: math.prod(1 + x for x in v) - 1 for k, v in out.items()}

    m_eng = monthly([(d, r) for d, r, _ in both])
    m_ref = monthly([(d, rr) for d, _, rr in both])
    common = sorted(k for k in m_eng if k in m_ref)
    # drop incomplete months (first/last partial)
    complete = common[1:-1] if len(common) > 2 else common
    me = [m_eng[k] for k in complete]
    mr = [m_ref[k] for k in complete]
    n = len(me)
    mean_e = sum(me) / n
    mean_r = sum(mr) / n
    cov = sum((a - mean_e) * (b - mean_r) for a, b in zip(me, mr))
    se = math.sqrt(sum((a - mean_e) ** 2 for a in me))
    sr = math.sqrt(sum((b - mean_r) ** 2 for b in mr))
    corr = cov / (se * sr) if se > 0 and sr > 0 else float('nan')
    diffs = [abs(a - b) for a, b in zip(me, mr)]
    worst = max(diffs)
    n_over = sum(1 for x in diffs if x > TOL['month_over_band'])

    # maxDD on levels
    def maxdd(vals):
        peak, mdd = vals[0], 0.0
        for v in vals:
            peak = max(peak, v)
            mdd = max(mdd, (peak - v) / peak)
        return mdd
    dd_e = maxdd([d['nav'] for d in daily])
    dd_r = maxdd([d['ref'] for d in daily if d['ref']])

    return {'window': [str(d0), str(d1)], 'years': round(yrs, 3),
            'cagr_engine': round(cagr_eng, 5), 'cagr_ref': round(cagr_ref, 5),
            'cagr_diff': round(abs(cagr_eng - cagr_ref), 5),
            'n_months': n, 'monthly_corr': round(corr, 4),
            'worst_month_diff': round(worst, 5),
            'n_months_over_band': n_over,
            'maxdd_engine': round(dd_e, 5), 'maxdd_ref': round(dd_r, 5),
            'maxdd_diff': round(abs(dd_e - dd_r), 5),
            'monthly_table': [
                {'month': f'{k[0]}-{k[1]:02d}', 'engine': round(m_eng[k], 5),
                 'ref': round(m_ref[k], 5),
                 'diff': round(m_eng[k] - m_ref[k], 5)} for k in complete]}


def judge(m: dict) -> tuple:
    fails = []
    if abs(m['cagr_diff']) > TOL['cagr_abs']:
        fails.append(f"cagr_diff {m['cagr_diff']} > {TOL['cagr_abs']}")
    if m['monthly_corr'] < TOL['monthly_corr']:
        fails.append(f"monthly_corr {m['monthly_corr']} < {TOL['monthly_corr']}")
    if m['worst_month_diff'] > TOL['worst_month']:
        fails.append(f"worst_month {m['worst_month_diff']} > {TOL['worst_month']}")
    if m['n_months_over_band'] > TOL['n_months_over']:
        fails.append(f"months_over_band {m['n_months_over_band']} > {TOL['n_months_over']}")
    if m['maxdd_diff'] > TOL['maxdd_abs']:
        fails.append(f"maxdd_diff {m['maxdd_diff']} > {TOL['maxdd_abs']}")
    return ('PASS' if not fails else 'FAIL'), fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', default='BXM,PUT')
    ap.add_argument('--fills', default='1.0,0.0')
    ap.add_argument('--round-label', default=None)
    args = ap.parse_args()
    engine_sha256 = engine_version.assert_engine_matches()

    conn = db.get_connection()
    divs = dividends(conn)

    results = {}
    for index in [x.strip() for x in args.index.split(',')]:
        ref = load_ref(index)
        for f in [float(x) for x in args.fills.split(',')]:
            engine = Engine(fill_frac=f, mark_mode='mid')
            days = trading_days(engine.closes())
            out = run_index(engine, index, days, divs, ref)
            m = metrics(out['daily'])
            verdict, fails = judge(m)
            m['skips'] = out['skips']
            m['n_intrinsic_marks'] = sum(1 for d in out['daily']
                                         if d['note'] == 'INTRINSIC_MARK')
            m['n_assignment_events'] = len(out['events'])

            cur = conn.cursor()
            cur.execute(
                """INSERT INTO deriv.kat_runs (index_name, params, status, metrics,
                                               verdict, finished_at, round_label)
                   VALUES (%s,%s,'SUCCESS',%s,%s,now(),%s) RETURNING run_id""",
                (index, json.dumps({'fill_frac': f, 'mark_mode': 'mid',
                                    'window': [str(WINDOW_START), str(WINDOW_END)],
                                    'tolerances': TOL,
                                    'bug_fix': BUGFIX_TAG,
                                    'engine_sha256': engine_sha256,
                                    'round_label': args.round_label}),
                 json.dumps(m), verdict, args.round_label))
            run_id = cur.fetchone()[0]
            for e in out['events']:
                cur.execute(
                    """INSERT INTO deriv.kat_events
                       (run_id, event_date, event_type, contract_id,
                        option_right, strike, spot, intrinsic, time_value,
                        trigger_value, detail)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, e['event_date'], e['event_type'], e['contract_id'],
                     e['right'], e['strike'], e['spot'], e['intrinsic'],
                     e['time_value'], e['trigger_value'], json.dumps(e['detail'])))
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

            key = f'{index}@f={f}'
            results[key] = {'run_id': str(run_id), 'verdict': verdict,
                            'fails': fails,
                            'cagr_diff': m['cagr_diff'],
                            'monthly_corr': m['monthly_corr'],
                            'worst_month_diff': m['worst_month_diff'],
                            'n_months_over_band': m['n_months_over_band'],
                            'maxdd_diff': m['maxdd_diff'],
                            'n_months': m['n_months'],
                            'skips': m['skips'],
                            'n_intrinsic_marks': m['n_intrinsic_marks'],
                            'n_assignment_events': m['n_assignment_events'],
                            'cagr_engine': m['cagr_engine'],
                            'cagr_ref': m['cagr_ref']}
            print(f"{key}: {verdict} cagr_diff={m['cagr_diff']} "
                  f"corr={m['monthly_corr']} worst={m['worst_month_diff']} "
                  f"n_over={m['n_months_over_band']} dd_diff={m['maxdd_diff']} "
                  f"assignments={m['n_assignment_events']}", flush=True)
            if fails:
                print('  FAILS:', fails, flush=True)

    conn.close()
    summary_path = os.path.expanduser(
        '~/.hermes/profiles/qr_etl/workspace/deriv_engine_kat/kat_results.json')
    with open(summary_path, 'w') as fh:
        json.dump(results, fh, indent=2)
    print('wrote', summary_path)


if __name__ == '__main__':
    main()
