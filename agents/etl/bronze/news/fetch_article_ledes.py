#!/usr/bin/env python3
"""
fetch_article_ledes.py — populate silver.historical_news.summary (kanban
t_2b413d87).

news_clusters embeddings were TITLE-ONLY because silver.historical_news had
no body/lede column. This script fills the new summary column from two
sources, cheapest first:

  1. JOIN backfill — silver.news_items.body (RSS summaries, already in the
     DB) copied onto historical_news rows sharing the same url. HTML is
     stripped; <= 4000 chars.
  2. LIVE FETCH — for remaining recent rows (GDELT path carries title+url
     only), GET the article and extract main text with trafilatura.
     Probed 2026-08-12: ~80% of sampled GDELT urls extract cleanly at
     ~0.4s per fetch.

Sentinel semantics on silver.historical_news.summary:
  NULL = not yet attempted (picked up on a later run)
  ''   = attempted, nothing extractable (paywall / bot-block / dead link)
         — never retried, so runs converge instead of re-hammering dead urls.

Bounded for the every-2h news_clusters_refresh.sh wrapper: --max-fetch caps
articles per run, --max-seconds stops starting new fetches after N seconds
(the run still exits 0; remaining NULL rows are picked up next tick).

Idempotent; safe to overlap with clean_news.py (different rows: it writes
summary only where currently NULL, we never overwrite non-NULL).

Run:  etl-venv/bin/python bronze/news/fetch_article_ledes.py
          [--hours 48] [--max-fetch 150] [--max-seconds 300] [--join-days 7]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import requests  # noqa: E402

from db import get_connection             # noqa: E402
from freshness import freshness_guard     # noqa: E402
from news_scopes import strip_html        # noqa: E402

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/126.0 Safari/537.36 '
                    'etl-news-lede/1.0'}
MAX_SUMMARY = 4000
MIN_SUMMARY = 100        # shorter extracts are boilerplate, mark as failed
FETCH_TIMEOUT = 15
SLEEP_S = 0.4


def join_backfill(conn, days: int) -> int:
    """Copy silver.news_items.body onto historical_news rows by url."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT h.id, n.body
               FROM silver.historical_news h
               JOIN silver.news_items n ON n.url = h.url
               WHERE h.summary IS NULL
                 AND h.date >= NOW() - INTERVAL '%s days'
                 AND n.body IS NOT NULL AND length(n.body) > 40""",
            (int(days),))
        pairs = cur.fetchall()
        done = 0
        for hid, body in pairs:
            plain = strip_html(body)[:MAX_SUMMARY]
            if len(plain) < 40:
                continue
            cur.execute(
                'UPDATE silver.historical_news SET summary = %s '
                'WHERE id = %s AND summary IS NULL',
                (plain, hid))
            done += cur.rowcount
    conn.commit()
    return done


def extract_lede(url: str) -> str | None:
    """GET url and extract main text. None = nothing usable."""
    import trafilatura  # deferred: heavy import, etl-venv only
    r = requests.get(url, headers=UA, timeout=FETCH_TIMEOUT)
    r.raise_for_status()
    txt = trafilatura.extract(r.text, include_comments=False,
                              include_tables=False)
    if not txt or len(txt) < MIN_SUMMARY:
        return None
    return txt[:MAX_SUMMARY]


def fetch_recent(args) -> tuple[int, int, int]:
    """Live-fetch recent NULL-summary rows. Returns (ok, failed, skipped)."""
    conn = get_connection()
    ok = failed = skipped = 0
    t0 = time.monotonic()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, url FROM silver.historical_news
                   WHERE summary IS NULL AND url IS NOT NULL
                     AND date >= NOW() - INTERVAL '%s hours'
                   ORDER BY date DESC, id DESC""",
                (int(args.hours),))
            rows = cur.fetchall()
        seen_urls: dict[str, str | None] = {}  # url -> summary ('' = failed)
        for hid, url in rows:
            if len(seen_urls) >= args.max_fetch and url not in seen_urls:
                skipped += 1
                continue
            if (args.max_seconds
                    and time.monotonic() - t0 > args.max_seconds):
                skipped += 1
                continue
            if url not in seen_urls:
                try:
                    seen_urls[url] = extract_lede(url) or ''
                except Exception:
                    seen_urls[url] = ''
                time.sleep(SLEEP_S)
            summary = seen_urls[url]
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE silver.historical_news SET summary = %s '
                    'WHERE id = %s AND summary IS NULL',
                    (summary, hid))
                if cur.rowcount:
                    ok += bool(summary)
                    failed += not summary
            conn.commit()
    finally:
        conn.close()
    return ok, failed, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=48,
                    help='trailing window for live-fetch candidates')
    ap.add_argument('--max-fetch', type=int, default=150,
                    help='max distinct urls to GET per run')
    ap.add_argument('--max-seconds', type=int, default=300,
                    help='stop starting new fetches after N seconds (0=off)')
    ap.add_argument('--join-days', type=int, default=7,
                    help='trailing window for the news_items join backfill')
    args = ap.parse_args()

    with freshness_guard(source='bronze:fetch_article_ledes'):
        conn = get_connection()
        try:
            joined = join_backfill(conn, args.join_days)
        finally:
            conn.close()
        print(f'✅ join backfill from silver.news_items: +{joined} summaries',
              flush=True)
        ok, failed, skipped = fetch_recent(args)
        print(f'✅ live fetch: +{ok} extracted, {failed} no-content '
              f'(marked empty), {skipped} deferred to next run', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
