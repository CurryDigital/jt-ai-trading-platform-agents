# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Portfolio: Live Positions & Portfolio Snapshots
Reads from: bronze.ibkr_positions_live, gold.paper_strategies,
            gold.strategy_ticker_scores
Writes to:  gold.ibkr_positions_live, gold.portfolio_snapshots,
            gold.trade_executions
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date

SQL_SYNC_POSITIONS = """
INSERT INTO gold.ibkr_positions_live
  (account, ticker, quantity, avg_cost, market_price, market_value,
   unrealized_pnl, unrealized_pnl_pct, side, asset_class, currency, fetched_at)
SELECT
  account,
  -- Normalise ticker (strip exchange suffix if present)
  SPLIT_PART(ticker, '.', 1) AS ticker,
  quantity,
  avg_cost,
  market_price,
  market_value,
  unrealized_pnl,
  unrealized_pnl_pct,
  CASE WHEN quantity > 0 THEN 'LONG' ELSE 'SHORT' END AS side,
  asset_class,
  currency,
  fetched_at
FROM bronze.ibkr_positions_live
ON CONFLICT (account, ticker) DO UPDATE SET
  quantity          = EXCLUDED.quantity,
  market_price      = EXCLUDED.market_price,
  market_value      = EXCLUDED.market_value,
  unrealized_pnl    = EXCLUDED.unrealized_pnl,
  unrealized_pnl_pct = EXCLUDED.unrealized_pnl_pct,
  fetched_at        = EXCLUDED.fetched_at;
"""

SQL_SNAPSHOT = """
INSERT INTO gold.portfolio_snapshots
  (snapshot_date, portfolio_type,
   total_value, cash_value, positions_value,
   daily_pnl, daily_pnl_pct,
   gross_exposure, net_exposure,
   calculated_at)
SELECT
  CURRENT_DATE,
  'live' AS portfolio_type,
  SUM(market_value) AS total_value,
  0 AS cash_value,
  SUM(market_value) AS positions_value,
  SUM(unrealized_pnl) AS daily_pnl,
  SUM(unrealized_pnl) / NULLIF(SUM(market_value), 0) * 100 AS daily_pnl_pct,
  SUM(ABS(market_value)) / NULLIF(SUM(market_value), 0) AS gross_exposure,
  SUM(CASE WHEN side = 'LONG' THEN market_value ELSE -market_value END)
    / NULLIF(SUM(market_value), 0) AS net_exposure,
  NOW()
FROM gold.ibkr_positions_live
ON CONFLICT (snapshot_date, portfolio_type) DO UPDATE SET
  total_value       = EXCLUDED.total_value,
  positions_value   = EXCLUDED.positions_value,
  daily_pnl         = EXCLUDED.daily_pnl,
  daily_pnl_pct     = EXCLUDED.daily_pnl_pct,
  calculated_at     = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    
    # Check if target table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'gold' AND table_name = 'ibkr_positions_live'
        );
    """)
    has_positions_table = cur.fetchone()[0]
    
    if has_positions_table:
        cur.execute(SQL_SYNC_POSITIONS)
        print(f"✅ gold.ibkr_positions_live synced: {cur.rowcount} rows upserted")
        cur.execute(SQL_SNAPSHOT)
        print(f"✅ gold.portfolio_snapshots updated: {cur.rowcount} rows upserted")
    else:
        print("⚠️  gold.ibkr_positions_live does not exist — skipping position sync")
    
    # Also sync account summary from bronze to gold
    cur.execute("""
        INSERT INTO gold.ibkr_account_summary
            (account, net_liquidation, cash_hkd, cash_usd, available_funds, buying_power, position_count, fetched_at)
        SELECT account, net_liquidation, cash_hkd, cash_usd, available_funds, buying_power, position_count, fetched_at
        FROM bronze.ibkr_account_summary
        ON CONFLICT (account) DO UPDATE SET
            net_liquidation = EXCLUDED.net_liquidation,
            cash_hkd = EXCLUDED.cash_hkd,
            cash_usd = EXCLUDED.cash_usd,
            available_funds = EXCLUDED.available_funds,
            buying_power = EXCLUDED.buying_power,
            position_count = EXCLUDED.position_count,
            fetched_at = EXCLUDED.fetched_at;
    """)
    print(f"✅ gold.ibkr_account_summary synced: {cur.rowcount} rows upserted")
    
    # Check if consumption table exists before writing
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'consumption' AND table_name = 'portfolio_positions_current'
        );
    """)
    has_cons_table = cur.fetchone()[0]
    
    if has_cons_table:
        # Also sync account summary from gold to consumption for frontend
        cur.execute("""
            INSERT INTO consumption.portfolio_positions_current
                (strategy_id, ticker, side, entry_date, entry_price, current_price,
                 quantity, market_value, weight_pct, unrealized_pnl, realized_pnl, status, updated_at)
            SELECT
                'LIVE_IBKR_CASH' AS strategy_id,
                'HKD' AS ticker,
                'LONG' AS side,
                CURRENT_DATE AS entry_date,
                cash_hkd AS entry_price,
                cash_hkd AS current_price,
                1 AS quantity,
                cash_hkd AS market_value,
                100.0 AS weight_pct,
                0 AS unrealized_pnl,
                0 AS realized_pnl,
                'ACTIVE' AS status,
                NOW() AS updated_at
            FROM gold.ibkr_account_summary
            WHERE cash_hkd IS NOT NULL
            ON CONFLICT DO NOTHING;
        """)
        print(f"✅ Cash position synced to consumption: {cur.rowcount} rows")
    else:
        print("⚠️  consumption.portfolio_positions_current does not exist — skipping consumption sync")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
