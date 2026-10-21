#!/usr/bin/env python3
"""
Sync gold.strategy_registry.in_market_capital from the canonical paper ledger.

Kanban t_9579ff7c (2026-07-31): registry bookkeeping was write-once
(promotion SQL set in_market_capital = assigned_capital) and never
recomputed, so it contradicted the actual paper book.

Source of truth: gold.paper_trades_synthetic (status='open').
  - This is the engine book written by rebuild_paper_positions.py /
    refresh_paper_trades_synthetic.py (round lots, capital-capped) and is
    the same ledger that feeds consumption.portfolio_positions_current.
  - gold.paper_trades is NOT used: its writer (refresh_paper_trades.py)
    is orphaned (not in the signal cycle or pipeline manifest), its rows
    are stale, and it carries NULL n_shares artifacts when signal_criteria
    has no parseable weight.

Semantics:
  - execution_mode='PAPER' AND monitoring is_active=true:
      in_market_capital = COALESCE(SUM(n_shares * entry_price) over open
      synthetic rows, 0). Flat books (e.g. all-SELL signals, monthly
      mostly-cash strategies) legitimately compute to 0.
  - execution_mode='PAPER' AND NOT actively monitored (retired/stopped):
      in_market_capital = 0. The synthetic ledger keeps shadow rows for
      approved-but-unmonitored strategies (t_f51d67fe); those are not
      deployed capital and must not surface as in-market.
  - SIMULATION rows are not touched.

Runs in the signal cycle AFTER rebuild_paper_positions.py and
sync_paper_positions_current.py. Idempotent: only writes when the value
actually changes (IS DISTINCT FROM), so updated_at is not churned.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import datetime
import pytz

HKT = pytz.timezone("Asia/Hong_Kong")

SYNC_SQL = """
WITH monitored AS (
    SELECT strategy_id FROM gold.strategy_paper_monitoring WHERE is_active = true
),
deployed AS (
    SELECT strategy_id, SUM(n_shares * entry_price) AS in_market
    FROM gold.paper_trades_synthetic
    WHERE status = 'open'
      AND strategy_id IN (SELECT strategy_id FROM monitored)
    GROUP BY strategy_id
),
computed AS (
    SELECT r.strategy_id,
           CASE
               WHEN m.strategy_id IS NOT NULL THEN ROUND(COALESCE(d.in_market, 0), 2)
               ELSE 0
           END AS new_in_market
    FROM gold.strategy_registry r
    LEFT JOIN monitored m ON m.strategy_id = r.strategy_id
    LEFT JOIN deployed d ON d.strategy_id = r.strategy_id
    WHERE r.execution_mode = 'PAPER'
)
UPDATE gold.strategy_registry r
SET in_market_capital = c.new_in_market,
    updated_at = NOW()
FROM computed c
WHERE r.strategy_id = c.strategy_id
  AND r.in_market_capital IS DISTINCT FROM c.new_in_market
RETURNING r.strategy_id, c.new_in_market;
"""

VERIFY_SQL = """
SELECT r.strategy_id, r.status, r.assigned_capital, r.in_market_capital,
       COALESCE(pm.is_active, false) AS monitored
FROM gold.strategy_registry r
LEFT JOIN gold.strategy_paper_monitoring pm ON pm.strategy_id = r.strategy_id
WHERE r.execution_mode = 'PAPER'
ORDER BY r.strategy_id;
"""


def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SYNC_SQL)
    changed = cur.fetchall()
    conn.commit()

    now_hkt = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S HKT")
    print(f"[{now_hkt}] in_market_capital sync: {len(changed)} row(s) updated")
    for sid, val in changed:
        print(f"   {sid}: -> {float(val):,.2f}")

    cur.execute(VERIFY_SQL)
    print(f"\nPAPER registry state after sync:")
    for sid, status, assigned, in_mkt, monitored in cur.fetchall():
        flag = "monitored" if monitored else "NOT monitored"
        print(f"   {sid}: status={status} assigned={float(assigned or 0):,.2f} "
              f"in_market={float(in_mkt or 0):,.2f} ({flag})")

    cur.close()
    conn.close()


if __name__ == "__main__":
    run()
