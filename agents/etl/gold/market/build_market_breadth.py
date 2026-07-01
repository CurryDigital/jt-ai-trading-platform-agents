#!/usr/bin/env python3
"""
build_market_breadth.py
=======================
Populates gold.market_breadth_facts (created in db_setup/migrations/002).
Computed entirely from gold.daily_ohlcv + gold.asset_registry; no new bronze
source required.

Output schema (one row per region):
    region, advancing, declining, unchanged, new_highs, new_lows, updated_at

Definitions:
    advancing/declining/unchanged → count of tickers with returns_1d > / < / = 0
      on the latest available trading date.
    new_highs/new_lows           → count of tickers whose close is a new 52w
      high / low on the latest date.

Region filter:
    'US' = market = 'US' in asset_registry
    'HK' = market = 'HK' in asset_registry
    Other regions are ignored (frontend v2 only displays US+HK).

UPSERT pattern: there is exactly one row per region — on conflict, replace.
"""

import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


SQL = """
WITH latest_date AS (
    SELECT MAX(date) AS d FROM gold.daily_ohlcv
),
returns_today AS (
    SELECT
        ar.market                            AS region,
        o.ticker,
        o.close,
        o.returns_1d
    FROM   gold.daily_ohlcv o
    JOIN   gold.asset_registry ar ON ar.ticker = o.ticker AND ar.is_active = TRUE
    WHERE  o.date = (SELECT d FROM latest_date)
      AND  ar.market IN ('US','HK')
      AND  ar.asset_class IN ('EQUITY','ETF','STOCK')
),
fifty_two_week AS (
    SELECT
        ticker,
        MAX(high) AS hi_52w,
        MIN(low)  AS lo_52w
    FROM   gold.daily_ohlcv
    WHERE  date BETWEEN (SELECT d - INTERVAL '365 days' FROM latest_date)
                    AND (SELECT d FROM latest_date)
    GROUP  BY ticker
),
joined AS (
    SELECT
        r.region, r.ticker, r.close, r.returns_1d,
        f.hi_52w, f.lo_52w
    FROM   returns_today r
    LEFT JOIN fifty_two_week f USING (ticker)
)
INSERT INTO gold.market_breadth_facts
    (region, advancing, declining, unchanged, new_highs, new_lows, updated_at)
SELECT
    region,
    COUNT(*) FILTER (WHERE returns_1d > 0)                              AS advancing,
    COUNT(*) FILTER (WHERE returns_1d < 0)                              AS declining,
    COUNT(*) FILTER (WHERE returns_1d = 0 OR returns_1d IS NULL)        AS unchanged,
    COUNT(*) FILTER (WHERE close IS NOT NULL AND hi_52w IS NOT NULL AND close >= hi_52w) AS new_highs,
    COUNT(*) FILTER (WHERE close IS NOT NULL AND lo_52w IS NOT NULL AND close <= lo_52w) AS new_lows,
    NOW()                                                              AS updated_at
FROM joined
GROUP BY region
ON CONFLICT (region) DO UPDATE SET
    advancing   = EXCLUDED.advancing,
    declining   = EXCLUDED.declining,
    unchanged   = EXCLUDED.unchanged,
    new_highs   = EXCLUDED.new_highs,
    new_lows    = EXCLUDED.new_lows,
    updated_at  = EXCLUDED.updated_at;
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.market_breadth_facts — {n} region rows upserted")
        return n
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='market_breadth',
                asset_class='equity',
                expected_max_staleness_hours=30,
                error=error,
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


if __name__ == "__main__":
    try:
        build()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
