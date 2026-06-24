#!/usr/bin/env python3
"""
build_macro_sectors.py
======================
Populates gold.macro_sectors_facts (created in db_setup/migrations/002).

Daily perf for US GICS-ish sector ETFs from gold.sector_etfs. For HK we
fall back to gold.daily_ohlcv on HSI sector indices.

Output schema:
    region, sector, perf_pct, ord, updated_at

GICS sector → ETF mapping (US):
    Technology              → XLK
    Financials              → XLF
    Energy                  → XLE
    Healthcare              → XLV
    Consumer Discretionary  → XLY
    Consumer Staples        → XLP
    Industrials             → XLI
    Materials               → XLB
    Utilities               → XLU
    Real Estate             → XLRE
    Communication Services  → XLC
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


# Static mapping kept inside the builder. Easy to extend — add a row to the
# VALUES list. The `ord` column is the display order on the UI.
US_SECTOR_MAP = [
    ('Technology',             'XLK',  1),
    ('Financials',             'XLF',  2),
    ('Energy',                 'XLE',  3),
    ('Healthcare',             'XLV',  4),
    ('Consumer Discretionary', 'XLY',  5),
    ('Consumer Staples',       'XLP',  6),
    ('Industrials',            'XLI',  7),
    ('Materials',              'XLB',  8),
    ('Utilities',              'XLU',  9),
    ('Real Estate',            'XLRE', 10),
    ('Communication Services', 'XLC',  11),
]

# Two-step refresh: delete then insert per region. Atomic via wrapping txn.
DELETE_SQL = "DELETE FROM gold.macro_sectors_facts WHERE region = %s;"

INSERT_US_SQL = """
WITH latest AS (
    SELECT MAX(date) AS d FROM gold.sector_etfs
),
prior AS (
    SELECT ticker, date, close_price
    FROM   gold.sector_etfs
    WHERE  date = (SELECT MAX(date) FROM gold.sector_etfs WHERE date < (SELECT d FROM latest))
),
today AS (
    SELECT ticker, close_price
    FROM   gold.sector_etfs
    WHERE  date = (SELECT d FROM latest)
),
mapping (sector, ticker, ord) AS (
    VALUES %s
),
perf AS (
    SELECT
        m.sector,
        m.ord,
        CASE WHEN p.close_price IS NULL OR p.close_price = 0 THEN NULL
             ELSE (t.close_price / p.close_price - 1.0) * 100.0
        END AS perf_pct
    FROM   mapping m
    LEFT JOIN today t ON t.ticker = m.ticker
    LEFT JOIN prior p ON p.ticker = m.ticker
)
INSERT INTO gold.macro_sectors_facts (region, sector, perf_pct, ord, updated_at)
SELECT 'US', sector, ROUND(perf_pct::numeric, 4), ord, NOW()
FROM perf
WHERE perf_pct IS NOT NULL;
"""

# HK sector approximation: pull from gold.daily_ohlcv via asset_registry.sector
# (one row per asset_registry.sector value, weighted by market cap proxy =
# count of tickers).
INSERT_HK_SQL = """
WITH latest_date AS (
    SELECT MAX(date) AS d FROM gold.daily_ohlcv
),
hk_universe AS (
    SELECT
        ar.sector,
        o.returns_1d
    FROM   gold.daily_ohlcv o
    JOIN   gold.asset_registry ar ON ar.ticker = o.ticker AND ar.is_active = TRUE
    WHERE  o.date = (SELECT d FROM latest_date)
      AND  ar.market = 'HK'
      AND  ar.sector IS NOT NULL
      AND  o.returns_1d IS NOT NULL
)
INSERT INTO gold.macro_sectors_facts (region, sector, perf_pct, ord, updated_at)
SELECT
    'HK',
    sector,
    ROUND((AVG(returns_1d) * 100.0)::numeric, 4) AS perf_pct,
    ROW_NUMBER() OVER (ORDER BY AVG(returns_1d) DESC)::INTEGER AS ord,
    NOW()
FROM hk_universe
GROUP BY sector;
"""


def build_us(conn) -> int:
    """US sectors via XLK/XLF/... ETFs."""
    with conn.cursor() as cur:
        cur.execute(DELETE_SQL, ('US',))
        # Inline VALUES tuple substitution (the mapping is constant; safe).
        values_sql = ', '.join(
            cur.mogrify('(%s,%s,%s)', row).decode() for row in US_SECTOR_MAP
        )
        cur.execute(INSERT_US_SQL % values_sql)
        return cur.rowcount


def build_hk(conn) -> int:
    """HK sectors via asset_registry.sector + daily_ohlcv averaging."""
    with conn.cursor() as cur:
        cur.execute(DELETE_SQL, ('HK',))
        cur.execute(INSERT_HK_SQL)
        return cur.rowcount


def build() -> int:
    conn = get_connection()
    try:
        n_us = build_us(conn)
        n_hk = build_hk(conn)
        conn.commit()
        print(f"✅ gold.macro_sectors_facts — US={n_us} sector rows · HK={n_hk} sector rows")
        return n_us + n_hk
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='macro_sectors',
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
