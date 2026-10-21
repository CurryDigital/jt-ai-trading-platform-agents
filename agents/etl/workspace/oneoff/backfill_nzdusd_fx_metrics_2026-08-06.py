#!/usr/bin/env python3
"""
One-off (kanban t_aa97c50d): backfill NZDUSD full history in gold.fx_metrics
from silver.unified_prices.

Why: gold.fx_metrics was historically fed by bronze.fx_prices (IBKR), which
carried only 3 NZDUSD rows (2026-06-17). After the 2026-08-06 rewire of
gold/fx/build_fx_metrics.py onto the silver alias series, NZDUSD had just a
44-day window in gold while silver carries 2493 daily rows (yfinance '=X'
derived). This script upserts the full NZDUSD silver history with the same
stage-1 SQL shape as build_fx_metrics.py, then recomputes RSI/MACD/ATR over
the full history (no write cutoff).

Scope guard: touches ticker='NZDUSD' only. Other tickers keep their
bronze-era history.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts')))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from price_indicators import indicator_rows
from psycopg2.extras import execute_values

TICKER = 'NZDUSD'

STAGE1_SQL = """
INSERT INTO gold.fx_metrics
  (ticker, date,
   open, high, low, close_price,
   log_return,
   sma_5, sma_20, sma_50,
   bollinger_width, volatility_20d,
   market_regime)
WITH deduped AS (
  SELECT ticker, date::timestamp AS date, open, high, low, close
  FROM silver.unified_prices
  WHERE ticker = %s
),
returns_calc AS (
  SELECT ticker, date, open, high, low, close,
    LN(close / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)) AS log_return
  FROM deduped
),
with_indicators AS (
  SELECT
    ticker, date, open, high, low, close AS close_price, log_return,
    AVG(close) OVER w5   AS sma_5,
    AVG(close) OVER w20  AS sma_20,
    AVG(close) OVER w50  AS sma_50,
    (4 * STDDEV(close) OVER w20) / NULLIF(AVG(close) OVER w20, 0) AS bollinger_width,
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
SELECT ticker, date, open, high, low, close_price, log_return,
       sma_5, sma_20, sma_50, bollinger_width, volatility_20d, market_regime
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
  bollinger_width = EXCLUDED.bollinger_width,
  volatility_20d  = EXCLUDED.volatility_20d,
  market_regime   = EXCLUDED.market_regime;
"""


def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(STAGE1_SQL, (TICKER,))
    print(f"stage1 upserted: {cur.rowcount} rows")

    cur.execute(
        "SELECT ticker, date, high, low, close_price FROM gold.fx_metrics "
        "WHERE ticker = %s AND close_price IS NOT NULL AND close_price > 0 "
        "ORDER BY ticker, date", (TICKER,))
    rows = cur.fetchall()
    print(f"indicator input rows: {len(rows)}")

    payload = indicator_rows(rows, write_cutoff=None)  # write full history
    cur.execute("""CREATE TEMP TABLE _fx_ind_bf
        (ticker text, date date, rsi_14 numeric, macd_line numeric,
         macd_signal numeric, macd_histogram numeric, atr_14 numeric)
        ON COMMIT DROP""")
    execute_values(cur, "INSERT INTO _fx_ind_bf VALUES %s", payload, page_size=1000)
    cur.execute("""
        UPDATE gold.fx_metrics g SET
          rsi_14         = i.rsi_14,
          macd_line      = i.macd_line,
          macd_signal    = i.macd_signal,
          macd_histogram = i.macd_histogram,
          atr_14         = i.atr_14
        FROM _fx_ind_bf i
        WHERE g.ticker = i.ticker AND g.date = i.date""")
    print(f"indicators updated: {cur.rowcount} rows")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    run()
