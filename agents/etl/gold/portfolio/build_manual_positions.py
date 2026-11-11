#!/usr/bin/env python3
"""
Gold Portfolio: Manual Positions Fold-In
Reads from: gold.manual_orders
Writes to:  consumption.portfolio_positions_current (source='manual')
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_UPSERT_MANUAL = """
-- 2026-09-12 (t_bb898628): conflict key is (strategy_id, ticker) but the old
-- GROUP BY (ticker, side, DATE(created_at), entry_price) emitted one row per
-- fill — a second filled order for the same ticker (e.g. GLD buy+sell from the
-- paper_uat reconciler) produced duplicate constrained values and a
-- CardinalityViolation. Now net to ONE row per ticker: BUY qty positive,
-- SELL qty negative; flat (net 0) tickers are closed and skipped.
INSERT INTO consumption.portfolio_positions_current (
    strategy_id, ticker, side, entry_date, entry_price, current_price,
    quantity, market_value, weight_pct, unrealized_pnl, realized_pnl,
    status, source, execution_mode, updated_at, created_at
)
WITH netted AS (
    SELECT
        ticker,
        SUM(CASE WHEN side = 'SELL' THEN -qty ELSE qty END) AS net_qty,
        COALESCE(
            SUM(CASE WHEN side <> 'SELL' THEN qty * COALESCE(entry_price, 0) END)
            / NULLIF(SUM(CASE WHEN side <> 'SELL' THEN qty END), 0),
            AVG(COALESCE(entry_price, 0)),
            0
        ) AS wavg_entry,
        MIN(DATE(created_at)) AS entry_date,
        MIN(created_at) AS created_at
    FROM gold.manual_orders
    WHERE status IN ('accepted', 'open', 'filled')
      -- t_53888693 (2026-11-10): paper_uat reconciler fills logged to
      -- gold.manual_orders are NOT live manual positions; folding them in
      -- double-counted the UAT mirror against the real broker book.
      AND book IS DISTINCT FROM 'paper_uat'
    GROUP BY ticker
    HAVING SUM(CASE WHEN side = 'SELL' THEN -qty ELSE qty END) <> 0
)
SELECT
    'MANUAL' AS strategy_id,
    ticker,
    CASE WHEN net_qty < 0 THEN 'SHORT' ELSE 'LONG' END AS side,
    entry_date,
    wavg_entry AS entry_price,
    wavg_entry AS current_price,
    ABS(net_qty) AS quantity,
    ABS(net_qty) * wavg_entry AS market_value,
    100.0 AS weight_pct,
    0 AS unrealized_pnl,
    0 AS realized_pnl,
    'OPEN' AS status,
    'manual' AS source,
    'MANUAL' AS execution_mode,
    NOW() AS updated_at,
    created_at
FROM netted
ON CONFLICT (strategy_id, ticker)
DO UPDATE SET
    strategy_id    = EXCLUDED.strategy_id,
    side           = EXCLUDED.side,
    entry_price    = EXCLUDED.entry_price,
    current_price  = EXCLUDED.current_price,
    quantity       = EXCLUDED.quantity,
    market_value   = EXCLUDED.market_value,
    weight_pct     = EXCLUDED.weight_pct,
    unrealized_pnl = EXCLUDED.unrealized_pnl,
    realized_pnl   = EXCLUDED.realized_pnl,
    status         = EXCLUDED.status,
    source         = EXCLUDED.source,
    execution_mode = EXCLUDED.execution_mode,
    updated_at     = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'gold' AND table_name = 'manual_orders'
        );
    """)
    if not cur.fetchone()[0]:
        print("⚠️  gold.manual_orders does not exist — skipping manual positions fold-in")
        conn.close()
        return

    cur.execute(SQL_UPSERT_MANUAL)
    rows = cur.rowcount
    conn.commit()
    conn.close()
    print(f"✅ consumption.portfolio_positions_current manual fold-in: {rows} rows")

if __name__ == "__main__":
    run()
