# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Equity: Stock Metrics (Current Snapshot)
Reads from: silver.unified_prices, silver.technical_indicators, silver.asset_registry
Writes to:  gold.stock_metrics

Latest daily metrics for all equities (current snapshot only).
One row per ticker with most recent data.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
WITH latest_prices AS (
  SELECT DISTINCT ON (ticker)
    ticker,
    date,
    open, high, low, close, volume,
    returns_1d
  FROM silver.unified_prices
  WHERE date >= CURRENT_DATE - INTERVAL '14 days'
  ORDER BY ticker, date DESC
),
latest_ti AS (
  SELECT DISTINCT ON (ticker)
    ticker,
    rsi_14,
    macd_histogram AS macd_hist,
    sma_50, sma_200,
    atr_14,
    volatility_20d,
    volume_sma_20, volume_ratio
  FROM silver.technical_indicators
  WHERE date >= CURRENT_DATE - INTERVAL '7 days'
  ORDER BY ticker, date DESC
),
prev_sma AS (
  -- Get previous day's SMAs for cross detection
  SELECT DISTINCT ON (ticker)
    ticker,
    sma_50 AS prev_sma_50,
    sma_200 AS prev_sma_200
  FROM silver.technical_indicators
  WHERE date >= CURRENT_DATE - INTERVAL '10 days' 
    AND date < CURRENT_DATE - INTERVAL '1 day'
  ORDER BY ticker, date DESC
),
prices_252d AS (
  SELECT 
    ticker,
    MAX(close) AS high_52w,
    STDDEV(returns_1d) * SQRT(252) AS volatility_annual
  FROM silver.unified_prices
  WHERE date >= CURRENT_DATE - INTERVAL '252 days'
  GROUP BY ticker
)
INSERT INTO gold.stock_metrics_history
  (date, ticker, sector,
   open, high, low, close, volume, vwap,
   rsi_14, macd_hist, sma_50, sma_200,
   atr_14, beta, sharpe_ratio,
   rel_strength_sp500, rel_strength_sector,
   dist_from_52w_high, implied_volatility,
   golden_cross, death_cross, above_sma_200,
   created_at)

SELECT 
  lp.date,
  lp.ticker,
  ar.sector,
  lp.open, lp.high, lp.low, lp.close, lp.volume,
  NULL AS vwap,
  ti.rsi_14,
  ti.macd_hist,
  ti.sma_50, ti.sma_200,
  ti.atr_14,
  NULL AS beta,
  NULL AS sharpe_ratio,
  NULL AS rel_strength_sp500,
  NULL AS rel_strength_sector,
  (lp.close / NULLIF(p252.high_52w, 0) - 1) * 100 AS dist_from_52w_high,
  p252.volatility_annual AS implied_volatility,
  -- Compute golden/death cross from current vs previous SMA
  (ti.sma_50 > ti.sma_200 AND ps.prev_sma_50 <= ps.prev_sma_200) AS golden_cross,
  (ti.sma_50 < ti.sma_200 AND ps.prev_sma_50 >= ps.prev_sma_200) AS death_cross,
  lp.close > ti.sma_200 AS above_sma_200,
  NOW()

FROM latest_prices lp
JOIN silver.asset_registry ar ON ar.ticker = lp.ticker AND ar.asset_class = 'STOCK'
LEFT JOIN latest_ti ti ON ti.ticker = lp.ticker
LEFT JOIN prev_sma ps ON ps.ticker = lp.ticker
LEFT JOIN prices_252d p252 ON p252.ticker = lp.ticker

ON CONFLICT (ticker, date) DO UPDATE SET
  date             = EXCLUDED.date,
  sector           = EXCLUDED.sector,
  open             = EXCLUDED.open,
  high             = EXCLUDED.high,
  low              = EXCLUDED.low,
  close            = EXCLUDED.close,
  volume           = EXCLUDED.volume,
  rsi_14           = EXCLUDED.rsi_14,
  macd_hist        = EXCLUDED.macd_hist,
  sma_50           = EXCLUDED.sma_50,
  sma_200          = EXCLUDED.sma_200,
  atr_14           = EXCLUDED.atr_14,
  dist_from_52w_high = EXCLUDED.dist_from_52w_high,
  implied_volatility = EXCLUDED.implied_volatility,
  golden_cross     = EXCLUDED.golden_cross,
  death_cross      = EXCLUDED.death_cross,
  above_sma_200    = EXCLUDED.above_sma_200,
  created_at       = EXCLUDED.created_at;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    
    # Ensure unique constraint exists for ON CONFLICT
    cur.execute("""
        DO $$ 
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'stock_metrics_ticker_key' 
                AND conrelid = 'gold.stock_metrics'::regclass
            ) AND (
                SELECT relkind FROM pg_class WHERE oid = 'gold.stock_metrics'::regclass
            ) = 'r' THEN
                ALTER TABLE gold.stock_metrics ADD CONSTRAINT stock_metrics_ticker_key UNIQUE (ticker);
            END IF;
        END $$;
    """)
    conn.commit()
    
    # Get count before
    before = 0  # stock_metrics is a view, no direct count
    
    # Execute upsert
    cur.execute(SQL)
    upserted = cur.rowcount
    
    conn.commit()
    
    # Get count after
    cur.execute("SELECT COUNT(*), MAX(date) FROM gold.stock_metrics_history;")
    after, max_date = cur.fetchone()
    
    # Get ticker coverage
    cur.execute("""
        SELECT COUNT(DISTINCT ticker) 
        FROM gold.stock_metrics_history 
        WHERE date >= CURRENT_DATE - INTERVAL '2 days';
    """)
    current_tickers = cur.fetchone()[0]
    
    conn.close()
    
    print(f"✅ gold.stock_metrics updated:")
    print(f"   Rows before: {before}")
    print(f"   Rows upserted: {upserted}")
    print(f"   Rows after: {after}")
    print(f"   Max date: {max_date}")
    print(f"   Current tickers (last 2 days): {current_tickers}")

if __name__ == "__main__":
    run()
