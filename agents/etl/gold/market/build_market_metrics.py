# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Market: Market Indices & Sentiment
Reads from: silver.market_indices, silver.unified_prices
Writes to:  gold.index_metrics, gold.market_sentiment_daily, gold.market_regimes
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from price_indicators import indicator_rows, WARMUP_CALENDAR_DAYS, WRITE_TAIL_DAYS

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
  NULL::numeric AS macd_line,    -- filled in stage 2 via indicators.py
  NULL::numeric AS macd_signal,  -- filled in stage 2
  NULL::numeric AS macd_hist,    -- filled in stage 2
  NULL::numeric AS atr_14,       -- filled in stage 2
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
WHERE m.date >= CURRENT_DATE - INTERVAL '14 days'
WINDOW w AS (PARTITION BY m.ticker ORDER BY m.date)

-- 2026-07-22: refresh every computed non-key column on conflict. The daily
-- run re-inserts the last 14 days, so the old 5-column update left ma_50/200,
-- rsi_14, returns_*, 52w range, volatility etc. stale on ~13 of every 14
-- dates. index_metrics is a pure (ticker,date) metric table — all recomputed.
ON CONFLICT (ticker, date) DO UPDATE SET
  name                  = EXCLUDED.name,
  market                = EXCLUDED.market,
  region                = EXCLUDED.region,
  currency              = EXCLUDED.currency,
  open                  = EXCLUDED.open,
  high                  = EXCLUDED.high,
  low                   = EXCLUDED.low,
  close                 = EXCLUDED.close,
  volume                = EXCLUDED.volume,
  change_pct            = EXCLUDED.change_pct,
  change_amount         = EXCLUDED.change_amount,
  ytd_change            = EXCLUDED.ytd_change,
  ma_50                 = EXCLUDED.ma_50,
  ma_200                = EXCLUDED.ma_200,
  above_ma_50           = EXCLUDED.above_ma_50,
  above_ma_200          = EXCLUDED.above_ma_200,
  golden_cross          = EXCLUDED.golden_cross,
  rsi_14                = EXCLUDED.rsi_14,
  macd_line             = EXCLUDED.macd_line,
  macd_signal           = EXCLUDED.macd_signal,
  macd_hist             = EXCLUDED.macd_hist,
  atr_14                = EXCLUDED.atr_14,
  _52_week_high         = EXCLUDED._52_week_high,
  _52_week_low          = EXCLUDED._52_week_low,
  _52_week_range_pct    = EXCLUDED._52_week_range_pct,
  returns_1d            = EXCLUDED.returns_1d,
  returns_5d            = EXCLUDED.returns_5d,
  returns_21d           = EXCLUDED.returns_21d,
  returns_63d           = EXCLUDED.returns_63d,
  returns_252d          = EXCLUDED.returns_252d,
  volatility_21d        = EXCLUDED.volatility_21d,
  is_volatility_index   = EXCLUDED.is_volatility_index,
  created_at            = NOW();
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
  rating             = EXCLUDED.rating,
  score              = EXCLUDED.score,
  bull_percentage    = EXCLUDED.bull_percentage,
  bear_percentage    = EXCLUDED.bear_percentage,
  index_change_score = EXCLUDED.index_change_score,
  breadth_score      = EXCLUDED.breadth_score,
  technical_score    = EXCLUDED.technical_score,
  vix_score          = EXCLUDED.vix_score,
  index_change_pct   = EXCLUDED.index_change_pct,
  advancing_pct      = EXCLUDED.advancing_pct,
  above_ma50_pct     = EXCLUDED.above_ma50_pct,
  rsi_avg            = EXCLUDED.rsi_avg,
  vix_level          = EXCLUDED.vix_level,
  created_at         = NOW();
"""

# Stage 2 — fill the true MACD (EMA-based) and Wilder ATR through indicators.py.
# rsi_14 comes from silver.market_indices upstream and is left as-is; macd_* and
# atr_14 were hardcoded NULL in the INSERT above. Warmup reads a long window of
# daily OHLC back from gold.index_metrics (which accumulates history across
# runs); only the recent tail is written back.
IDX_FILL_FETCH_SQL = """
SELECT ticker, date, high, low, close
FROM gold.index_metrics
WHERE close > 0 AND close IS NOT NULL
  AND date >= (SELECT MAX(date) - INTERVAL '%s days' FROM gold.index_metrics)
ORDER BY ticker, date
"""

IDX_FILL_UPDATE_SQL = """
UPDATE gold.index_metrics g SET
  macd_line   = i.macd_line,
  macd_signal = i.macd_signal,
  macd_hist   = i.macd_histogram,
  atr_14      = i.atr_14
FROM _idx_ind i
WHERE g.ticker = i.ticker AND g.date = i.date
"""


def fill_index_indicators(conn):
    from datetime import timedelta
    from psycopg2.extras import execute_values
    cur = conn.cursor()
    cur.execute(IDX_FILL_FETCH_SQL % WARMUP_CALENDAR_DAYS)
    rows = cur.fetchall()
    cur.execute("SELECT MAX(date) FROM gold.index_metrics")
    max_date = cur.fetchone()[0]
    cutoff = (max_date - timedelta(days=WRITE_TAIL_DAYS)) if max_date else None
    payload = indicator_rows(rows, write_cutoff=cutoff)
    if not payload:
        print("⚠️  index indicators: no rows to fill")
        return
    cur.execute("""CREATE TEMP TABLE _idx_ind
        (ticker text, date date, rsi_14 numeric, macd_line numeric,
         macd_signal numeric, macd_histogram numeric, atr_14 numeric)
        ON COMMIT DROP""")
    execute_values(cur, "INSERT INTO _idx_ind VALUES %s", payload, page_size=1000)
    cur.execute(IDX_FILL_UPDATE_SQL)
    print(f"✅ gold.index_metrics indicators filled: {cur.rowcount} rows (MACD/ATR via indicators.py)")


def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_INDEX)
    print(f"✅ gold.index_metrics updated: {cur.rowcount} rows upserted")
    fill_index_indicators(conn)
    cur.execute(SQL_SENTIMENT)
    print(f"✅ gold.market_sentiment_daily updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
