#!/usr/bin/env python3
"""
Gold Market: Market Indices & Sentiment
Reads from: silver.market_indices, silver.unified_prices
Writes to:  gold.index_metrics, gold.market_sentiment_daily, gold.market_regimes
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_INDEX = """
INSERT INTO gold.index_metrics
  (ticker, date, name, market, region, currency,
   open, high, low, close, volume,
   change_pct, change_amount, ytd_change,
   ma_50, ma_200, above_ma_50, above_ma_200, golden_cross, rsi_14,
   macd_line, macd_signal, macd_hist,
   atr_14, _52_week_high, _52_week_low, _52_week_range_pct,
   returns_1d, returns_5d, returns_21d, returns_63d, returns_252d,
   volatility_21d, is_volatility_index, created_at)

SELECT
  m.ticker, m.date, m.name, m.market, m.region, m.currency,
  m.open, m.high, m.low, m.close, m.volume,
  m.change_pct, m.change_amount, m.ytd_change,
  m.ma_50, m.ma_200,
  m.close > m.ma_50  AS above_ma_50,
  m.close > m.ma_200 AS above_ma_200,
  (m.ma_50 > m.ma_200 AND LAG(m.ma_50) OVER w <= LAG(m.ma_200) OVER w) AS golden_cross,
  m.rsi_14,
  NULL AS macd_line,
  NULL AS macd_signal,
  NULL AS macd_hist,
  NULL AS atr_14,
  MAX(m.close) OVER (PARTITION BY m.ticker ORDER BY m.date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS _52_week_high,
  MIN(m.close) OVER (PARTITION BY m.ticker ORDER BY m.date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS _52_week_low,
  (m.close - MIN(m.close) OVER (PARTITION BY m.ticker ORDER BY m.date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW))
    / NULLIF(MAX(m.close) OVER (PARTITION BY m.ticker ORDER BY m.date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
           - MIN(m.close) OVER (PARTITION BY m.ticker ORDER BY m.date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW), 0) AS _52_week_range_pct,
  m.change_pct / 100 AS returns_1d,
  (m.close / NULLIF(LAG(m.close, 5)   OVER w, 0) - 1) AS returns_5d,
  (m.close / NULLIF(LAG(m.close, 21)  OVER w, 0) - 1) AS returns_21d,
  (m.close / NULLIF(LAG(m.close, 63)  OVER w, 0) - 1) AS returns_63d,
  (m.close / NULLIF(LAG(m.close, 252) OVER w, 0) - 1) AS returns_252d,
  STDDEV(m.change_pct / 100) OVER (PARTITION BY m.ticker ORDER BY m.date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW)
    * SQRT(252) AS volatility_21d,
  m.is_volatility_index,
  NOW()

FROM silver.market_indices m
WINDOW w AS (PARTITION BY m.ticker ORDER BY m.date)

ON CONFLICT (ticker, date) DO UPDATE SET
  close         = EXCLUDED.close,
  change_pct    = EXCLUDED.change_pct,
  above_ma_50   = EXCLUDED.above_ma_50,
  above_ma_200  = EXCLUDED.above_ma_200,
  golden_cross  = EXCLUDED.golden_cross,
  created_at    = NOW();
"""

SQL_SENTIMENT = """
INSERT INTO gold.market_sentiment_daily
  (market, date, rating, score, bull_percentage, bear_percentage,
   index_change_score, breadth_score, technical_score, vix_score,
   index_change_pct, advancing_pct, above_ma50_pct, rsi_avg, vix_level, created_at)

WITH latest_us AS (
  SELECT date, close AS spx_close, change_pct AS spx_chg, rsi_14 AS spx_rsi
  FROM gold.index_metrics
  WHERE ticker = 'SPY' OR ticker = 'SPX'
  ORDER BY date DESC LIMIT 1
),
latest_vix AS (
  SELECT close AS vix_close
  FROM gold.index_metrics
  WHERE is_volatility_index = TRUE AND (ticker = 'VIX' OR ticker = '^VIX')
  ORDER BY date DESC LIMIT 1
)
SELECT
  'US' AS market,
  u.date,
  CASE
    WHEN u.spx_chg > 0.5  AND v.vix_close < 20 THEN 'Bullish'
    WHEN u.spx_chg < -0.5 OR  v.vix_close > 30 THEN 'Bearish'
    ELSE 'Neutral'
  END AS rating,
  ROUND(((u.spx_chg + 2) / 4 * 100)::numeric, 2) AS score,
  CASE WHEN u.spx_chg > 0 THEN 60 ELSE 40 END AS bull_percentage,
  CASE WHEN u.spx_chg < 0 THEN 60 ELSE 40 END AS bear_percentage,
  ROUND(((u.spx_chg + 2) / 4 * 100)::numeric, 2) AS index_change_score,
  NULL AS breadth_score,
  ROUND(((u.spx_rsi - 30) / 40 * 100)::numeric, 2) AS technical_score,
  ROUND(((30 - LEAST(v.vix_close, 50)) / 30 * 100)::numeric, 2) AS vix_score,
  u.spx_chg AS index_change_pct,
  NULL AS advancing_pct,
  NULL AS above_ma50_pct,
  u.spx_rsi AS rsi_avg,
  v.vix_close AS vix_level,
  NOW()
FROM latest_us u, latest_vix v
ON CONFLICT (market, date) DO UPDATE SET
  rating   = EXCLUDED.rating,
  score    = EXCLUDED.score,
  vix_level = EXCLUDED.vix_level;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_INDEX)
    print(f"✅ gold.index_metrics updated: {cur.rowcount} rows upserted")
    cur.execute(SQL_SENTIMENT)
    print(f"✅ gold.market_sentiment_daily updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
