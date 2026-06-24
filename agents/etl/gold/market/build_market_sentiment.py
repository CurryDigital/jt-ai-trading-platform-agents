#!/usr/bin/env python3
"""
build_market_sentiment.py
=========================
Populates gold.market_sentiment_facts (singleton — id=1) from
gold.vix_regime + computed VIX delta.

Output schema (single row):
    fear_greed, fear_greed_label, vix, vix_change_pct, put_call, updated_at

Sources today:
    vix             → gold.vix_regime.vix       (latest row)
    vix_change_pct  → derived from yesterday vs today close
    fear_greed      → DERIVED from VIX z-score band (placeholder until a
                      real F&G feed is wired):
                          VIX z >  1.5  → 'Extreme Fear'   (score 15)
                          VIX z >  0.5  → 'Fear'           (score 35)
                          VIX z > -0.5  → 'Neutral'        (score 50)
                          VIX z > -1.5  → 'Greed'          (score 70)
                          else          → 'Extreme Greed'  (score 85)
    put_call        → NULL until a real CBOE feed is wired.

The placeholder F&G is documented as such; replace the CASE in this file
once a real F&G ingest lands.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


SQL = """
WITH today AS (
    SELECT date, vix, vix_z60
    FROM   gold.vix_regime
    ORDER  BY date DESC
    LIMIT  1
),
yesterday AS (
    SELECT vix
    FROM   gold.vix_regime
    WHERE  date < (SELECT date FROM today)
    ORDER  BY date DESC
    LIMIT  1
),
calc AS (
    SELECT
        t.vix,
        CASE WHEN y.vix IS NULL OR y.vix = 0 THEN NULL
             ELSE (t.vix / y.vix - 1.0) * 100.0
        END AS vix_change_pct,
        t.vix_z60,
        CASE
            WHEN t.vix_z60 IS NULL          THEN 50
            WHEN t.vix_z60 >   1.5          THEN 15
            WHEN t.vix_z60 >   0.5          THEN 35
            WHEN t.vix_z60 >  -0.5          THEN 50
            WHEN t.vix_z60 >  -1.5          THEN 70
            ELSE                                 85
        END AS fear_greed,
        CASE
            WHEN t.vix_z60 IS NULL          THEN 'Neutral'
            WHEN t.vix_z60 >   1.5          THEN 'Extreme Fear'
            WHEN t.vix_z60 >   0.5          THEN 'Fear'
            WHEN t.vix_z60 >  -0.5          THEN 'Neutral'
            WHEN t.vix_z60 >  -1.5          THEN 'Greed'
            ELSE                                 'Extreme Greed'
        END AS fear_greed_label
    FROM today t
    LEFT JOIN yesterday y ON TRUE
)
INSERT INTO gold.market_sentiment_facts
    (id, fear_greed, fear_greed_label, vix, vix_change_pct, put_call, updated_at)
SELECT
    1, fear_greed, fear_greed_label, vix, ROUND(vix_change_pct::numeric, 4), NULL, NOW()
FROM calc
ON CONFLICT (id) DO UPDATE SET
    fear_greed       = EXCLUDED.fear_greed,
    fear_greed_label = EXCLUDED.fear_greed_label,
    vix              = EXCLUDED.vix,
    vix_change_pct   = EXCLUDED.vix_change_pct,
    -- put_call deliberately not overwritten — a real feed can fill it independently.
    updated_at       = EXCLUDED.updated_at;
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.market_sentiment_facts — {n} row upserted (singleton id=1)")
        return n
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='market_sentiment',
                asset_class='macro',
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
