#!/usr/bin/env python3
"""
build_market_movers.py
======================
Populates gold.market_movers_facts (created in db_setup/migrations/002).

Top 10 gainers + top 10 losers per region (US, HK), ranked by returns_1d on
the latest trading date. Computed from gold.daily_ohlcv + gold.asset_registry.

Output schema (one row per region × direction × rank, max 40 rows):
    region, direction ∈ {gainer,loser}, ticker, change_pct, rank, updated_at

Refresh contract: truncate-region-then-insert so stale tickers don't linger
in the top-N list.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


# Two-step: delete then insert. Keeps the operation atomic via the
# wrapping transaction.
DELETE_SQL = "DELETE FROM gold.market_movers_facts;"

INSERT_SQL = """
WITH latest_date AS (
    SELECT MAX(date) AS d FROM gold.daily_ohlcv
),
candidates AS (
    SELECT
        ar.market   AS region,
        o.ticker,
        o.returns_1d * 100.0 AS change_pct
    FROM   gold.daily_ohlcv o
    JOIN   gold.asset_registry ar ON ar.ticker = o.ticker AND ar.is_active = TRUE
    WHERE  o.date = (SELECT d FROM latest_date)
      AND  ar.market IN ('US','HK')
      AND  ar.asset_class IN ('EQUITY','ETF','STOCK')
      AND  o.returns_1d IS NOT NULL
),
ranked_gainers AS (
    SELECT
        region,
        'gainer'::VARCHAR    AS direction,
        ticker,
        change_pct,
        ROW_NUMBER() OVER (PARTITION BY region ORDER BY change_pct DESC) AS rank
    FROM candidates
),
ranked_losers AS (
    SELECT
        region,
        'loser'::VARCHAR     AS direction,
        ticker,
        change_pct,
        ROW_NUMBER() OVER (PARTITION BY region ORDER BY change_pct ASC) AS rank
    FROM candidates
)
INSERT INTO gold.market_movers_facts
    (region, direction, ticker, change_pct, rank, updated_at)
SELECT region, direction, ticker, ROUND(change_pct::numeric, 4), rank::INTEGER, NOW()
FROM (
    SELECT * FROM ranked_gainers WHERE rank <= 10
    UNION ALL
    SELECT * FROM ranked_losers  WHERE rank <= 10
) t
ORDER BY region, direction, rank;
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL)
            cur.execute(INSERT_SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.market_movers_facts — {n} mover rows inserted")
        return n
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='market_movers',
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
