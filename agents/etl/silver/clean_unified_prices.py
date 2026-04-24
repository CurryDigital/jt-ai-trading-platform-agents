#!/usr/bin/env python3
"""
Silver Transform: Unified Prices
Merges bronze.yf_prices + bronze.fmp_prices + bronze.manual_prices
→ silver.unified_prices (deduplicated, normalized, source-ranked)
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

UPSERT_SQL = """
INSERT INTO silver.unified_prices
    (ticker, asset_class, market, date, open, high, low, close, volume,
     adjusted_close, returns_1d, returns_log, primary_source, all_sources, updated_at)
WITH ranked AS (
    -- yfinance (priority 1)
    SELECT
        ticker,
        NULL::varchar AS asset_class,
        NULL::varchar AS market,
        date,
        open::numeric(20,8),
        high::numeric(20,8),
        low::numeric(20,8),
        close::numeric(20,8),
        volume::numeric,
        adjusted_close::numeric(20,8),
        'yfinance' AS src,
        1 AS priority
    FROM bronze.yf_prices

    UNION ALL

    -- FMP (priority 2)
    SELECT ticker, NULL, NULL, date,
        open::numeric(20,8), high::numeric(20,8),
        low::numeric(20,8), close::numeric(20,8),
        volume::numeric, adjusted_close::numeric(20,8),
        'fmp', 2
    FROM bronze.fmp_prices

    UNION ALL

    -- Manual (priority 3)
    SELECT ticker, NULL, NULL, date,
        open::numeric(20,8), high::numeric(20,8),
        low::numeric(20,8), close::numeric(20,8),
        volume::numeric, adjusted_close::numeric(20,8),
        'manual', 3
    FROM bronze.manual_prices
),
best AS (
    SELECT DISTINCT ON (ticker, date) *
    FROM ranked
    ORDER BY ticker, date, priority
)
SELECT
    b.ticker,
    ar.asset_class,
    ar.market,
    b.date,
    b.open, b.high, b.low, b.close, b.volume, b.adjusted_close,
    -- 1-day return
    ROUND(
        (b.close - LAG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.date))
        / NULLIF(LAG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.date), 0),
        6
    ) AS returns_1d,
    -- log return
    ROUND(
        LN(NULLIF(b.close, 0) / NULLIF(LAG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.date), 0)),
        6
    ) AS returns_log,
    b.src AS primary_source,
    jsonb_build_array(b.src) AS all_sources,
    NOW() AS updated_at
FROM best b
LEFT JOIN silver.asset_registry ar ON ar.ticker = b.ticker
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

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(UPSERT_SQL)
    print(f"✅ silver.unified_prices — {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
