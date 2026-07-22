#!/usr/bin/env python3
"""One-off full backfill of technical_indicators for strategy universe."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

CUTOFF_DATE = '2025-01-01'

UNIVERSE = [
    'AAPL','MSFT','AMZN','GOOGL','META','TSLA','NVDA','JPM','JNJ','V','UNH','XOM','WMT','PG','MA','HD','CVX','LLY','ABBV','MRK','BAC','PEP','KO','COST','TMO','DIS','MCD','CSCO','PFE','ACN','VZ','ADBE','CMCSA','NKE','TXN','HON','AMGN','IBM','LOW','UNP','QCOM','SPGI','PM','INTU','RTX','MDT','GS','CVS','DE','BLK','TGT','SBUX','CAT','AXP','AMAT','ISRG','GILD','MS','SCHW','LMT','PYPL','ADP','MDLZ','CSX','EL','GE','TJX','ITW','C','ZTS','NOC','USB','DUK','SO','CI','BDX','MMM','PLD','CCI','KMB','O','CL','NSC','EW','APD','FISV','PNC','FIS','SHW','CME','PSA','EQIX','ICE','MCO','COF','MET','TRV','DHR','AON','SLB','APTV','SPY','QQQ','IWM','TLT','IEF','AGG','HYG','JNK','LQD','EMB','GLD','SLV','GDX','SOXX',
]

SQL = """
WITH price_returns AS (
  SELECT
    ticker, date, close, volume,
    LN(close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)) AS log_return
  FROM silver.unified_prices
  WHERE close > 0 AND close IS NOT NULL
    AND date >= %(cutoff)s
    AND ticker = ANY(%(universe)s)
)
INSERT INTO silver.technical_indicators
  (ticker, date, sma_20, sma_50, sma_200, ema_12, ema_26, rsi_14, macd_line, macd_signal, macd_histogram, bb_upper, bb_middle, bb_lower, bb_width, atr_14, volatility_20d, volume_sma_20, volume_ratio, price_vs_sma50_pct, price_vs_sma200_pct, calculated_at)
SELECT
  ticker, date,
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
  CASE WHEN AVG(close) OVER w20 = 0 THEN NULL ELSE LEAST(GREATEST((4 * STDDEV(close) OVER w20) / AVG(close) OVER w20, -9999), 9999) END AS bb_width,
  NULL AS atr_14,
  CASE WHEN STDDEV(log_return) OVER w20 IS NULL THEN NULL WHEN STDDEV(log_return) OVER w20 > 10 THEN 10 WHEN STDDEV(log_return) OVER w20 < -10 THEN -10 ELSE STDDEV(log_return) OVER w20 * SQRT(252) END AS volatility_20d,
  LEAST(AVG(volume) OVER w20, 9999999999) AS volume_sma_20,
  volume::numeric / NULLIF(AVG(volume) OVER w20, 0) AS volume_ratio,
  CASE WHEN AVG(close) OVER w50 = 0 THEN NULL ELSE LEAST(GREATEST((close / NULLIF(AVG(close) OVER w50, 0) - 1) * 100, -9999), 9999) END AS price_vs_sma50_pct,
  CASE WHEN AVG(close) OVER w200 = 0 THEN NULL ELSE LEAST(GREATEST((close / NULLIF(AVG(close) OVER w200, 0) - 1) * 100, -9999), 9999) END AS price_vs_sma200_pct,
  NOW()
FROM price_returns
WINDOW
  w12  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW),
  w20  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
  w26  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 25 PRECEDING AND CURRENT ROW),
  w50  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
  w200 AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
ON CONFLICT (ticker, date) DO UPDATE SET
  sma_20 = EXCLUDED.sma_20, sma_50 = EXCLUDED.sma_50, sma_200 = EXCLUDED.sma_200,
  bb_upper = EXCLUDED.bb_upper, bb_lower = EXCLUDED.bb_lower,
  volatility_20d = EXCLUDED.volatility_20d,
  price_vs_sma50_pct = EXCLUDED.price_vs_sma50_pct, price_vs_sma200_pct = EXCLUDED.price_vs_sma200_pct,
  calculated_at = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL, {'cutoff': CUTOFF_DATE, 'universe': UNIVERSE})
    print(f"✅ silver.technical_indicators full backfill: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    run()
