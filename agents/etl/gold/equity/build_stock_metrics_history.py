#!/usr/bin/env python3
"""
Gold Equity: Stock Metrics History
Reads from: silver.unified_prices, silver.technical_indicators
Writes to:  gold.stock_metrics_history

Full historical daily metrics for all equities.
Used for backtesting and long-term performance analysis.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
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
  NULL AS vwap,   -- requires intraday data
  ti.rsi_14,
  ti.macd_line, ti.macd_signal, ti.macd_histogram,
  ti.sma_50, ti.sma_200,
  ti.stoch_k, ti.stoch_d,
  ti.adx, ti.adx_plus_di, ti.adx_minus_di,
  ti.psar, ti.psar_direction,
  ti.atr_14,
  NULL AS beta,
  ti.volatility_20d AS volatility_21d,
  p.returns_1d,
  (p.close / NULLIF(LAG(p.close, 5)  OVER w, 0) - 1) AS returns_5d,
  (p.close / NULLIF(LAG(p.close, 21) OVER w, 0) - 1) AS returns_21d,
  ti.volume_sma_20, ti.volume_ratio,
  (ti.sma_50 > ti.sma_200 AND
   LAG(ti.sma_50) OVER w <= LAG(ti.sma_200) OVER w) AS golden_cross,
  (ti.sma_50 < ti.sma_200 AND
   LAG(ti.sma_50) OVER w >= LAG(ti.sma_200) OVER w) AS death_cross,
  p.close > ti.sma_200 AS above_sma_200,
  NULL AS rel_strength_sp500,
  NULL AS rel_strength_sector,
  -- Distance from rolling 52-week high
  (p.close / NULLIF(MAX(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date
                          ROWS BETWEEN 251 PRECEDING AND CURRENT ROW), 0) - 1) * 100
    AS dist_from_52w_high,
  NULL AS dist_from_ytd_high,
  NULL AS dist_from_ytd_low,
  NOW()

FROM silver.unified_prices p
JOIN silver.technical_indicators ti USING (ticker, date)
JOIN silver.asset_registry ar ON ar.ticker = p.ticker
WHERE ar.asset_class = 'STOCK'
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
