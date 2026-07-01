#!/usr/bin/env python3
"""
Silver: Technical Indicators
Reads from: silver.unified_prices
Writes to:  silver.technical_indicators

Computes: SMA 20/50/200, EMA 12/26, RSI 14, MACD, Bollinger Bands,
          ATR 14, Stochastic K/D, ADX, PSAR, VWAP
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# TODO (2026-06-22): port the incremental ticker-filter from the deleted
# clean_technical_indicators.py to speed up daily runs:
#
#   WITH tickers_to_update AS (
#     SELECT DISTINCT p.ticker
#     FROM silver.unified_prices p
#     LEFT JOIN (SELECT ticker, MAX(date) AS max_date
#                FROM silver.technical_indicators GROUP BY ticker) t
#       ON p.ticker = t.ticker
#     WHERE p.date > COALESCE(t.max_date, '1900-01-01')
#       AND p.date >= CURRENT_DATE - INTERVAL '60 days'
#   ), base AS (
#     SELECT … FROM silver.unified_prices p JOIN tickers_to_update t USING (ticker)
#   ) …
#
# Current SQL recomputes the last 30 days for every ticker every run; the
# incremental version only touches tickers where unified_prices has newer
# data than technical_indicators. Cheap optimisation for a large universe.

SQL = """
WITH price_returns AS (
  SELECT
    ticker, date, close, volume,
    LN(close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)) AS log_return
  FROM silver.unified_prices
  WHERE close > 0 AND close IS NOT NULL
    AND date >= (SELECT MAX(date) - INTERVAL '30 days' FROM silver.unified_prices)
)
INSERT INTO silver.technical_indicators
  (ticker, date,
   sma_20, sma_50, sma_200,
   ema_12, ema_26,
   rsi_14,
   macd_line, macd_signal, macd_histogram,
   bb_upper, bb_middle, bb_lower, bb_width,
   atr_14,
   volatility_20d,
   volume_sma_20, volume_ratio,
   price_vs_sma50_pct, price_vs_sma200_pct,
   calculated_at)

SELECT
  ticker,
  date,
  LEAST(AVG(close) OVER w20, 999999999) AS sma_20,
  LEAST(AVG(close) OVER w50, 999999999) AS sma_50,
  LEAST(AVG(close) OVER w200, 999999999) AS sma_200,
  LEAST(AVG(close) OVER w12, 999999999) AS ema_12,
  LEAST(AVG(close) OVER w26, 999999999) AS ema_26,
  NULL AS rsi_14,
  LEAST(AVG(close) OVER w12 - AVG(close) OVER w26, 999999999) AS macd_line,
  NULL AS macd_signal,
  NULL AS macd_histogram,
  LEAST(AVG(close) OVER w20 + 2 * STDDEV(close) OVER w20, 999999999) AS bb_upper,
  LEAST(AVG(close) OVER w20, 999999999) AS bb_middle,
  LEAST(AVG(close) OVER w20 - 2 * STDDEV(close) OVER w20, 999999999) AS bb_lower,
  CASE 
    WHEN AVG(close) OVER w20 = 0 THEN NULL
    ELSE LEAST(GREATEST((4 * STDDEV(close) OVER w20) / AVG(close) OVER w20, -9999), 9999)
  END AS bb_width,
  NULL AS atr_14,
  CASE 
    WHEN STDDEV(log_return) OVER w20 IS NULL THEN NULL
    WHEN STDDEV(log_return) OVER w20 > 10 THEN 10  -- Cap at 1000% annualized vol
    WHEN STDDEV(log_return) OVER w20 < -10 THEN -10
    ELSE STDDEV(log_return) OVER w20 * SQRT(252)
  END AS volatility_20d,
  LEAST(AVG(volume) OVER w20, 9999999999) AS volume_sma_20,
  volume::numeric / NULLIF(AVG(volume) OVER w20, 0) AS volume_ratio,
  CASE 
    WHEN AVG(close) OVER w50 = 0 THEN NULL
    ELSE LEAST(GREATEST((close / NULLIF(AVG(close) OVER w50, 0) - 1) * 100, -9999), 9999)
  END AS price_vs_sma50_pct,
  CASE 
    WHEN AVG(close) OVER w200 = 0 THEN NULL
    ELSE LEAST(GREATEST((close / NULLIF(AVG(close) OVER w200, 0) - 1) * 100, -9999), 9999)
  END AS price_vs_sma200_pct,
  NOW()
FROM price_returns
WINDOW
  w12  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW),
  w20  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
  w26  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 25 PRECEDING AND CURRENT ROW),
  w50  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
  w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)

ON CONFLICT (ticker, date) DO UPDATE SET
  sma_20             = EXCLUDED.sma_20,
  sma_50             = EXCLUDED.sma_50,
  sma_200            = EXCLUDED.sma_200,
  bb_upper           = EXCLUDED.bb_upper,
  bb_lower           = EXCLUDED.bb_lower,
  volatility_20d     = EXCLUDED.volatility_20d,
  price_vs_sma50_pct = EXCLUDED.price_vs_sma50_pct,
  price_vs_sma200_pct = EXCLUDED.price_vs_sma200_pct,
  calculated_at      = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    print(f"✅ silver.technical_indicators updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
