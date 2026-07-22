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
Writes to:  gold.ibkr_positions_live, gold.portfolio_snapshots
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
WITH latest_account AS (
    SELECT
        net_liquidation,
        COALESCE(cash_hkd, 0) + COALESCE(cash_usd, 0) AS cash_value
    FROM gold.ibkr_account_summary
    ORDER BY fetched_at DESC
    LIMIT 1
),
position_summary AS (
    SELECT
        COALESCE(SUM(market_value), 0) AS raw_positions_value,
        COALESCE(SUM(unrealized_pnl), 0) AS daily_pnl,
        COALESCE(SUM(ABS(market_value)), 0) AS gross_exposure,
        COALESCE(SUM(CASE WHEN side = 'SHORT' THEN -ABS(market_value) ELSE market_value END), 0) AS net_exposure
    FROM gold.ibkr_positions_live
)
INSERT INTO gold.portfolio_snapshots
  (snapshot_date, portfolio_type,
   total_value, cash_value, positions_value,
   daily_pnl, daily_pnl_pct,
   gross_exposure, net_exposure,
   calculated_at)
SELECT
  CURRENT_DATE,
  'live' AS portfolio_type,
  la.net_liquidation AS total_value,
  la.cash_value,
  COALESCE(la.net_liquidation, 0) - la.cash_value AS positions_value,
  ps.daily_pnl,
  ps.daily_pnl / NULLIF(la.net_liquidation - la.cash_value, 0) * 100 AS daily_pnl_pct,
  ps.gross_exposure,
  ps.net_exposure,
  NOW()
FROM position_summary ps, latest_account la
ON CONFLICT (snapshot_date, portfolio_type) DO UPDATE SET
  total_value       = EXCLUDED.total_value,
  cash_value        = EXCLUDED.cash_value,
  positions_value   = EXCLUDED.positions_value,
  daily_pnl         = EXCLUDED.daily_pnl,
  daily_pnl_pct     = EXCLUDED.daily_pnl_pct,
  gross_exposure    = EXCLUDED.gross_exposure,
  net_exposure      = EXCLUDED.net_exposure,
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
        # Previously this script inserted a synthetic HKD cash row into the
        # positions table.  Cash is now reported from gold.ibkr_account_summary
        # via the consumption.account_summary view, so we no longer pollute
        # the positions table with a cash pseudo-position.
        print("✅ Cash position is sourced from gold.ibkr_account_summary; no synthetic position row inserted")
    else:
        print("⚠️  consumption.portfolio_positions_current does not exist — skipping consumption sync")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
