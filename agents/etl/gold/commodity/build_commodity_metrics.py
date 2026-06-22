# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Commodity: Commodity Metrics & Seasonality
Reads from: bronze.yf_commodity_futures
Writes to:  gold.commodity_futures, gold.commodity_metrics,
            gold.commodity_seasonality, gold.seasonality_patterns
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_FUTURES = """
INSERT INTO gold.commodity_futures
  (ticker, name, category, exchange, date,
   open_price, high_price, low_price, close_price, volume,
   returns, log_returns, volatility_20d,
   sma_50, sma_200, month, quarter, year, day_of_year,
   collected_at)
WITH returns_calc AS (
  -- First compute returns without nesting window functions
  SELECT
    ticker, name, category, exchange, date, open, high, low, close, volume,
    (close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0) - 1) AS returns,
    LN(GREATEST(close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0), 1e-10)) AS log_returns
  FROM bronze.yf_commodity_futures
),
with_indicators AS (
  SELECT
    ticker, name, category, exchange, date,
    open AS open_price, high AS high_price, low AS low_price, close AS close_price, volume,
    returns, log_returns,
    STDDEV(log_returns) OVER w20 * SQRT(252) AS volatility_20d,
    AVG(close) OVER w50  AS sma_50,
    AVG(close) OVER w200 AS sma_200,
    EXTRACT(MONTH  FROM date)::int AS month,
    EXTRACT(QUARTER FROM date)::int AS quarter,
    EXTRACT(YEAR   FROM date)::int AS year,
    EXTRACT(DOY    FROM date)::int AS day_of_year,
    NOW() AS collected_at
  FROM returns_calc
  WINDOW
    w20  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
    w50  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
    w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
)
SELECT * FROM with_indicators
ON CONFLICT (ticker, date) DO UPDATE SET
  close_price    = EXCLUDED.close_price,
  returns        = EXCLUDED.returns,
  log_returns    = EXCLUDED.log_returns,
  volatility_20d = EXCLUDED.volatility_20d,
  collected_at   = NOW();
"""

SQL_SEASONALITY = """
INSERT INTO gold.commodity_seasonality
  (ticker, name, category, month, avg_return, std_return, obs_count, seasonal_bias, calculated_at)
SELECT
  ticker,
  MAX(name),
  MAX(category),
  month,
  AVG(returns)    AS avg_return,
  STDDEV(returns) AS std_return,
  COUNT(*)        AS obs_count,
  CASE
    WHEN AVG(returns) > 0.005  THEN 'bullish'
    WHEN AVG(returns) < -0.005 THEN 'bearish'
    ELSE 'neutral'
  END AS seasonal_bias,
  NOW()
FROM gold.commodity_futures
WHERE returns IS NOT NULL
GROUP BY ticker, month
ON CONFLICT (ticker, month) DO UPDATE SET
  avg_return    = EXCLUDED.avg_return,
  std_return    = EXCLUDED.std_return,
  obs_count     = EXCLUDED.obs_count,
  seasonal_bias = EXCLUDED.seasonal_bias,
  calculated_at = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_FUTURES)
    print(f"✅ gold.commodity_futures updated: {cur.rowcount} rows upserted")
    cur.execute(SQL_SEASONALITY)
    print(f"✅ gold.commodity_seasonality updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
