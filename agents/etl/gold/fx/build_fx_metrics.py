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

Computes SMA/Bollinger/volatility/regime in SQL, then fills the true
technical indicators (Wilder RSI-14, EMA-based MACD line/signal/histogram,
Wilder ATR-14) through shared/scripts/indicators.py in a second pass.

2026-07-24 (ROADMAP G3): the SQL used to emit rsi_14/macd_signal/macd_histogram/
atr_14 as NULL and macd_line as AVG(12)-AVG(26) (an SMA difference, not an EMA
MACD). That is the same bug class that killed the silver MACD. The indicators
are now computed in Python via indicators.py — the single source of truth — so
silver, FX and index agree. Never fabricated: NULL where history is too short.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
sys.path.insert(0, 'shared/scripts')  # legacy CWD-relative bootstrap
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from price_indicators import indicator_rows, WARMUP_CALENDAR_DAYS, WRITE_TAIL_DAYS

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
    NULL::numeric AS rsi_14,          -- filled in stage 2 via indicators.py
    NULL::numeric AS macd_line,       -- filled in stage 2 (was AVG diff, i.e. SMA-MACD)
    NULL::numeric AS macd_signal,     -- filled in stage 2
    NULL::numeric AS macd_histogram,  -- filled in stage 2
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
    w20  AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
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
  open            = EXCLUDED.open,
  high            = EXCLUDED.high,
  low             = EXCLUDED.low,
  close_price     = EXCLUDED.close_price,
  log_return      = EXCLUDED.log_return,
  sma_5           = EXCLUDED.sma_5,
  sma_20          = EXCLUDED.sma_20,
  sma_50          = EXCLUDED.sma_50,
  rsi_14          = EXCLUDED.rsi_14,
  macd_line       = EXCLUDED.macd_line,
  macd_signal     = EXCLUDED.macd_signal,
  macd_histogram  = EXCLUDED.macd_histogram,
  bollinger_width = EXCLUDED.bollinger_width,
  atr_14          = EXCLUDED.atr_14,
  volatility_20d  = EXCLUDED.volatility_20d,
  market_regime   = EXCLUDED.market_regime;
"""

# Stage 2 — fill the true indicators through indicators.py. Warmup reads a long
# window of daily OHLC back from gold.fx_metrics itself (which accumulates
# history across daily runs); only the recent tail is written back.
FILL_FETCH_SQL = """
SELECT ticker, date, high, low, close_price
FROM gold.fx_metrics
WHERE close_price > 0 AND close_price IS NOT NULL
  AND date >= (SELECT MAX(date) - INTERVAL '%s days' FROM gold.fx_metrics)
ORDER BY ticker, date
"""

FILL_UPDATE_SQL = """
UPDATE gold.fx_metrics g SET
  rsi_14         = i.rsi_14,
  macd_line      = i.macd_line,
  macd_signal    = i.macd_signal,
  macd_histogram = i.macd_histogram,
  atr_14         = i.atr_14
FROM _fx_ind i
WHERE g.ticker = i.ticker AND g.date = i.date
"""


def fill_indicators(conn):
    from datetime import timedelta
    from psycopg2.extras import execute_values
    cur = conn.cursor()
    cur.execute(FILL_FETCH_SQL % WARMUP_CALENDAR_DAYS)
    rows = cur.fetchall()
    cur.execute("SELECT MAX(date) FROM gold.fx_metrics")
    max_date = cur.fetchone()[0]
    cutoff = (max_date - timedelta(days=WRITE_TAIL_DAYS)) if max_date else None
    payload = indicator_rows(rows, write_cutoff=cutoff)
    if not payload:
        print("⚠️  fx indicators: no rows to fill")
        return
    cur.execute("""CREATE TEMP TABLE _fx_ind
        (ticker text, date date, rsi_14 numeric, macd_line numeric,
         macd_signal numeric, macd_histogram numeric, atr_14 numeric)
        ON COMMIT DROP""")
    execute_values(cur, "INSERT INTO _fx_ind VALUES %s", payload, page_size=1000)
    cur.execute(FILL_UPDATE_SQL)
    print(f"✅ gold.fx_metrics indicators filled: {cur.rowcount} rows (RSI/MACD/ATR via indicators.py)")


def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    print(f"✅ gold.fx_metrics updated: {cur.rowcount} rows upserted")
    fill_indicators(conn)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
