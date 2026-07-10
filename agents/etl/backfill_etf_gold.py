#!/usr/bin/env python3
"""
Refresh silver.unified_prices and silver.technical_indicators for backfilled ETFs.
Then rebuild gold.kpis_metrics and gold.stock_metrics_history for those tickers.
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

TARGET_ETFS = [
    'SPY','VTI','VOO','VUG','VYM','SCHD','JEPI','JEPQ','DIA','IWB','IWV',
    'QQQ','IWF','VGT','XLK','SMH','SOXX','IGV','SKYY','CIBR','HACK','QCLN','ARKK','ARKQ','FNGU','TQQQ','QLD','SSO',
    'BND','AGG','TLT','IEF','LQD','HYG','JNK','EMB','MUB','VTEB','GOVT',
    'GLD','SLV','USO','UNG','DBA','DBC','CPER','WEAT','PALL','PPLT',
    'VNQ','SCHH','XLRE','IYR','REM',
    'BITO','IBIT','FBTC'
]

def run_sql(label, sql, params=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    print(f"✅ {label}: {cur.rowcount} rows affected")
    conn.commit()
    conn.close()

# 1. Promote bronze to silver.unified_prices for these tickers
UNIFIED_SQL = """
INSERT INTO silver.unified_prices
    (ticker, asset_class, market, date, open, high, low, close, volume,
     adjusted_close, returns_1d, returns_log, primary_source, all_sources, updated_at)
SELECT
    yf.ticker,
    ar.asset_class,
    ar.market,
    yf.date,
    yf.open::numeric(20,8),
    yf.high::numeric(20,8),
    yf.low::numeric(20,8),
    yf.close::numeric(20,8),
    yf.volume::numeric,
    yf.adjusted_close::numeric(20,8),
    ROUND(
        (yf.close - LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date))
        / NULLIF(LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date), 0),
        6
    ) AS returns_1d,
    ROUND(
        LN(NULLIF(GREATEST(yf.close, 0.0001), 0) / NULLIF(GREATEST(LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date), 0.0001), 0)),
        6
    ) AS returns_log,
    'yfinance' AS primary_source,
    jsonb_build_array('yfinance') AS all_sources,
    NOW() AS updated_at
FROM bronze.yf_prices yf
LEFT JOIN gold.asset_registry ar ON ar.ticker = yf.ticker
WHERE yf.ticker = ANY(%s)
ON CONFLICT (ticker, date) DO UPDATE SET
    open            = EXCLUDED.open,
    high            = EXCLUDED.high,
    low             = EXCLUDED.low,
    close           = EXCLUDED.close,
    volume          = EXCLUDED.volume,
    adjusted_close  = EXCLUDED.adjusted_close,
    returns_1d      = EXCLUDED.returns_1d,
    returns_log     = EXCLUDED.returns_log,
    primary_source  = EXCLUDED.primary_source,
    all_sources     = EXCLUDED.all_sources,
    updated_at      = NOW();
"""

# 2. Compute technical indicators for these tickers (full history, not just 30 days)
TECH_SQL = """
WITH price_returns AS (
  SELECT
    ticker, date, close, volume,
    LN(close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)) AS log_return
  FROM silver.unified_prices
  WHERE close > 0 AND close IS NOT NULL
    AND ticker = ANY(%s)
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
    WHEN STDDEV(log_return) OVER w20 > 10 THEN 10
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

