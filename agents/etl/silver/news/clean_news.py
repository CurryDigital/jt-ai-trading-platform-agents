#!/usr/bin/env python3
"""
clean_news.py — silver layer for pipeline C.

Reads bronze.raw_news over a trailing window (default 3 days — catches late
arrivals on re-runs), normalizes, dedupes (url_hash = canonical url, else
normalized headline), tags scopes via the entity dictionary
(shared/news_scopes.py), and upserts into silver.news_items.

Also upserts into silver.historical_news (kanban t_ffff7242): that archive
table feeds consumption.news_clusters and was previously written ONLY by the
GDELT backfill script — a single throttled external API. When GDELT has this
box in the 429 penalty box, silver.historical_news (and therefore the News
clusters API) goes stale even though RSS ingest is unaffected. The RSS path
now lands in historical_news too, so clusters stay fresh through GDELT
outages. Idempotent via the (date, entity_name, headline) unique key.

Items whose scope tagging comes back EMPTY (no dictionary hit) are still
written with the feed's scope hint when present; items with no scopes at all
are skipped and counted — they cannot feed gold.news_sentiment_daily.

Cron: pipeline C wrapper, after ingest_news.py.
Standalone: python agents/etl/silver/news/clean_news.py [--days 3]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection            # noqa: E402
from freshness import freshness_guard    # noqa: E402
from news_scopes import (                # noqa: E402
    SCOPES, extract_entity, headline_hash, normalize_lang, strip_html,
    tag_scopes, url_hash,
)

SELECT_SQL = """
SELECT date, category, entity_name, headline, source, raw_content
FROM bronze.raw_news
WHERE date >= NOW() - INTERVAL '%s days'
"""

UPSERT_SQL = """
INSERT INTO silver.news_items
    (published_at, date, scopes, entity_name, headline, body, source, url,
     url_hash, headline_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (url_hash) DO NOTHING;
"""

# RSS/feed path also lands in the archive table that feeds news_clusters
# (t_ffff7242). Category = the scope the row belongs to; prefer the feed
# hint when it is a valid scope, else the first tagged scope.
# summary (t_2b413d87): plain-text RSS lede, so cluster embeddings can use
# title + first ~200 words. COALESCE keeps an existing summary (e.g. a
# fetched full body from fetch_article_ledes.py) over the RSS lede.
HIST_SQL = """
INSERT INTO silver.historical_news (date, category, entity_name, headline, source, lang, url, summary)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (date, entity_name, headline) DO UPDATE SET
    url = COALESCE(EXCLUDED.url, silver.historical_news.url),
    summary = COALESCE(silver.historical_news.summary, EXCLUDED.summary);
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=3)
    args = ap.parse_args()

    with freshness_guard(source='silver:clean_news'):
        conn = get_connection()
        scanned = inserted = skipped_unscoped = dupes = hist = 0
        try:
            with conn.cursor() as cur:
                cur.execute(SELECT_SQL % int(args.days))
                rows = cur.fetchall()
                for (date, category, entity, headline, source, raw) in rows:
                    scanned += 1
                    url = body = hint = None
                    if raw:
                        try:
                            payload = json.loads(raw)
                            url = payload.get('url')
                            body = payload.get('summary') or None
                            hint = payload.get('feed_scope') or category
                        except (ValueError, AttributeError):
                            hint = category
                    scopes = tag_scopes(headline, body, hint=hint)
                    if not scopes:
                        skipped_unscoped += 1
                        continue
                    ent = entity or extract_entity(headline, body)
                    cur.execute(UPSERT_SQL, (
                        date, date.date() if hasattr(date, 'date') else date,
                        scopes, ent,
                        headline, body, source, url,
                        url_hash(url, headline), headline_hash(headline),
                    ))
                    if cur.rowcount:
                        inserted += 1
                    else:
                        dupes += 1
                    hist_scope = (hint if hint in SCOPES
                                  else (scopes[0] if scopes else None))
                    if hist_scope:
                        summary = strip_html(body)[:4000] or None
                        cur.execute(HIST_SQL, (
                            date, hist_scope, (ent or '')[:100],
                            headline[:2000], source,
                            normalize_lang(None, headline), url, summary))
                        hist += cur.rowcount
            conn.commit()
        finally:
            conn.close()

        print(f'✅ silver.news_items — +{inserted} (scanned={scanned}, '
              f'dupes={dupes}, skipped_unscoped={skipped_unscoped})')
        print(f'✅ silver.historical_news — +{hist} (rss/feed path)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
