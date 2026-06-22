#!/usr/bin/env python3
"""
Silver Transform: Technical Indicators
Reads silver.unified_prices → calculates → silver.technical_indicators
Incremental: processes tickers where unified_prices has newer data than technical_indicators
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

UPSERT_SQL = """
INSERT INTO silver.technical_indicators
    (ticker, date,
     sma_20, sma_50, sma_200,
     ema_12, ema_26,
     rsi_14,
     macd_line, macd_signal, macd_histogram,
     bb_upper, bb_middle, bb_lower, bb_width,
     atr_14, volatility_20d,
     volume_sma_20, volume_ratio,
     price_vs_sma50_pct, price_vs_sma200_pct,
     calculated_at)
WITH tickers_to_update AS (
    SELECT DISTINCT p.ticker
    FROM silver.unified_prices p
    LEFT JOIN (
        SELECT ticker, MAX(date) AS max_date
        FROM silver.technical_indicators
        GROUP BY ticker
    ) t ON p.ticker = t.ticker
    WHERE p.date > COALESCE(t.max_date, '1900-01-01')
      AND p.date >= CURRENT_DATE - INTERVAL '60 days'
),
base AS (
    SELECT p.ticker, p.date, p.close, p.high, p.low, p.volume,
        AVG(p.close) OVER w20  AS sma_20,
        AVG(p.close) OVER w50  AS sma_50,
        AVG(p.close) OVER w200 AS sma_200,
        STDDEV(p.close) OVER w20 AS std_20,
        AVG(p.high - p.low) OVER w14 AS atr_14,
        AVG(p.volume) OVER w20 AS volume_sma_20
    FROM silver.unified_prices p
    JOIN tickers_to_update t ON p.ticker = t.ticker
    WINDOW
        w14  AS (PARTITION BY p.ticker ORDER BY p.date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),
        w20  AS (PARTITION BY p.ticker ORDER BY p.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w50  AS (PARTITION BY p.ticker ORDER BY p.date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
        w200 AS (PARTITION BY p.ticker ORDER BY p.date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
),
price_changes AS (
    SELECT p.ticker, p.date, p.close,
        LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close
    FROM silver.unified_prices p
    JOIN tickers_to_update t ON p.ticker = t.ticker
),
gain_loss AS (
    SELECT ticker, date, close,
        GREATEST(close - prev_close, 0) AS gain,
        GREATEST(prev_close - close, 0) AS loss
    FROM price_changes
    WHERE prev_close IS NOT NULL
),
rsi_calc AS (
    SELECT ticker, date, close,
        ROUND(
            100 - 100 / (1 + NULLIF(
                AVG(gain) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW)
                /
                NULLIF(AVG(loss) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW), 0)
            , 0))
        , 4) AS rsi_14
    FROM gain_loss
)
SELECT
    b.ticker, b.date,
    ROUND(b.sma_20::numeric, 4)  AS sma_20,
    ROUND(b.sma_50::numeric, 4)  AS sma_50,
    ROUND(b.sma_200::numeric, 4) AS sma_200,
    NULL::numeric AS ema_12,
    NULL::numeric AS ema_26,
    r.rsi_14,
    NULL::numeric AS macd_line,
    NULL::numeric AS macd_signal,
    NULL::numeric AS macd_histogram,
    ROUND((b.sma_20 + 2 * b.std_20)::numeric, 4) AS bb_upper,
    ROUND(b.sma_20::numeric, 4)                   AS bb_middle,
    ROUND((b.sma_20 - 2 * b.std_20)::numeric, 4) AS bb_lower,
    ROUND(CASE WHEN b.sma_20 > 0 THEN (4 * b.std_20 / b.sma_20 * 100)::numeric ELSE NULL END, 4) AS bb_width,
    ROUND(b.atr_14::numeric, 4)  AS atr_14,
    ROUND((b.std_20 / NULLIF(b.sma_20, 0) * SQRT(252) * 100)::numeric, 4) AS volatility_20d,
    ROUND(b.volume_sma_20::numeric, 2) AS volume_sma_20,
    ROUND((b.volume / NULLIF(b.volume_sma_20, 0))::numeric, 4) AS volume_ratio,
    ROUND(((b.close - b.sma_50)  / NULLIF(b.sma_50, 0)  * 100)::numeric, 4) AS price_vs_sma50_pct,
    ROUND(((b.close - b.sma_200) / NULLIF(b.sma_200, 0) * 100)::numeric, 4) AS price_vs_sma200_pct,
    NOW() AS calculated_at
FROM base b
JOIN rsi_calc r USING (ticker, date)
ON CONFLICT (ticker, date) DO UPDATE SET
    sma_20             = EXCLUDED.sma_20,
    sma_50             = EXCLUDED.sma_50,
    sma_200            = EXCLUDED.sma_200,
    rsi_14             = EXCLUDED.rsi_14,
    bb_upper           = EXCLUDED.bb_upper,
    bb_middle          = EXCLUDED.bb_middle,
    bb_lower           = EXCLUDED.bb_lower,
    bb_width           = EXCLUDED.bb_width,
    atr_14             = EXCLUDED.atr_14,
    volatility_20d     = EXCLUDED.volatility_20d,
    volume_sma_20      = EXCLUDED.volume_sma_20,
    volume_ratio       = EXCLUDED.volume_ratio,
    price_vs_sma50_pct  = EXCLUDED.price_vs_sma50_pct,
    price_vs_sma200_pct = EXCLUDED.price_vs_sma200_pct,
    calculated_at      = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(UPSERT_SQL)
    print(f"✅ silver.technical_indicators — {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
