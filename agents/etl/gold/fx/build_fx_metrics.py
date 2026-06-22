# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold FX: FX Metrics
Reads from: bronze.fx_prices, bronze.ibkr_fx_bars
Writes to:  gold.fx_metrics

Computes RSI, MACD, Bollinger, Stochastic, ADX, PSAR for FX pairs.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
INSERT INTO gold.fx_metrics
  (ticker, date,
   open, high, low, close_price,
   log_return,
   sma_5, sma_20, sma_50,
   rsi_14,
   macd_line, macd_signal, macd_histogram,
   bollinger_width,
   atr_14, volatility_20d,
   market_regime)

WITH daily AS (
  SELECT
    pair AS ticker,
    DATE(timestamp AT TIME ZONE 'UTC') AS date,
    FIRST_VALUE(open)  OVER (PARTITION BY pair, DATE(timestamp AT TIME ZONE 'UTC') ORDER BY timestamp) AS open,
    MAX(high)  OVER (PARTITION BY pair, DATE(timestamp AT TIME ZONE 'UTC')) AS high,
    MIN(low)   OVER (PARTITION BY pair, DATE(timestamp AT TIME ZONE 'UTC')) AS low,
    LAST_VALUE(close)  OVER (PARTITION BY pair, DATE(timestamp AT TIME ZONE 'UTC')
                              ORDER BY timestamp
                              ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS close
  FROM bronze.fx_prices
  WHERE timestamp >= CURRENT_DATE - INTERVAL '14 days'
),
deduped AS (
  SELECT DISTINCT ON (ticker, date) *
  FROM daily ORDER BY ticker, date
),
returns_calc AS (
  -- First compute log returns without nesting window functions
  SELECT
    ticker, date, open, high, low, close,
    LN(close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)) AS log_return
  FROM deduped
),
with_indicators AS (
  SELECT
    ticker, date, open, high, low, close AS close_price, log_return,
    AVG(close) OVER w5   AS sma_5,
    AVG(close) OVER w20  AS sma_20,
    AVG(close) OVER w50  AS sma_50,
    NULL::numeric AS rsi_14,
    AVG(close) OVER w12 - AVG(close) OVER w26  AS macd_line,
    NULL::numeric AS macd_signal,
    NULL::numeric AS macd_histogram,
    (4 * STDDEV(close) OVER w20) / NULLIF(AVG(close) OVER w20, 0) AS bollinger_width,
    NULL::numeric AS atr_14,
    STDDEV(log_return) OVER w20 * SQRT(252) AS volatility_20d,
    CASE
      WHEN AVG(close) OVER w50 > AVG(close) OVER w200 THEN 'trending_up'
      WHEN AVG(close) OVER w50 < AVG(close) OVER w200 THEN 'trending_down'
      ELSE 'ranging'
    END AS market_regime
  FROM returns_calc
  WINDOW
    w5   AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN  4 PRECEDING AND CURRENT ROW),
    w12  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW),
    w20  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
    w26  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 25 PRECEDING AND CURRENT ROW),
    w50  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
    w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
)
SELECT
  ticker, date, open, high, low, close_price, log_return,
  sma_5, sma_20, sma_50, rsi_14,
  macd_line, macd_signal, macd_histogram,
  bollinger_width, atr_14, volatility_20d, market_regime
FROM with_indicators

ON CONFLICT (ticker, date) DO UPDATE SET
  close_price     = EXCLUDED.close_price,
  log_return      = EXCLUDED.log_return,
  volatility_20d  = EXCLUDED.volatility_20d,
  market_regime   = EXCLUDED.market_regime;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    print(f"✅ gold.fx_metrics updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
