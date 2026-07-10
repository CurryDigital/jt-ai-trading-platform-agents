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
INSERT INTO consumption.portfolio_positions_current (
    strategy_id, ticker, side, entry_date, entry_price, current_price,
    quantity, market_value, weight_pct, unrealized_pnl, realized_pnl,
    status, source, execution_mode, updated_at, created_at
)
SELECT
    'MANUAL' AS strategy_id,
    ticker,
    COALESCE(side, 'LONG') AS side,
    DATE(created_at) AS entry_date,
    COALESCE(entry_price, 0) AS entry_price,
    COALESCE(entry_price, 0) AS current_price,
    SUM(qty) AS quantity,
    SUM(qty * COALESCE(entry_price, 0)) AS market_value,
    100.0 AS weight_pct,
    0 AS unrealized_pnl,
    0 AS realized_pnl,
    'OPEN' AS status,
    'manual' AS source,
    'MANUAL' AS execution_mode,
    NOW() AS updated_at,
    MIN(created_at) AS created_at
FROM gold.manual_orders
WHERE status IN ('accepted', 'open', 'filled')
GROUP BY ticker, side, DATE(created_at), entry_price
ON CONFLICT ON CONSTRAINT portfolio_positions_current_ticker_key
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
