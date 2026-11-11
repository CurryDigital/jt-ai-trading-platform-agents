#!/usr/bin/env python3
"""Backfill declared cost model into gold.paper_trades_synthetic (t_f81b2bb2).

Append-only remediation: adds entry_cost / exit_cost / cost_bps_applied and
restates pnl/pnl_pct net of costs. entry_price / exit_price are NEVER touched.

Cost resolution per row:
  bps = strategy_configs.cost_bps -> markets[asset_registry.market]
        (fallback silver.unified_prices market), else -> default, else 0.
  CASH rows: 0.

  entry_cost = entry_price * n_shares * bps / 1e4
  exit_cost  = exit_price  * n_shares * bps / 1e4   (closed rows only)
  pnl        = (exit_price - entry_price) * n_shares - entry_cost - exit_cost
  pnl_pct    = pnl / (entry_price * n_shares) * 100

Idempotent: pre-state snapshot table is created once (IF NOT EXISTS); UPDATEs
fire only where values differ (IS DISTINCT FROM).

Usage: backfill_paper_trade_costs.py [--dry-run]
"""
import os
import sys
from datetime import datetime

ETL_HOME = os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
)
sys.path.insert(0, os.path.join(ETL_HOME, "shared", "scripts"))
from db import get_connection  # noqa: E402

SNAP = "gold.paper_trades_synthetic__cost_bak_20261028"

MKT_CTE = """
WITH mkt AS (
  SELECT DISTINCT ON (ticker) ticker, market
  FROM (
    SELECT ticker, market, 0 AS prio FROM gold.asset_registry WHERE market IS NOT NULL
    UNION ALL
    SELECT ticker, market, 1 AS prio FROM silver.unified_prices WHERE market IS NOT NULL
  ) x ORDER BY ticker, prio
),
calc AS (
  SELECT p.id,
         CASE WHEN p.ticker = 'CASH' THEN 0
              ELSE COALESCE((
                SELECT COALESCE(
                         (sc.config_value->'markets'->>m.market)::numeric,
                         (sc.config_value->>'default')::numeric, 0)
                FROM gold.strategy_configs sc
                WHERE sc.strategy_id = p.strategy_id
                  AND sc.config_key = 'cost_bps'), 0)
         END AS bps
  FROM gold.paper_trades_synthetic p
  LEFT JOIN mkt m ON m.ticker = p.ticker
)
"""

SQL_SNAPSHOT = f"""
CREATE TABLE IF NOT EXISTS {SNAP} AS SELECT * FROM gold.paper_trades_synthetic;
"""

SQL_UPDATE_CLOSED = MKT_CTE + """
UPDATE gold.paper_trades_synthetic p
SET entry_cost       = ROUND(p.entry_price * p.n_shares * c.bps / 10000.0, 6),
    exit_cost        = ROUND(p.exit_price  * p.n_shares * c.bps / 10000.0, 6),
    cost_bps_applied = c.bps,
    pnl = (p.exit_price - p.entry_price) * p.n_shares
          - ROUND(p.entry_price * p.n_shares * c.bps / 10000.0, 6)
          - ROUND(p.exit_price  * p.n_shares * c.bps / 10000.0, 6),
    pnl_pct = CASE WHEN p.entry_price = 0 OR p.entry_price IS NULL THEN 0
              ELSE (((p.exit_price - p.entry_price) * p.n_shares
                     - ROUND(p.entry_price * p.n_shares * c.bps / 10000.0, 6)
                     - ROUND(p.exit_price  * p.n_shares * c.bps / 10000.0, 6))
                    / (p.entry_price * p.n_shares)) * 100 END
FROM calc c
WHERE p.id = c.id
  AND p.status = 'closed'
  AND (p.entry_cost IS DISTINCT FROM ROUND(p.entry_price * p.n_shares * c.bps / 10000.0, 6)
       OR p.exit_cost IS DISTINCT FROM ROUND(p.exit_price * p.n_shares * c.bps / 10000.0, 6)
       OR p.cost_bps_applied IS DISTINCT FROM c.bps);
"""

