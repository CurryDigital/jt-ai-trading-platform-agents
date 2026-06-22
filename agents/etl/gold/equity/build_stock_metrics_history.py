# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Equity: Stock Metrics History
Reads from: silver.unified_prices, silver.technical_indicators
Writes to:  gold.stock_metrics_history

Incremental: only processes dates not already in stock_metrics_history.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
WITH max_history AS (
    SELECT MAX(date) AS max_date FROM gold.stock_metrics_history
),
prices AS (
    SELECT
        p.ticker,
        p.date,
        p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 5)  OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_5d_ago,
        LAG(p.close, 21) OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_21d_ago,
        MAX(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date
                           ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high_52w
    FROM silver.unified_prices p
    WHERE p.date >= COALESCE((SELECT max_date - INTERVAL '300 days' FROM max_history), '2000-01-01')
)
INSERT INTO gold.stock_metrics_history
  (ticker, date, sector,
   open, high, low, close, volume, vwap,
   rsi_14, macd_line, macd_signal, macd_hist,
   sma_50, sma_200,
   stoch_k, stoch_d, adx, adx_plus_di, adx_minus_di,
   psar, psar_direction,
   atr_14, beta, volatility_21d,
   returns_1d, returns_5d, returns_21d,
   volume_sma_20, volume_ratio,
   golden_cross, death_cross, above_sma_200,
   rel_strength_sp500, rel_strength_sector,
   dist_from_52w_high, dist_from_ytd_high, dist_from_ytd_low,
   created_at)

SELECT
  p.ticker,
  p.date,
  ar.sector,
  p.open, p.high, p.low, p.close, p.volume,
  NULL AS vwap,
  ti.rsi_14,
  ti.macd_line, ti.macd_signal, ti.macd_histogram,
  ti.sma_50, ti.sma_200,
  ti.stoch_k, ti.stoch_d,
  ti.adx, ti.adx_plus_di, ti.adx_minus_di,
  ti.psar, ti.psar_direction,
  ti.atr_14,
  NULL AS beta,
  ti.volatility_20d AS volatility_21d,
  (p.close / NULLIF(LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date), 0) - 1) AS returns_1d,
  (p.close / NULLIF(p.close_5d_ago, 0) - 1) AS returns_5d,
  (p.close / NULLIF(p.close_21d_ago, 0) - 1) AS returns_21d,
  ti.volume_sma_20, ti.volume_ratio,
  (ti.sma_50 > ti.sma_200 AND
   LAG(ti.sma_50) OVER w <= LAG(ti.sma_200) OVER w) AS golden_cross,
  (ti.sma_50 < ti.sma_200 AND
   LAG(ti.sma_50) OVER w >= LAG(ti.sma_200) OVER w) AS death_cross,
  p.close > ti.sma_200 AS above_sma_200,
  NULL AS rel_strength_sp500,
  NULL AS rel_strength_sector,
  (p.close / NULLIF(p.high_52w, 0) - 1) * 100 AS dist_from_52w_high,
  NULL AS dist_from_ytd_high,
  NULL AS dist_from_ytd_low,
  NOW()

FROM prices p
JOIN silver.technical_indicators ti USING (ticker, date)
JOIN silver.asset_registry ar ON ar.ticker = p.ticker
WHERE ar.asset_class = 'STOCK'
  AND p.date > COALESCE((SELECT max_date FROM max_history), '2000-01-01')
WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)

ON CONFLICT (ticker, date) DO UPDATE SET
  close        = EXCLUDED.close,
  rsi_14       = EXCLUDED.rsi_14,
  golden_cross = EXCLUDED.golden_cross,
  above_sma_200 = EXCLUDED.above_sma_200,
  created_at   = EXCLUDED.created_at;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    print(f"✅ gold.stock_metrics_history updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
