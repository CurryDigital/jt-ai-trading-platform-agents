#!/usr/bin/env python3
"""
Gold Crypto: Crypto KPIs
Reads from: bronze.binance_crypto_ohlcv, bronze.binance_funding_rates,
            bronze.coinbase_crypto_ohlcv
Writes to:  gold.crypto_kpis, gold.crypto_metrics
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_KPIS = """
INSERT INTO gold.crypto_kpis
  (ticker, date,
   open, high, low, close, volume,
   body_size, upper_shadow, lower_shadow, candle_type,
   atr_14, volatility_20d, volatility_7d, daily_range_pct,
   sma_5, sma_20, sma_50, trend_direction, price_vs_sma20_pct,
   rsi_14, macd_line, macd_signal,
   bb_upper, bb_lower, bb_position,
   volume_sma_20, volume_ratio,
   cond_high_volume, cond_rsi_below_30, cond_rsi_above_70,
   cond_above_bb, cond_below_bb,
   crypto_breakout_trigger, crypto_oversold_bounce_trigger, crypto_volume_spike_trigger,
   updated_at)

WITH src AS (
  SELECT
    ticker,
    DATE(timestamp) AS date,
    MAX(CASE WHEN interval = '1d' THEN open  END) AS open,
    MAX(CASE WHEN interval = '1d' THEN high  END) AS high,
    MIN(CASE WHEN interval = '1d' THEN low   END) AS low,
    MAX(CASE WHEN interval = '1d' THEN close END) AS close,
    SUM(CASE WHEN interval = '1d' THEN volume END) AS volume
  FROM bronze.binance_crypto_ohlcv
  WHERE interval = '1d'
  GROUP BY ticker, DATE(timestamp)
),
indicators AS (
  SELECT
    ticker, date, open, high, low, close, volume,
    ABS(close - open)                   AS body_size,
    high - GREATEST(open, close)        AS upper_shadow,
    LEAST(open, close) - low            AS lower_shadow,
    CASE WHEN close >= open THEN 'bullish' ELSE 'bearish' END AS candle_type,
    NULL::numeric AS atr_14,
    STDDEV(LN(close / NULLIF(LAG(close) OVER w, 0))) OVER w20 * SQRT(252) AS volatility_20d,
    STDDEV(LN(close / NULLIF(LAG(close) OVER w, 0))) OVER w7  * SQRT(365) AS volatility_7d,
    (high - low) / NULLIF(close, 0) * 100 AS daily_range_pct,
    AVG(close) OVER w5  AS sma_5,
    AVG(close) OVER w20 AS sma_20,
    AVG(close) OVER w50 AS sma_50,
    CASE
      WHEN close > AVG(close) OVER w20 THEN 'up'
      ELSE 'down'
    END AS trend_direction,
    (close / NULLIF(AVG(close) OVER w20, 0) - 1) * 100 AS price_vs_sma20_pct,
    NULL::numeric AS rsi_14,
    AVG(close) OVER w12 - AVG(close) OVER w26 AS macd_line,
    NULL::numeric AS macd_signal,
    AVG(close) OVER w20 + 2 * STDDEV(close) OVER w20 AS bb_upper,
    AVG(close) OVER w20 - 2 * STDDEV(close) OVER w20 AS bb_lower,
    (close - (AVG(close) OVER w20 - 2 * STDDEV(close) OVER w20))
      / NULLIF(4 * STDDEV(close) OVER w20, 0) AS bb_position,
    AVG(volume) OVER w20 AS volume_sma_20,
    volume::numeric / NULLIF(AVG(volume) OVER w20, 0) AS volume_ratio
  FROM src
  WINDOW
    w   AS (PARTITION BY ticker ORDER BY date),
    w5  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN  4 PRECEDING AND CURRENT ROW),
    w7  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN  6 PRECEDING AND CURRENT ROW),
    w12 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW),
    w20 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
    w26 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 25 PRECEDING AND CURRENT ROW),
    w50 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW)
)
SELECT
  ticker, date, open, high, low, close, volume,
  body_size, upper_shadow, lower_shadow, candle_type,
  atr_14, volatility_20d, volatility_7d, daily_range_pct,
  sma_5, sma_20, sma_50, trend_direction, price_vs_sma20_pct,
  rsi_14, macd_line, macd_signal,
  bb_upper, bb_lower, bb_position,
  volume_sma_20, volume_ratio,
  -- Conditions
  volume_ratio > 1.5 AS cond_high_volume,
  rsi_14 < 30        AS cond_rsi_below_30,
  rsi_14 > 70        AS cond_rsi_above_70,
  close > bb_upper   AS cond_above_bb,
  close < bb_lower   AS cond_below_bb,
  -- Trigger signals
  (close > bb_upper AND volume_ratio > 2.0) AS crypto_breakout_trigger,
  (rsi_14 < 30 AND close < bb_lower)        AS crypto_oversold_bounce_trigger,
  (volume_ratio > 3.0)                       AS crypto_volume_spike_trigger,
  NOW()
FROM indicators

ON CONFLICT (ticker, date) DO UPDATE SET
  close            = EXCLUDED.close,
  volume           = EXCLUDED.volume,
  volatility_20d   = EXCLUDED.volatility_20d,
  crypto_breakout_trigger        = EXCLUDED.crypto_breakout_trigger,
  crypto_oversold_bounce_trigger = EXCLUDED.crypto_oversold_bounce_trigger,
  updated_at       = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_KPIS)
    print(f"✅ gold.crypto_kpis updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
