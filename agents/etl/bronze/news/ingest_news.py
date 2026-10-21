#!/usr/bin/env python3
"""
ingest_news.py — bronze-layer news ingest for pipeline C.

Sources (2026-08-07 source audit — FMP news endpoints are NOT available under
the current subscription, both legacy v3/v4 and new /stable/ return
"Restricted Endpoint"; so this pipeline is RSS + GDELT only):

  Per-scope RSS feeds (free, no key)  -> bronze.raw_news
  GDELT DOC 2.0 API last-24h per scope -> bronze.raw_news (source='gdelt:<domain>')

bronze.raw_news is an append-only raw tier; intra-run and cross-run dupes are
suppressed with a (date, source, headline) NOT EXISTS guard, full dedupe
happens in silver/news/clean_news.py via url_hash.

Cron: pipeline C wrapper (scripts/pipeline_c_news.sh) 08:45 UTC Mon-Fri.
Standalone: python agents/etl/bronze/news/ingest_news.py [--skip-gdelt]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import feedparser  # noqa: E402  (installed in etl-venv 2026-08-07)
import requests    # noqa: E402

from db import get_connection                              # noqa: E402
from freshness import freshness_guard                      # noqa: E402
from news_scopes import SCOPES                             # noqa: E402

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) etl-news/1.0'}

# --- RSS feed registry (primary scope hint -> feeds) -------------------------
RSS_FEEDS = {
    'US': [
        ('CNBC Top',       'https://www.cnbc.com/id/100003114/device/rss/rss.html'),
        ('CNBC Economy',   'https://www.cnbc.com/id/20910258/device/rss/rss.html'),
        ('MarketWatch',    'https://feeds.marketwatch.com/marketwatch/topstories/'),
        ('MarketWatch MP', 'https://feeds.marketwatch.com/marketwatch/marketpulse/'),
        ('Yahoo Finance',  'https://finance.yahoo.com/news/rssindex'),
        ('Fed Press',      'https://www.federalreserve.gov/feeds/press_all.xml'),
        ('Investing.com',  'https://www.investing.com/rss/news_1.rss'),
    ],
    'HK': [
        ('SCMP Business',  'https://www.scmp.com/rss/92/feed'),
        ('SCMP Markets',   'https://www.scmp.com/rss/318198/feed'),
        ('HongKongFP',     'https://hongkongfp.com/feed/'),
    ],
    'CRYPTO': [
        ('CoinDesk',       'https://www.coindesk.com/arc/outboundfeeds/rss/'),
        ('CoinTelegraph',  'https://cointelegraph.com/rss'),
        ('The Block',      'https://www.theblock.co/rss.xml'),
    ],
    # FXStreet / DailyFX are Cloudflare/Akamai-walled (HTML, not XML) — dropped
    # 2026-08-07 after live probe; replacements below verified working.
    'FX': [
        ('ForexLive',      'https://www.forexlive.com/feed/'),
        ('Investing.com FX', 'https://www.investing.com/rss/news_25.rss'),
    ],
    # Kitco has no public RSS (HTML at every probed path); goldsilver.com is
    # Cloudflare-walled. Mining.com + Investing.com commodities verified.
    'METAL': [
        ('Mining.com',     'https://www.mining.com/feed/'),
        ('Investing.com Metals', 'https://www.investing.com/rss/news_11.rss'),
    ],
}

# --- GDELT last-24h queries per scope ---------------------------------------
GDELT_QUERIES = {
    'US':     '("federal reserve" OR "wall street" OR "S&P 500")',
    'HK':     '("hang seng" OR "hong kong stocks" OR HKEX)',
    'CRYPTO': '(bitcoin OR ethereum OR cryptocurrency)',
    'FX':     '(forex OR "currency market" OR "dollar index")',
    'METAL':  '("gold price" OR gold OR bullion OR "precious metals")',
}
GDELT_URL = 'https://api.gdeltproject.org/api/v2/doc/doc'
# Published limit is 1 req / 5s, but observed 429s at 6s spacing (shared-IP
# throttling). 15s spacing + up to 3 retries with 30s backoff is reliable.
GDELT_SLEEP_S = 20
GDELT_RETRIES = 4
GDELT_BACKOFF_S = 60


INSERT_SQL = """
INSERT INTO bronze.raw_news (date, category, entity_name, headline, source, raw_content)
SELECT %s, %s, %s, %s, %s, %s
WHERE NOT EXISTS (
    SELECT 1 FROM bronze.raw_news b
    WHERE b.date::date = %s AND b.source = %s AND b.headline = %s
);
"""


def _to_utc(ts_struct) -> datetime:
    if ts_struct:
        return datetime(*ts_struct[:6], tzinfo=timezone.utc).replace(tzinfo=None)
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fetch_rss(cur) -> tuple[int, list[str]]:
    inserted, problems = 0, []
    for scope in SCOPES:
        for name, url in RSS_FEEDS.get(scope, []):
            try:
                feed = feedparser.parse(url, request_headers=UA)
                if feed.bozo and not feed.entries:
                    problems.append(f'{name}: bozo {feed.bozo_exception}')
                    continue
                n = 0
                for e in feed.entries[:60]:
                    headline = (e.get('title') or '').strip()
                    if not headline:
                        continue
                    published = _to_utc(e.get('published_parsed') or e.get('updated_parsed'))
                    payload = json.dumps({
                        'url': e.get('link'),
                        'summary': (e.get('summary') or '')[:4000],
                        'feed_scope': scope,
                    })
                    cur.execute(INSERT_SQL, (
                        published, scope, None, headline[:2000], name[:100], payload,
                        published.date(), name[:100], headline[:2000],
                    ))
                    n += cur.rowcount
                inserted += n
                print(f'  RSS {name:<22} scope={scope:<7} +{n}')
            except Exception as exc:
                problems.append(f'{name}: {exc}')
    return inserted, problems


def fetch_gdelt(cur) -> tuple[int, list[str]]:
    inserted, problems = 0, []
    for i, scope in enumerate(SCOPES):
        if i:
            time.sleep(GDELT_SLEEP_S)
        data = None
        for attempt in range(GDELT_RETRIES):
            try:
                r = requests.get(GDELT_URL, params={
                    'query': GDELT_QUERIES[scope],
                    'mode': 'artlist',
                    'maxrecords': 250,
                    'format': 'json',
                    'timespan': '1d',
                    'sort': 'hybridrel',
                }, headers=UA, timeout=40)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as exc:
                if attempt == GDELT_RETRIES - 1:
                    problems.append(f'gdelt/{scope}: {exc}')
                else:
                    time.sleep(GDELT_BACKOFF_S)
        if data is None:
            continue
        try:
            arts = data.get('articles') or []
            n = 0
            for a in arts:
                headline = (a.get('title') or '').strip()
                if not headline:
                    continue
                try:
                    published = datetime.strptime(a.get('seendate', ''), '%Y%m%dT%H%M%SZ')
                except ValueError:
                    published = datetime.now(timezone.utc).replace(tzinfo=None)
                domain = (a.get('domain') or 'gdelt')[:80]
                payload = json.dumps({
                    'url': a.get('url'),
                    'summary': '',
                    'feed_scope': scope,
                    'sourcecountry': a.get('sourcecountry'),
                    'language': a.get('language'),
                })
                cur.execute(INSERT_SQL, (
                    published, scope, None, headline[:2000], f'gdelt:{domain}'[:100], payload,
                    published.date(), f'gdelt:{domain}'[:100], headline[:2000],
                ))
                n += cur.rowcount
            inserted += n
            print(f'  GDELT scope={scope:<7} +{n} (of {len(arts)})')
        except Exception as exc:
            problems.append(f'gdelt/{scope}: {exc}')
    return inserted, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-gdelt', action='store_true')
    args = ap.parse_args()

    with freshness_guard(source='bronze:ingest_news'):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                rss_n, rss_problems = fetch_rss(cur)
                gdel_n, gdel_problems = ([0, []] if args.skip_gdelt
                                         else fetch_gdelt(cur))
            conn.commit()
        finally:
            conn.close()

        total = rss_n + gdel_n
        print(f'✅ bronze.raw_news — {total} new rows (rss={rss_n}, gdelt={gdel_n})')
        for p in rss_problems + gdel_problems:
            print(f'  ⚠️  {p}')
        # Partial source failures are acceptable (RSS churn) — only hard-fail
        # when EVERYTHING failed.
        if total == 0 and (rss_problems or gdel_problems):
            raise RuntimeError(f'all news sources failed: {rss_problems + gdel_problems}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
