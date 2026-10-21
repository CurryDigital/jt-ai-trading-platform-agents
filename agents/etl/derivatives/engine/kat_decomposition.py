#!/usr/bin/env python3
"""KAT failure decomposition for the latest BXM/PUT runs (per index x fill).

Quantifies, per run:
- monthly corr, annualized tracking error (std of monthly diffs * sqrt(12)),
  daily corr, mean drift (cagr_engine - cagr_ref)
- commission drag: sum(commissions)/nav0/years
- settlement timing wedge: CBOE settles SPX AM (SOQ); we settle at SPY 16:00
  close. Recompute each leg's intrinsic at expiry-day OPEN (stock EOD open)
  and measure the P&L delta for the short leg.
- roll-day concentration of daily return diffs (roll mechanics vs MTM noise)
- spread drag estimate: cagr(f=0) - cagr(f=1) per index
Then: total_gap = timing + commissions + spread_drag + residual.
"""
import sys, math, json, datetime as dt, traceback
from collections import defaultdict
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
import db

MULT = 100


def main():
    conn = db.get_connection()
    cur = conn.cursor()

    # stock opens on expiry dates
    cur.execute("""SELECT trade_date, payload->>'open', payload->>'close'
                   FROM bronze.thetadata_stock_eod_raw WHERE symbol='SPY'""")
    px = {d: (float(o), float(c)) for d, o, c in cur.fetchall()}

    # latest run per (index, fill_frac)
    cur.execute("""
        SELECT DISTINCT ON (index_name, params->>'fill_frac')
               run_id, index_name, params, metrics, verdict
        FROM deriv.kat_runs WHERE verdict IS NOT NULL
        ORDER BY index_name, params->>'fill_frac', created_at DESC""")
    runs = cur.fetchall()
    pj = lambda p: p if isinstance(p, dict) else json.loads(p)
    print(f'runs: {[(r[1], pj(r[2])["fill_frac"], r[4]) for r in runs]}')

    # spread drag per index from the two fills
    cagr_by = {}
    for run_id, idx, params, metrics, verdict in runs:
        m = metrics if isinstance(metrics, dict) else json.loads(metrics)
        f = pj(params)['fill_frac']
        cagr_by[(idx, f)] = (m['cagr_engine'], m['cagr_ref'])

    for run_id, idx, params, metrics, verdict in runs:
        m = metrics if isinstance(metrics, dict) else json.loads(metrics)
        f = pj(params)['fill_frac']
        print(f'\n=== {idx} f={f} verdict={verdict} ===')
        print(f"  cagr engine={m['cagr_engine']:.4f} ref={m['cagr_ref']:.4f} "
              f"diff(engine-ref)={m['cagr_engine']-m['cagr_ref']:+.4f}")

        cur.execute("""SELECT trade_date, nav, ret_engine, ret_ref, note
                       FROM deriv.kat_daily WHERE run_id=%s ORDER BY trade_date""",
                    (run_id,))
        daily = cur.fetchall()
        both = [(d, float(re_), float(rr)) for d, nav, re_, rr, note in daily
                if re_ is not None and rr is not None]
        # daily corr + TE
        de = [x[1] for x in both]; dr = [x[2] for x in both]
        me_, mr_ = sum(de)/len(de), sum(dr)/len(dr)
        cov = sum((a-me_)*(b-mr_) for a, b in zip(de, dr))
        se = math.sqrt(sum((a-me_)**2 for a in de)); sr = math.sqrt(sum((b-mr_)**2 for b in dr))
        dcorr = cov/(se*sr)
        dte = math.sqrt(sum((a-b-(me_-mr_))**2 for a, b in zip(de, dr))/(len(de)-1))*math.sqrt(252)
        # monthly
        mm = defaultdict(lambda: [1.0, 1.0])
        for d, a, b in both:
            mm[(d.year, d.month)][0] *= (1+a)
            mm[(d.year, d.month)][1] *= (1+b)
        keys = sorted(mm)[1:-1]
        mre = [mm[k][0]-1 for k in keys]; mrr = [mm[k][1]-1 for k in keys]
        n = len(mre)
        mme, mmr = sum(mre)/n, sum(mrr)/n
        mcov = sum((a-mme)*(b-mmr) for a, b in zip(mre, mrr))
        mse = math.sqrt(sum((a-mme)**2 for a in mre)); msr = math.sqrt(sum((b-mmr)**2 for b in mrr))
        mcorr = mcov/(mse*msr)
        mte = math.sqrt(sum((a-b-(mme-mmr))**2 for a, b in zip(mre, mrr))/(n-1))*math.sqrt(12)
        drift_month = mme - mmr
        print(f'  monthly: corr={mcorr:.4f} TE(ann)={mte*100:.2f}% '
              f'mean diff={drift_month*100:+.3f}%/mo ({drift_month*12*100:+.2f}%/yr)')
        print(f'  daily:   corr={dcorr:.4f} TE(ann)={dte*100:.2f}%')
        diffs = sorted(zip(keys, (a-b for a, b in zip(mre, mrr))), key=lambda kv: -abs(kv[1]))
        print('  top monthly |diff|: ' + ', '.join(
            f'{k[0]}-{k[1]:02d}:{v*100:+.2f}%' for k, v in diffs[:5]))

        # trades: commissions + settlement timing wedge
        cur.execute("""SELECT roll_date, expiry, strike, option_right, fill_price,
                              settle_value, commission FROM deriv.kat_trades
                       WHERE run_id=%s ORDER BY roll_date""", (run_id,))
        trades = cur.fetchall()
        nav0 = float(daily[0][1])
        d0, d1 = daily[0][0], daily[-1][0]
        yrs = (d1 - d0).days / 365.25
        comm = sum(float(t[6]) for t in trades)
        is_call = idx == 'BXM'
        timing_total = 0.0
        n_open = 0
        for roll, expiry, K, right, fill, settle, c in trades:
            if expiry in px:
                o, cl = px[expiry]
                intr_close = max(cl - float(K), 0.0) if is_call else max(float(K) - cl, 0.0)
                intr_open = max(o - float(K), 0.0) if is_call else max(float(K) - o, 0.0)
                timing_total += (intr_close - intr_open) * MULT
                n_open += 1
        print(f'  trades={len(trades)} commissions total=${comm:.0f} '
              f'({comm/nav0/yrs*100:.3f}%/yr of nav0)')
        print(f'  settle timing (close vs open, n={n_open}): engine P&L delta if '
              f'open-settled = ${-timing_total:+.0f} total '
              f'({-timing_total/nav0/yrs*100:+.3f}%/yr)')

        # roll-day concentration
        expiries = {t[1] for t in trades}
        rolls = {t[0] for t in trades}
        roll_days = rolls | expiries
        on = [abs(a-b) for d, a, b in both if d in roll_days]
        off = [abs(a-b) for d, a, b in both if d not in roll_days]
        print(f'  daily |diff|: roll/expiry days mean={sum(on)/len(on)*100:.3f}% (n={len(on)}), '
              f'other days mean={sum(off)/len(off)*100:.3f}% (n={len(off)})')

        # decomposition
        other_f = 0.0 if f == 1.0 else 1.0
        spread_drag = None
        if (idx, other_f) in cagr_by:
            spread_drag = abs(cagr_by[(idx, 1.0)][0] - cagr_by[(idx, 0.0)][0])
        gap = m['cagr_engine'] - m['cagr_ref']
        comm_c = -comm/nav0/yrs  # drag on engine
        timing_c = -timing_total/nav0/yrs
        spread_c = -(spread_drag if (spread_drag and f == 1.0) else (spread_drag/2 if spread_drag else 0.0))
        resid = gap - (comm_c + timing_c + (spread_c or 0.0))
        print(f'  DECOMP (engine-ref, /yr): total={gap*100:+.2f}% '
              f'= commissions {comm_c*100:+.2f}% + settle-timing {timing_c*100:+.2f}% '
              f'+ spread-drag {(spread_c or 0)*100:+.2f}% + residual {resid*100:+.2f}%')
    conn.close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(2)
