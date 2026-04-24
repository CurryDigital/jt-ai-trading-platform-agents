#!/usr/bin/env python3
"""
Silver: Unified Prices
Reads from: bronze.yf_prices, bronze.fmp_prices, bronze.manual_prices, bronze.fx_prices
Writes to:  silver.unified_prices

Rules:
  - Deduplicate by (ticker, date), prefer yf > fmp > manual
  - Compute returns_1d and returns_log
  - Tag asset_class and market from silver.asset_registry
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
INSERT INTO silver.unified_prices
  (ticker, asset_class, market, date, open, high, low, close, volume, adjusted_close,
   returns_1d, returns_log, primary_source, updated_at)

WITH ranked AS (
  -- yfinance (priority 1)
  SELECT
    p.ticker,
    ar.asset_class,
    ar.market,
    p.date,
    p.open, p.high, p.low, p.close, p.volume, p.adjusted_close,
    'yfinance' AS source,
    1 AS priority
  FROM bronze.yf_prices p
  LEFT JOIN silver.asset_registry ar ON ar.ticker = p.ticker

  UNION ALL

  -- FMP (priority 2)
  SELECT
    p.ticker,
    ar.asset_class,
    ar.market,
    p.date,
    p.open, p.high, p.low, p.close, p.volume, p.adjusted_close,
    'fmp' AS source,
    2 AS priority
  FROM bronze.fmp_prices p
  LEFT JOIN silver.asset_registry ar ON ar.ticker = p.ticker

  UNION ALL

  -- Manual (priority 3)
  SELECT
    p.ticker,
    ar.asset_class,
    ar.market,
    p.date,
    p.open, p.high, p.low, p.close, p.volume, p.adjusted_close,
    'manual' AS source,
    3 AS priority
  FROM bronze.manual_prices p
  LEFT JOIN silver.asset_registry ar ON ar.ticker = p.ticker
),
best AS (
  SELECT DISTINCT ON (ticker, date) *
  FROM ranked
  ORDER BY ticker, date, priority ASC
),
with_returns AS (
  SELECT
    ticker, asset_class, market, date, open, high, low, close, volume, adjusted_close, source,
    (close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)) - 1 AS returns_1d,
    LN(close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0))   AS returns_log
  FROM best
)
SELECT
  ticker, asset_class, market, date, open, high, low, close, volume, adjusted_close,
  returns_1d, returns_log, source, NOW()
FROM with_returns

ON CONFLICT (ticker, date) DO UPDATE SET
  close         = EXCLUDED.close,
  returns_1d    = EXCLUDED.returns_1d,
  returns_log   = EXCLUDED.returns_log,
  primary_source = EXCLUDED.primary_source,
  updated_at    = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    print(f"✅ silver.unified_prices updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