# 3. Build gold.kpis_metrics for these tickers (full history, not just 90 days)
KPIS_SQL = """
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
   cond_above_sma20, cond_below_sma20,
   cond_above_sma50, cond_below_sma50,
   cond_above_sma200, cond_below_sma200,
   cond_high_volume, cond_low_volume,
   cond_rsi_oversold, cond_rsi_overbought,
   cond_rsi_below_40, cond_rsi_below_45,
   cond_bb_squeeze,
   cond_macd_bullish, cond_macd_bearish,
   cond_golden_cross, cond_death_cross,
   s001_high_vol_pullback,
   s002_oversold_bounce,
   s007_3day_monday,
   s012_tech_momentum,
   updated_at)
SELECT
  p.ticker,
  p.date,
  p.close, p.open, p.high, p.low, p.volume,
  p.returns_1d * 100 AS change_1d,
  (p.close / NULLIF(LAG(p.close, 5)  OVER w, 0) - 1) * 100 AS change_1w,
  (p.close / NULLIF(LAG(p.close, 21) OVER w, 0) - 1) * 100 AS change_1m,
  (p.close / NULLIF(LAG(p.close, 63) OVER w, 0) - 1) * 100 AS change_3m,
  NULL AS change_ytd,
  ti.sma_20, ti.sma_50, ti.sma_200,
  ti.ema_12, ti.ema_26,
  ti.rsi_14,
  ti.macd_line, ti.macd_signal, ti.macd_histogram,
  ti.bb_upper, ti.bb_middle, ti.bb_lower, ti.bb_width,
  (p.close - ti.bb_lower) / NULLIF(ti.bb_upper - ti.bb_lower, 0) AS bb_position,
  ti.bb_width < 0.05 AS bb_squeeze,
  ti.atr_14,
  ti.atr_14 / NULLIF(p.close, 0) * 100 AS atr_14_pct,
  ti.volatility_20d,
  NULL AS volatility_50d,
  ti.volume_sma_20, ti.volume_ratio,
  (p.close / NULLIF(ti.sma_20, 0) - 1) * 100 AS price_vs_sma20_pct,
  ti.price_vs_sma50_pct,
  ti.price_vs_sma200_pct,
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
  (ti.sma_50 > ti.sma_200 AND
   LAG(ti.sma_50) OVER w <= LAG(ti.sma_200) OVER w) AS cond_golden_cross,
  (ti.sma_50 < ti.sma_200 AND
   LAG(ti.sma_50) OVER w >= LAG(ti.sma_200) OVER w) AS cond_death_cross,
  (ti.volume_ratio > 1.5 AND p.returns_1d < -0.01 AND ti.rsi_14 < 45) AS s001_high_vol_pullback,
  (ti.rsi_14 < 30 AND p.close > ti.sma_200) AS s002_oversold_bounce,
  (ti.rsi_14 < 40
   AND p.returns_1d < 0
   AND LAG(p.returns_1d, 1) OVER w < 0
   AND LAG(p.returns_1d, 2) OVER w < 0
   AND EXTRACT(DOW FROM p.date) = 1) AS s007_3day_monday,
  (p.close > ti.sma_50 AND ti.macd_histogram > 0 AND ti.rsi_14 BETWEEN 50 AND 65) AS s012_tech_momentum,
  NOW()
FROM silver.unified_prices p
JOIN silver.technical_indicators ti ON ti.ticker = p.ticker AND ti.date = p.date
WHERE p.ticker = ANY(%s)
WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
ON CONFLICT (ticker, date) DO UPDATE SET
  close               = EXCLUDED.close,
  open                = EXCLUDED.open,
  high                = EXCLUDED.high,
  low                 = EXCLUDED.low,
  volume              = EXCLUDED.volume,
  change_1d           = EXCLUDED.change_1d,
  change_1w           = EXCLUDED.change_1w,
  change_1m           = EXCLUDED.change_1m,
  change_3m           = EXCLUDED.change_3m,
  sma_20              = EXCLUDED.sma_20,
  sma_50              = EXCLUDED.sma_50,
  sma_200             = EXCLUDED.sma_200,
  ema_12              = EXCLUDED.ema_12,
  ema_26              = EXCLUDED.ema_26,
  rsi_14              = EXCLUDED.rsi_14,
  macd_line           = EXCLUDED.macd_line,
  macd_signal         = EXCLUDED.macd_signal,
  macd_histogram      = EXCLUDED.macd_histogram,
  bb_upper            = EXCLUDED.bb_upper,
  bb_middle           = EXCLUDED.bb_middle,
  bb_lower            = EXCLUDED.bb_lower,
  bb_width            = EXCLUDED.bb_width,
  bb_position         = EXCLUDED.bb_position,
  bb_squeeze          = EXCLUDED.bb_squeeze,
  atr_14              = EXCLUDED.atr_14,
  atr_14_pct          = EXCLUDED.atr_14_pct,
  volatility_20d      = EXCLUDED.volatility_20d,
  volume_sma_20       = EXCLUDED.volume_sma_20,
  volume_ratio        = EXCLUDED.volume_ratio,
  price_vs_sma20_pct  = EXCLUDED.price_vs_sma20_pct,
  price_vs_sma50_pct  = EXCLUDED.price_vs_sma50_pct,
  price_vs_sma200_pct = EXCLUDED.price_vs_sma200_pct,
  cond_above_sma20    = EXCLUDED.cond_above_sma20,
  cond_below_sma20    = EXCLUDED.cond_below_sma20,
  cond_above_sma50    = EXCLUDED.cond_above_sma50,
  cond_below_sma50    = EXCLUDED.cond_below_sma50,
  cond_above_sma200   = EXCLUDED.cond_above_sma200,
  cond_below_sma200   = EXCLUDED.cond_below_sma200,
  cond_high_volume    = EXCLUDED.cond_high_volume,
  cond_low_volume     = EXCLUDED.cond_low_volume,
  cond_rsi_oversold   = EXCLUDED.cond_rsi_oversold,
  cond_rsi_overbought = EXCLUDED.cond_rsi_overbought,
  cond_rsi_below_40   = EXCLUDED.cond_rsi_below_40,
  cond_rsi_below_45   = EXCLUDED.cond_rsi_below_45,
  cond_bb_squeeze     = EXCLUDED.cond_bb_squeeze,
  cond_macd_bullish   = EXCLUDED.cond_macd_bullish,
  cond_macd_bearish   = EXCLUDED.cond_macd_bearish,
  cond_golden_cross   = EXCLUDED.cond_golden_cross,
  cond_death_cross    = EXCLUDED.cond_death_cross,
  s001_high_vol_pullback = EXCLUDED.s001_high_vol_pullback,
  s002_oversold_bounce   = EXCLUDED.s002_oversold_bounce,
  s007_3day_monday       = EXCLUDED.s007_3day_monday,
  s012_tech_momentum     = EXCLUDED.s012_tech_momentum,
  updated_at          = NOW();
"""

