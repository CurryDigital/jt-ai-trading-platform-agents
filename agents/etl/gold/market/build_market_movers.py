#!/usr/bin/env python3
"""
build_market_movers.py
======================
Populates gold.market_movers_facts (created in db_setup/migrations/002).

Top 10 gainers + top 10 losers per region (US, HK), ranked by change_pct on
snapshot date. Computed from consumption.markets_stocks_overview and filtered
by liquidity so thin names and futures don't surface in the Command Center.

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


# Liquidity filters: must have meaningful current volume and be trading at
# least half its average volume (to avoid one-off spikes / stale prints).
MIN_VOLUME = 100_000
MIN_VOLUME_RATIO = 0.5

# Two-step: delete then insert. Keeps the operation atomic via the
# wrapping transaction.
DELETE_SQL = "DELETE FROM gold.market_movers_facts;"

INSERT_SQL = """
WITH candidates AS (
    SELECT
        market     AS region,
        ticker,
        change_pct,
        volume,
        avg_volume
    FROM   consumption.markets_stocks_overview
    WHERE  market IN ('US','HK')
      AND  asset_class IN ('EQUITY','ETF','STOCK')
      AND  change_pct IS NOT NULL
      AND  volume >= {min_volume}
      AND  (avg_volume IS NULL OR avg_volume = 0 OR volume::numeric / avg_volume >= {min_volume_ratio})
      AND  ticker NOT LIKE '%=F'          -- exclude futures contracts
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
""".format(min_volume=MIN_VOLUME, min_volume_ratio=MIN_VOLUME_RATIO)

# Expose region and restrict to top-3 per region/direction for the Command Center.
CREATE_OR_REPLACE_VIEW_SQL = """
CREATE OR REPLACE VIEW consumption.market_movers AS
SELECT region,
       direction,
       ticker,
       change_pct,
       rank,
       updated_at
FROM   gold.market_movers_facts
WHERE  rank <= 3
ORDER BY region, direction, rank;
"""



def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL)
            cur.execute(INSERT_SQL)
            n = cur.rowcount
            cur.execute(CREATE_OR_REPLACE_VIEW_SQL)
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
