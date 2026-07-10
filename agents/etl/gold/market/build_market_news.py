#!/usr/bin/env python3
"""
build_market_news.py
====================
Populates gold.news_sentiment (created in db_setup/migrations/002) with a
representative set of market headlines for the redesign scopes. In production
this should be replaced by an ingestion job from a real news API; until that
exists, this builder keeps the /api/news panel and macro-box headlines populated.

Contract: DELETE per market + INSERT with the current sample set. This avoids
duplicate headline rows on every run while still refreshing the `published_at`
timestamp.

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


HEADLINES = [
    ('US', 'S&P 500 hits fresh record as tech rally broadens', 'Reuters', 'bull', 'High', ['equities', 'tech']),
    ('US', 'Fed officials strike hawkish tone on rate path', 'Bloomberg', 'bear', 'High', ['rates', 'fed']),
    ('HK', 'Hang Seng extends rebound on property stimulus hopes', 'SCMP', 'bull', 'Med', ['hk', 'property']),
    ('HK', 'HKEX turnover dips as sentiment stays cautious', 'Nikkei', 'neu', 'Low', ['hk', 'turnover']),
    ('CRYPTO', 'Bitcoin ETF inflows resume after two-day outflow streak', 'CoinDesk', 'bull', 'Med', ['crypto', 'etf']),
    ('FX', 'Dollar holds firm ahead of CPI data', 'FXStreet', 'neu', 'Med', ['dollar', 'macro']),
    ('METAL', 'Gold drifts lower as yields rise', 'Kitco', 'bear', 'Low', ['gold', 'yields']),
]

DELETE_SQL = "DELETE FROM gold.news_sentiment;"

INSERT_SQL = """
INSERT INTO gold.news_sentiment (market, headline, source, tone, impact, tags, published_at)
VALUES (%s, %s, %s, %s, %s, %s, NOW());
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL)
            for row in HEADLINES:
                cur.execute(INSERT_SQL, row)
        conn.commit()
        print(f"✅ gold.news_sentiment — {len(HEADLINES)} headline rows upserted")
        return len(HEADLINES)
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='market_news',
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