# 4. Build gold.stock_metrics_history for these ETFs (not just STOCK)
SMH_SQL = """
WITH prices AS (
    SELECT
        p.ticker,
        p.date,
        p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 5)  OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_5d_ago,
        LAG(p.close, 21) OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_21d_ago,
        MAX(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date
                           ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high_52w
    FROM silver.unified_prices p
    WHERE p.ticker = ANY(%s)
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
JOIN gold.asset_registry ar ON ar.ticker = p.ticker
WHERE p.ticker = ANY(%s)
WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
ON CONFLICT (ticker, date) DO UPDATE SET
  close        = EXCLUDED.close,
  open         = EXCLUDED.open,
  high         = EXCLUDED.high,
  low          = EXCLUDED.low,
  volume       = EXCLUDED.volume,
  rsi_14       = EXCLUDED.rsi_14,
  macd_line    = EXCLUDED.macd_line,
  macd_signal  = EXCLUDED.macd_signal,
  macd_hist    = EXCLUDED.macd_hist,
  sma_50       = EXCLUDED.sma_50,
  sma_200      = EXCLUDED.sma_200,
  atr_14       = EXCLUDED.atr_14,
  volatility_21d = EXCLUDED.volatility_21d,
  returns_1d   = EXCLUDED.returns_1d,
  returns_5d   = EXCLUDED.returns_5d,
  returns_21d  = EXCLUDED.returns_21d,
  volume_sma_20 = EXCLUDED.volume_sma_20,
  volume_ratio = EXCLUDED.volume_ratio,
  golden_cross = EXCLUDED.golden_cross,
  death_cross  = EXCLUDED.death_cross,
  above_sma_200 = EXCLUDED.above_sma_200,
  dist_from_52w_high = EXCLUDED.dist_from_52w_high,
  created_at   = EXCLUDED.created_at;
"""

if __name__ == '__main__':
    run_sql('silver.unified_prices', UNIFIED_SQL, (TARGET_ETFS,))
    run_sql('silver.technical_indicators', TECH_SQL, (TARGET_ETFS,))
    run_sql('gold.kpis_metrics', KPIS_SQL, (TARGET_ETFS,))
    run_sql('gold.stock_metrics_history', SMH_SQL, (TARGET_ETFS, TARGET_ETFS))
