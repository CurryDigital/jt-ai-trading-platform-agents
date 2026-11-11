#!/usr/bin/env python3
"""Independent verification of consumption.strategy_paper_deployment_current
(t_33ffe715).

Deliberately does NOT import rebuild_paper_positions: every quantity is
re-derived from raw tables with its own SQL so a bug in the writer's formula
cannot be inherited by the check.

Per strategy:
  invested_notional  = SUM(n_shares * entry_price) over OPEN rows in
                       gold.paper_trades_synthetic
  pending_notional   = SUM(n_shares * latest silver.unified_prices close)
                       over pending OPEN rows in gold.paper_pending_orders
  target_notional    = assigned_capital * sum(BUY scores) /
                       (sum(BUY scores) + CASH score) from
                       gold.strategy_ticker_scores
  assigned_capital   = gold.strategy_registry.assigned_capital
  deployment_ratio   = (invested + pending) / target
  capital_util       = (invested + pending) / assigned_capital

PASS when the persisted row matches within tolerance (abs $1 on notionals,
1e-4 on ratios). Prints PASS/FAIL per strategy plus a summary line; exit 1
on any FAIL.

Usage:
  python3 verify_paper_deployment_ratio.py [STRATEGY_ID ...]
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'shared', 'scripts'))
from db import get_connection  # noqa: E402

TOL_NOTIONAL = 1.0
TOL_RATIO = 1e-4


def recompute(cur, sid):
    cur.execute("""
        SELECT assigned_capital FROM gold.strategy_registry
        WHERE strategy_id = %s
    """, (sid,))
    row = cur.fetchone()
    if not row:
        return None
    capital = float(row[0] or 0)

    cur.execute("""
        SELECT COALESCE(SUM(n_shares * entry_price), 0)
        FROM gold.paper_trades_synthetic
        WHERE strategy_id = %s AND status = 'open'
    """, (sid,))
    invested = float(cur.fetchone()[0] or 0)

    cur.execute("""
        SELECT p.ticker, p.n_shares, u.close
        FROM gold.paper_pending_orders p
        LEFT JOIN LATERAL (
            SELECT close FROM silver.unified_prices u2
            WHERE u2.ticker = p.ticker
            ORDER BY u2.date DESC LIMIT 1
        ) u ON TRUE
        WHERE p.strategy_id = %s AND p.status = 'pending' AND p.order_kind = 'OPEN'
    """, (sid,))
    pending = sum(float(n or 0) * float(c) for _t, n, c in cur.fetchall() if c)

    cur.execute("""
        SELECT ticker, score, signal_action
        FROM gold.strategy_ticker_scores
        WHERE strategy_id = %s
    """, (sid,))
    buy_sum = 0.0
    cash_score = 0.0
    for ticker, score, action in cur.fetchall():
        s = max(0.0, float(score or 0))
        if action == 'BUY':
            buy_sum += s
        elif ticker == 'CASH':
            cash_score += s
    total = buy_sum + cash_score
    target = capital * (buy_sum / total) if total > 0 else 0.0

    committed = invested + pending
    return {
        'assigned_capital': capital,
        'invested_notional': invested,
        'pending_open_notional': pending,
        'committed_notional': committed,
        'target_notional': target,
        'deployment_ratio': committed / target if target > 0 else None,
        'capital_utilization': committed / capital if capital > 0 else None,
    }


def fetch_persisted(cur, sid):
    cur.execute("""
        SELECT run_date, assigned_capital, target_notional, invested_notional,
               pending_open_notional, committed_notional, deployment_ratio,
               capital_utilization, skips_by_kind, updated_at
        FROM consumption.strategy_paper_deployment_current
        WHERE strategy_id = %s
    """, (sid,))
    row = cur.fetchone()
    if not row:
        return None
    return {
        'run_date': row[0],
        'assigned_capital': float(row[1] or 0),
        'target_notional': float(row[2] or 0),
        'invested_notional': float(row[3] or 0),
        'pending_open_notional': float(row[4] or 0),
        'committed_notional': float(row[5] or 0),
        'deployment_ratio': float(row[6]) if row[6] is not None else None,
        'capital_utilization': float(row[7]) if row[7] is not None else None,
        'skips_by_kind': row[8],
        'updated_at': row[9],
    }


def close(a, b, tol):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol


def main():
    sids = sys.argv[1:]
    conn = get_connection()
    cur = conn.cursor()
    if not sids:
        cur.execute("SELECT strategy_id FROM consumption.strategy_paper_deployment_current ORDER BY 1")
        sids = [r[0] for r in cur.fetchall()]
    if not sids:
        print('No strategies to verify.')
        return 1

    fails = 0
    for sid in sids:
        exp = recompute(cur, sid)
        got = fetch_persisted(cur, sid)
        if exp is None:
            print(f'FAIL {sid}: not in gold.strategy_registry')
            fails += 1
            continue
        if got is None:
            print(f'FAIL {sid}: no row in consumption.strategy_paper_deployment_current '
                  f'(expected ratio {exp["deployment_ratio"]})')
            fails += 1
            continue
        checks = [
            ('assigned_capital', exp['assigned_capital'], got['assigned_capital'], TOL_NOTIONAL),
            ('target_notional', exp['target_notional'], got['target_notional'], TOL_NOTIONAL),
            ('invested_notional', exp['invested_notional'], got['invested_notional'], TOL_NOTIONAL),
            ('pending_open_notional', exp['pending_open_notional'], got['pending_open_notional'], TOL_NOTIONAL),
            ('committed_notional', exp['committed_notional'], got['committed_notional'], TOL_NOTIONAL),
            ('deployment_ratio', exp['deployment_ratio'], got['deployment_ratio'], TOL_RATIO),
            ('capital_utilization', exp['capital_utilization'], got['capital_utilization'], TOL_RATIO),
        ]
        bad = [(k, e, g) for k, e, g, tol in checks if not close(e, g, tol)]
        if bad:
            fails += 1
            print(f'FAIL {sid}:')
            for k, e, g in bad:
                print(f'    {k}: expected {e} persisted {g}')
        else:
            ratio = f"{got['deployment_ratio']:.2%}" if got['deployment_ratio'] is not None else 'n/a'
            util = f"{got['capital_utilization']:.2%}" if got['capital_utilization'] is not None else 'n/a'
            print(f'PASS {sid}: run_date={got["run_date"]} '
                  f'committed=${got["committed_notional"]:,.2f} '
                  f'target=${got["target_notional"]:,.2f} ratio={ratio} '
                  f'util={util} skips={got["skips_by_kind"]}')
    conn.close()
    print(f'\n{len(sids) - fails}/{len(sids)} strategies PASS')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
