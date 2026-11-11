#!/usr/bin/env python3
"""One-time / on-demand seeder for consumption.strategy_paper_deployment_current
(t_33ffe715).

Populates the per-book deployment-ratio surface from CURRENT state without
mutating any positions, signals, or orders. rebuild_paper_positions.py owns
the per-run refresh going forward; this script exists so the surface has
rows immediately after deployment (and to re-seed after disasters) without
firing a mid-cycle rebalance.

Semantics are identical to the rebalancer writer: it imports the engine's
own helpers (fetch_active_strategies / fetch_scores / fetch_prices /
resolve_cap_with_source / compute_deployment) so the seeded numbers are
exactly what the next scheduled run would persist.

PAPER_UAT strategies get no row (DB ledger empty by design).
Rows for strategies no longer in the active rebuild set are deleted
(same hygiene as the rebalancer's full-run stale cleanup).

Usage:
  python3 backfill_paper_deployment_current.py [--strategy-id SID] [--dry-run]
"""
import sys, os, argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'shared', 'scripts'))
from db import get_connection  # noqa: E402

import rebuild_paper_positions as rpp  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--strategy-id', default=None,
                    help='Seed only this strategy_id (default: all active)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Compute and print, roll back all writes')
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    conn = get_connection()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        rpp.ensure_skip_tables(cur)  # creates the deployment table if missing

        strategies = rpp.fetch_active_strategies(cur, strategy_id=args.strategy_id)
        if not strategies:
            print('No active PAPER/SIMULATION/PAPER_UAT strategies matched.')
            conn.commit()
            return 1
        strategy_ids = [s['strategy_id'] for s in strategies]

        all_tickers = list({t for s in strategies for t in s['universe']})
        prices = rpp.fetch_prices(cur, all_tickers)
        close_map = rpp.close_map_of(prices)
        signals = rpp.fetch_scores(cur, strategy_ids)
        cap_overrides = rpp.fetch_cap_overrides(cur, strategy_ids)
        paper_designs = rpp.fetch_paper_designs(cur, strategy_ids)

        # Current skip kinds per strategy (for skips_by_kind on the seeded row;
        # the next real run replaces it with the run's own skip list).
        skip_kinds = {}
        cur.execute("""
            SELECT strategy_id, skip_kind, COUNT(*)
            FROM consumption.strategy_paper_skips_current
            WHERE strategy_id = ANY(%s)
            GROUP BY strategy_id, skip_kind
        """, (strategy_ids,))
        for sid, kind, n in cur.fetchall():
            skip_kinds.setdefault(sid, {})[kind] = int(n)

        seeded = 0
        for s in strategies:
            sid = s['strategy_id']
            eff_pct, cap_source = rpp.resolve_cap_with_source(
                cap_overrides, paper_designs, sid, 0.20)
            skipped = [{'skip_kind': k} for k in skip_kinds.get(sid, {})
                       for _ in range(skip_kinds[sid][k])]
            dep = rpp.write_deployment(cur, today, s, signals.get(sid, []),
                                       skipped, close_map, eff_pct)
            if dep is None:
                print(f'  {sid}: PAPER_UAT - no row (broker is book-of-record)')
                continue
            seeded += 1
            ratio = (f"{dep['deployment_ratio']:.1%}"
                     if dep['deployment_ratio'] is not None else 'n/a')
            util = (f"{dep['capital_utilization']:.1%}"
                    if dep['capital_utilization'] is not None else 'n/a')
            print(f'  {sid}: committed ${dep["committed_notional"]:,.2f} '
                  f'(invested ${dep["invested_notional"]:,.2f} + pending '
                  f'${dep["pending_open_notional"]:,.2f}) / target '
                  f'${dep["target_notional"]:,.2f} = {ratio} '
                  f'[util {util} of ${dep["assigned_capital"]:,.2f}; '
                  f'cap {eff_pct:.0%} via {cap_source}]')

        if not args.strategy_id:
            cur.execute(rpp.SQL_DELETE_STALE_DEPLOYMENT_CURRENT, (strategy_ids,))
            if cur.rowcount:
                print(f'  Removed {cur.rowcount} stale deployment rows '
                      f'(strategies no longer active)')

        if args.dry_run:
            conn.rollback()
            print(f'DRY RUN: rolled back ({seeded} rows computed, none persisted).')
        else:
            conn.commit()
            print(f'Seeded {seeded} deployment rows (run_date {today}).')
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
