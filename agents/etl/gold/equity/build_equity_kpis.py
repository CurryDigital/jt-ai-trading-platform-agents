#!/usr/bin/env python3
"""
Gold Equity: KPIs Metrics
Reads from: silver.unified_prices, silver.technical_indicators,
            silver.unified_earnings, silver.asset_registry
Writes to:  gold.kpis_metrics

This is the master equity signal table powering the Command tab.
Computes all conditions (cond_*) and strategy trigger flags (s001_*, s007_*, etc.)
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
INSERT INTO gold.kpis_metrics
  (ticker, date,
   close, open, high, low, volume,
   change_1d, change_1w, change_1m, change_3m, change_ytd,
   sma_20, sma_50, sma_200, ema_12, ema_26,
   rsi_14,
   macd_line, macd_signal, macd_histogram,
   bb_upper, bb_middle, bb_lower, bb_width, bb_position, bb_squeeze,
   atr_14, atr_14_pct,
   volatility_20d, volatility_50d,
   volume_sma_20, volume_ratio,
   price_vs_sma20_pct, price_vs_sma50_pct, price_vs_sma200_pct,
   -- Core conditions
   cond_above_sma20, cond_below_sma20,
   cond_above_sma50, cond_below_sma50,
   cond_above_sma200, cond_below_sma200,
   cond_high_volume, cond_low_volume,
   cond_rsi_oversold, cond_rsi_overbought,
   cond_rsi_below_40, cond_rsi_below_45,
   cond_bb_squeeze,
   cond_macd_bullish, cond_macd_bearish,
   cond_golden_cross, cond_death_cross,
   -- Strategy triggers
   s001_high_vol_pullback,
   s002_oversold_bounce,
   s007_3day_monday,
   s012_tech_momentum,
   updated_at)

SELECT
  p.ticker,
  p.date,
  p.close, p.open, p.high, p.low, p.volume,

  -- Price changes
  p.returns_1d * 100 AS change_1d,
  (p.close / NULLIF(LAG(p.close, 5)  OVER w, 0) - 1) * 100 AS change_1w,
  (p.close / NULLIF(LAG(p.close, 21) OVER w, 0) - 1) * 100 AS change_1m,
  (p.close / NULLIF(LAG(p.close, 63) OVER w, 0) - 1) * 100 AS change_3m,
  NULL AS change_ytd,

  -- Technical indicators from silver
  ti.sma_20, ti.sma_50, ti.sma_200,
  ti.ema_12, ti.ema_26,
  ti.rsi_14,
  ti.macd_line, ti.macd_signal, ti.macd_histogram,
  ti.bb_upper, ti.bb_middle, ti.bb_lower, ti.bb_width,
  -- Bollinger position (0=lower band, 1=upper band)
  (p.close - ti.bb_lower) / NULLIF(ti.bb_upper - ti.bb_lower, 0) AS bb_position,
  -- BB squeeze: width < 10th percentile → TRUE (simplified)
  ti.bb_width < 0.05 AS bb_squeeze,
  ti.atr_14,
  ti.atr_14 / NULLIF(p.close, 0) * 100 AS atr_14_pct,
  ti.volatility_20d,
  NULL AS volatility_50d,
  ti.volume_sma_20, ti.volume_ratio,
  (p.close / NULLIF(ti.sma_20, 0) - 1) * 100 AS price_vs_sma20_pct,
  ti.price_vs_sma50_pct,
  ti.price_vs_sma200_pct,

  -- Conditions
  p.close > ti.sma_20  AS cond_above_sma20,
  p.close < ti.sma_20  AS cond_below_sma20,
  p.close > ti.sma_50  AS cond_above_sma50,
  p.close < ti.sma_50  AS cond_below_sma50,
  p.close > ti.sma_200 AS cond_above_sma200,
  p.close < ti.sma_200 AS cond_below_sma200,
  ti.volume_ratio > 1.5 AS cond_high_volume,
  ti.volume_ratio < 0.5 AS cond_low_volume,
  ti.rsi_14 < 30 AS cond_rsi_oversold,
  ti.rsi_14 > 70 AS cond_rsi_overbought,
  ti.rsi_14 < 40 AS cond_rsi_below_40,
  ti.rsi_14 < 45 AS cond_rsi_below_45,
  ti.bb_width < 0.05 AS cond_bb_squeeze,
  ti.macd_histogram > 0 AS cond_macd_bullish,
  ti.macd_histogram < 0 AS cond_macd_bearish,
  -- Golden cross: SMA50 crossed above SMA200 today
  (ti.sma_50 > ti.sma_200 AND
   LAG(ti.sma_50) OVER w <= LAG(ti.sma_200) OVER w) AS cond_golden_cross,
  (ti.sma_50 < ti.sma_200 AND
   LAG(ti.sma_50) OVER w >= LAG(ti.sma_200) OVER w) AS cond_death_cross,

  -- S001: High-vol pullback (high volume + price down + RSI < 45)
  (ti.volume_ratio > 1.5 AND p.returns_1d < -0.01 AND ti.rsi_14 < 45) AS s001_high_vol_pullback,

  -- S002: Oversold bounce (RSI < 30 + price above SMA200)
  (ti.rsi_14 < 30 AND p.close > ti.sma_200) AS s002_oversold_bounce,

  -- S007: 3-day Monday (RSI < 40 + last 3 days negative + today is Monday)
  (ti.rsi_14 < 40
   AND p.returns_1d < 0
   AND LAG(p.returns_1d, 1) OVER w < 0
   AND LAG(p.returns_1d, 2) OVER w < 0
   AND EXTRACT(DOW FROM p.date) = 1) AS s007_3day_monday,

  -- S012: Tech momentum (close > SMA50 + MACD bullish + RSI 50-65)
  (p.close > ti.sma_50 AND ti.macd_histogram > 0 AND ti.rsi_14 BETWEEN 50 AND 65) AS s012_tech_momentum,

  NOW()

FROM silver.unified_prices p
JOIN silver.technical_indicators ti ON ti.ticker = p.ticker AND ti.date = p.date
WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)

ON CONFLICT (ticker, date) DO UPDATE SET
  close               = EXCLUDED.close,
  rsi_14              = EXCLUDED.rsi_14,
  macd_histogram      = EXCLUDED.macd_histogram,
  cond_golden_cross   = EXCLUDED.cond_golden_cross,
  s001_high_vol_pullback = EXCLUDED.s001_high_vol_pullback,
  s002_oversold_bounce   = EXCLUDED.s002_oversold_bounce,
  s007_3day_monday       = EXCLUDED.s007_3day_monday,
  s012_tech_momentum     = EXCLUDED.s012_tech_momentum,
  updated_at          = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    print(f"✅ gold.kpis_metrics updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