SQL_UPDATE_OPEN = MKT_CTE + """
UPDATE gold.paper_trades_synthetic p
SET entry_cost       = ROUND(p.entry_price * p.n_shares * c.bps / 10000.0, 6),
    cost_bps_applied = c.bps
FROM calc c
WHERE p.id = c.id
  AND p.status = 'open'
  AND (p.entry_cost IS DISTINCT FROM ROUND(p.entry_price * p.n_shares * c.bps / 10000.0, 6)
       OR p.cost_bps_applied IS DISTINCT FROM c.bps);
"""

SQL_VERIFY = f"""
SELECT p.strategy_id,
       COUNT(*) FILTER (WHERE p.status = 'closed') AS closed,
       COUNT(*) FILTER (WHERE p.status = 'open') AS open_rows,
       SUM(b.pnl) FILTER (WHERE b.status = 'closed') AS gross_pnl_before,
       SUM(p.pnl) FILTER (WHERE p.status = 'closed') AS net_pnl_after,
       SUM(p.entry_cost) FILTER (WHERE p.status = 'closed') AS entry_costs,
       SUM(p.exit_cost)  FILTER (WHERE p.status = 'closed') AS exit_costs
FROM gold.paper_trades_synthetic p
JOIN {SNAP} b ON b.id = p.id
GROUP BY p.strategy_id
ORDER BY p.strategy_id;
"""


def main():
    dry_run = "--dry-run" in sys.argv
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    print(f"[{datetime.utcnow().isoformat()}Z] backfill_paper_trade_costs "
          f"({'DRY-RUN' if dry_run else 'APPLY'})")

    cur.execute(SQL_SNAPSHOT)
    cur.execute(f"SELECT COUNT(*) FROM {SNAP}")
    print(f"snapshot {SNAP}: {cur.fetchone()[0]} rows")

    cur.execute(SQL_UPDATE_CLOSED)
    closed_updated = cur.rowcount
    print(f"closed rows restated: {closed_updated}")

    cur.execute(SQL_UPDATE_OPEN)
    open_updated = cur.rowcount
    print(f"open rows cost-stamped: {open_updated}")

    cur.execute(SQL_VERIFY)
    rows = cur.fetchall()
    print(f"\n{'strategy':44s} {'closed':>6s} {'open':>5s} {'gross_before':>14s} "
          f"{'net_after':>14s} {'entry_cost':>11s} {'exit_cost':>11s}")
    for r in rows:
        sid, closed, opn, gross, net, ec, xc = r
        print(f"{sid:44s} {closed:>6} {opn:>5} "
              f"{float(gross or 0):>14.2f} {float(net or 0):>14.2f} "
              f"{float(ec or 0):>11.2f} {float(xc or 0):>11.2f}")

    # identity check: net == gross - costs
    cur.execute(f"""
        SELECT COUNT(*) FROM gold.paper_trades_synthetic p
        WHERE p.status = 'closed'
          AND ABS(p.pnl - ((p.exit_price - p.entry_price) * p.n_shares
                           - p.entry_cost - p.exit_cost)) > 0.01
    """)
    bad = cur.fetchone()[0]
    print(f"\nidentity violations (pnl != gross - costs, tol 0.01): {bad}")

    # prices untouched check vs snapshot
    cur.execute(f"""
        SELECT COUNT(*) FROM gold.paper_trades_synthetic p
        JOIN {SNAP} b ON b.id = p.id
        WHERE p.entry_price IS DISTINCT FROM b.entry_price
           OR p.exit_price  IS DISTINCT FROM b.exit_price
           OR p.n_shares    IS DISTINCT FROM b.n_shares
    """)
    touched = cur.fetchone()[0]
    print(f"entry/exit price or share rewrites vs snapshot: {touched} (must be 0)")

    if dry_run:
        conn.rollback()
        print("DRY-RUN: rolled back")
    else:
        if bad or touched:
            conn.rollback()
            print("REFUSING COMMIT: identity or price-integrity check failed")
            sys.exit(1)
        conn.commit()
        print("COMMITTED")


if __name__ == "__main__":
    main()
