#!/usr/bin/env python3
"""
Silver Transform: FX pair aliases (kanban t_464bcdb1)
=====================================================
Maintains non-suffixed FX pair series (EURUSD, GBPUSD, USDJPY, ...) in
silver.unified_prices as aliases of their yfinance '=X' counterparts.

Why: the non-suffixed series were historically fed from bronze.fx_prices
(IBKR), but IBKR FX historical ingest is disabled (paper account lacks the
FX data subscription — see bronze/ibkr/ingest_ibkr.py), so those rows froze
at 2026-06-16. yfinance only serves the '=X' form. This step derives the
alias rows from the canonical '=X' series already maintained by
clean_unified_prices.py, so the aliases stay fresh as long as the '=X'
ingest is fresh.

Alias discovery is DB-backed (no hardcoded pair list): any
silver.unified_prices ticker matching ^[A-Z]{6}$ whose '<ticker>=X' form is
an active FX row in gold.asset_registry gets aliased. Also normalizes
legacy asset_class labels ('FOREX'/NULL -> 'FX', market from registry) on
conflict.

Run after silver/clean_unified_prices.py (wired in pipeline_manifest.json).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

ALIAS_SQL = """
WITH aliases AS (
    -- Non-suffixed 6-letter FX tickers present in silver whose '=X' form is
    -- an active FX/CURRENCY row in the registry.
    SELECT DISTINCT up.ticker AS alias, up.ticker || '=X' AS src
    FROM silver.unified_prices up
    JOIN gold.asset_registry ar
      ON ar.ticker = up.ticker || '=X'
     AND ar.is_active = TRUE
     AND ar.asset_class IN ('FX', 'CURRENCY')
    WHERE up.ticker ~ '^[A-Z]{6}$'
),
base AS (
    SELECT a.alias,
           ar.asset_class,
           ar.market,
           s.date, s.open, s.high, s.low, s.close, s.volume, s.adjusted_close
    FROM aliases a
    JOIN silver.unified_prices s ON s.ticker = a.src
    LEFT JOIN silver.asset_registry ar ON ar.ticker = a.src
),
with_returns AS (
    SELECT
        alias, asset_class, market, date, open, high, low, close, volume, adjusted_close,
        ROUND(
            (close - LAG(close) OVER (PARTITION BY alias ORDER BY date))
            / NULLIF(LAG(close) OVER (PARTITION BY alias ORDER BY date), 0),
            6
        ) AS returns_1d,
        ROUND(
            LN(NULLIF(close, 0) / NULLIF(LAG(close) OVER (PARTITION BY alias ORDER BY date), 0)),
            6
        ) AS returns_log
    FROM base
)
INSERT INTO silver.unified_prices
    (ticker, asset_class, market, date, open, high, low, close, volume,
     adjusted_close, returns_1d, returns_log, source, primary_source, all_sources, updated_at)
SELECT
    alias,
    COALESCE(asset_class, 'FX'),
    market,
    date, open, high, low, close, volume, adjusted_close,
    returns_1d, returns_log,
    'yfinance' AS source,
    'yfinance_fx_alias' AS primary_source,
    jsonb_build_array('yfinance', 'fx_alias') AS all_sources,
    NOW()
FROM with_returns
ON CONFLICT (ticker, date) DO UPDATE SET
    asset_class     = EXCLUDED.asset_class,
    market          = EXCLUDED.market,
    open            = EXCLUDED.open,
    high            = EXCLUDED.high,
    low             = EXCLUDED.low,
    close           = EXCLUDED.close,
    volume          = EXCLUDED.volume,
    adjusted_close  = EXCLUDED.adjusted_close,
    returns_1d      = EXCLUDED.returns_1d,
    returns_log     = EXCLUDED.returns_log,
    source          = EXCLUDED.source,
    primary_source  = EXCLUDED.primary_source,
    all_sources     = EXCLUDED.all_sources,
    updated_at      = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(ALIAS_SQL)
    print(f"✅ silver.unified_prices FX aliases — {cur.rowcount} rows upserted")
    cur.execute("""
        SELECT ticker, MIN(date), MAX(date), COUNT(*)
        FROM silver.unified_prices
        WHERE primary_source = 'yfinance_fx_alias'
        GROUP BY ticker ORDER BY ticker;
    """)
    for row in cur.fetchall():
        print(f"   {row[0]}: {row[1]} .. {row[2]}  ({row[3]} rows)")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    run()
