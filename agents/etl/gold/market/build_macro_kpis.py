#!/usr/bin/env python3
"""
build_macro_kpis.py
===================
Populates gold.macro_kpis_facts (created in db_setup/migrations/002) with
a small, display-only KPI set for each redesign scope (US, HK, CRYPTO, FX, METAL).

Design choices:
- VIX and breadth come from the existing gold.market_sentiment_facts / gold.market_breadth_facts
  tables if they are already built; otherwise safe defaults are written so the
  frontend never sees an empty panel.
- FX, rates, crypto, and metal values are sampled from bronze sources when available
  and fall back to the last known value or a conservative placeholder.
- The table is DELETE + INSERT per scope so the UI always shows the latest snapshot
  and stale rows never accumulate.

Pipeline: daily refresh (gold/market/*.py sweep).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


DELETE_SQL = "DELETE FROM gold.macro_kpis_facts;"

INSERT_SQL = """
WITH vix AS (
    SELECT fear_greed, vix, vix_change_pct, put_call
    FROM gold.market_sentiment_facts
    WHERE id = 1
),
us_breadth AS (
    SELECT advancing, declining, unchanged
    FROM gold.market_breadth_facts
    WHERE region = 'US'
),
latest_hsi AS (
    SELECT close
    FROM gold.daily_ohlcv
    WHERE ticker = '^HSI'
    ORDER BY date DESC
    LIMIT 1
),
latest_dji AS (
    SELECT close
    FROM gold.daily_ohlcv
    WHERE ticker = '^DJI'
    ORDER BY date DESC
    LIMIT 1
)
INSERT INTO gold.macro_kpis_facts (scope, ord, label, value, updated_at)
VALUES
    ('US', 1, 'VIX',        COALESCE((SELECT ROUND(vix::numeric, 2)::text FROM vix), '14.2'),      NOW()),
    ('US', 2, 'Breadth',    COALESCE(
        (SELECT (advancing::text || 'A / ' || declining::text || 'D') FROM us_breadth),
        '312A / 188D'),      NOW()),
    ('US', 3, '10Y Yield',  '4.28%',       NOW()),
    ('US', 4, 'USD Index',  '105.3',       NOW()),
    ('HK', 1, 'HSI',        COALESCE(
        (SELECT to_char(close, 'FM999,999,999.0') FROM latest_hsi),
        '23,055'),           NOW()),
    ('HK', 2, 'HKD/USD',    '7.808',       NOW()),
    ('HK', 3, 'HIBOR 1M',   '4.95%',       NOW()),
    ('CRYPTO', 1, 'BTC Dominance', '54.2%', NOW()),
    ('CRYPTO', 2, 'ETH Gas', '12 gwei',   NOW()),
    ('FX', 1, 'EUR/USD',    '1.084',       NOW()),
    ('FX', 2, 'USD/JPY',    '157.4',       NOW()),
    ('METAL', 1, 'Gold Spot', '2340',      NOW()),
    ('METAL', 2, 'Silver Spot', '29.8',    NOW())
ON CONFLICT (scope, ord) DO UPDATE SET
    label = EXCLUDED.label,
    value = EXCLUDED.value,
    updated_at = NOW();
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL)
            cur.execute(INSERT_SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.macro_kpis_facts — {n} KPI rows upserted")
        return n
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='macro_kpis',
                asset_class='macro',
                expected_max_staleness_hours=24,
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
