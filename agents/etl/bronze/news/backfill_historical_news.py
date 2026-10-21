#!/usr/bin/env python3
"""
backfill_historical_news.py — historical news backfill for pipeline C.

Target per the Phase 0 spec: 24 months per scope into silver.historical_news.
Depth reality (re-verified live 2026-08-07, superseding the earlier '~3 month'
claim): the GDELT DOC 2.0 API serves >= 18 months — weekly windows 7mo and
18mo back both returned full 250-article pages. The script therefore:

  1. PROBES depth first: weekly windows at 18/15/12/9/6/4 months back
     (probes deeper than --months are skipped). The effective start is the
     deepest probe that returned articles. A probe that returns an empty
     article list marks the serving cap; a probe whose REQUEST fails (429
     throttle etc.) is inconclusive and never lowers the cap — if no probe
     succeeds but failures occurred, the requested depth is kept (out-of-range
     windows return empty cheaply and are ledgered with 0 articles).
  2. Iterates WEEKLY windows per scope (GDELT artlist caps at 250 records per
     query — heavy news weeks get truncated; documented in
     agents/etl/docs/news_pipeline_c_sources.md).
  3. Writes BOTH targets:
       silver.historical_news (date, category=scope, entity_name, headline,
                               source) — the spec's archive table
       silver.news_items      — so gold scoring can produce historical
                                gold.news_sentiment_daily for Phase 2 training
     Both writes are idempotent (unique constraints / url_hash), so the script
     is re-runnable and resumable: just start it again.

Rate limiting: GDELT publishes 1 req / 5s but 429s appear at <10s spacing from
this box (shared-IP throttle). 15s spacing; on 429 back off 120s x up to 5
tries, then record the window as failed and continue.

Usage:
  python bronze/news/backfill_historical_news.py [--months 3] [--scope US] [--force]
                                                 [--no-probe] [--max-seconds N]
                                                 [--retries N] [--max-consec-fail N]
                                                 [--recent-hours H]

Recent mode (--recent-hours H, kanban t_ffff7242): fetches just the trailing
H hours per scope (one GDELT call per scope, no ledger interaction) and
upserts into silver.historical_news / silver.news_items. This is the ONGOING
freshness path: the weekly-window ledger marks a completed window as done
forever, so once the every-2h chunk runner was retired (acceptance of
t_e8e6fe4c) nothing re-fetched the current week and silver.historical_news
went stale within a day. Wire this mode into the every-2h
news_clusters_refresh.sh so clusters always have fresh input. Idempotent;
safe to overlap with ledgered weekly windows.

Resume ledger: completed windows are recorded in
silver.news_backfill_windows(scope, window_start) and skipped on re-run, so
mop-up runs only re-fetch FAILED windows. --force ignores the ledger.

Chunked mode (news_backfill_once.sh recurring cron): --no-probe skips the
depth probe entirely (under GDELT throttle the deep probes 429 out and the
cap silently collapses to the deepest SERVED probe — 6mo — even though the
serving depth verified manually is >=18mo; out-of-range windows return cheap
empties and are ledgered with 0 articles). --max-seconds bounds the run so it
always exits before the cron script timeout; the ledger resumes on the next
tick. --max-consec-fail stops early when GDELT has this box in the penalty
box (consecutive permanent window failures), avoiding deeper throttling.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import requests  # noqa: E402

from db import get_connection             # noqa: E402
from news_scopes import (                 # noqa: E402
    SCOPES, extract_entity, headline_hash, normalize_lang, tag_scopes,
    url_hash,
)

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) etl-news-backfill/1.0'}
GDELT_URL = 'https://api.gdeltproject.org/api/v2/doc/doc'
SLEEP_S = 15
RETRIES = 5
BACKOFF_S = 120

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS silver.news_backfill_windows (
    scope        VARCHAR(8)  NOT NULL,
    window_start DATE        NOT NULL,
    articles     INTEGER,
    finished_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scope, window_start)
);
"""

# Broader queries than the daily ingest — volume matters for training data.
QUERIES = {
    'US':     '("federal reserve" OR "wall street" OR "S&P 500" OR nasdaq OR "stock market")',
    'HK':     '("hang seng" OR "hong kong stocks" OR HKEX OR "hong kong market")',
    'CRYPTO': '(bitcoin OR ethereum OR cryptocurrency OR crypto)',
    'FX':     '(forex OR "dollar index" OR "currency markets" OR euro OR yen)',
    'METAL':  '(gold OR silver OR bullion OR "precious metals" OR copper)',
}

HIST_SQL = """
INSERT INTO silver.historical_news (date, category, entity_name, headline, source, lang, url)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (date, entity_name, headline) DO UPDATE SET url = COALESCE(EXCLUDED.url, silver.historical_news.url);
"""

ITEMS_SQL = """
INSERT INTO silver.news_items
    (published_at, date, scopes, entity_name, headline, body, source, url,
     url_hash, headline_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (url_hash) DO NOTHING;
"""


def gdelt_window(query: str, start: datetime, end: datetime,
                 retries: int = RETRIES,
                 timespan: str | None = None) -> list[dict] | None:
    """One GDELT artlist call with retry. None = window failed permanently.

    timespan (e.g. '34h') uses GDELT's relative-window param instead of
    explicit start/enddatetime. Observed 2026-08-12 (t_ffff7242): during a
    shared-IP 429 stretch, start/enddatetime URLs kept getting 429 while a
    timespan URL to the same endpoint returned 200 — the throttle meters
    per-URL-pattern, so recent mode prefers timespan.
    """
    params = {
        'query': query,
        'mode': 'artlist',
        'maxrecords': 250,
        'format': 'json',
        'sort': 'hybridrel',
    }
    if timespan:
        params['timespan'] = timespan
    else:
        params['startdatetime'] = start.strftime('%Y%m%d%H%M%S')
        params['enddatetime'] = end.strftime('%Y%m%d%H%M%S')
    for attempt in range(retries):
        try:
            r = requests.get(GDELT_URL, params=params,
                             headers=UA, timeout=60)
            r.raise_for_status()
            return r.json().get('articles') or []
        except Exception as exc:
            print(f'    attempt {attempt + 1}/{retries} failed: {exc}',
                  flush=True)
            if attempt < retries - 1:
                time.sleep(BACKOFF_S)
    return None


def probe_depth(query: str, today: datetime,
                requested_months: int = 6) -> datetime | None:
    """Return the effective earliest date GDELT will serve for this query.

    Probes weekly windows at 18/15/12/9/6/4 months back (skipping depths
    beyond the requested --months). Empty article list => serving cap;
    request failure (429/throttle) => inconclusive, never lowers the cap.
    """
    served: list[int] = []
    failed = 0
    for months_back in (18, 15, 12, 9, 6, 4):
        if months_back > max(requested_months, 6):
            continue
        end = today - timedelta(days=30 * months_back)
        start = end - timedelta(days=7)
        arts = gdelt_window(query, start, end)
        time.sleep(SLEEP_S)
        if arts is None:
            failed += 1
            print(f'    depth probe: {months_back}mo window REQUEST FAILED '
                  f'(inconclusive)', flush=True)
            continue
        if arts:
            served.append(months_back)
            continue
        print(f'    depth probe: {months_back}mo window EMPTY', flush=True)
    if served:
        return today - timedelta(days=30 * max(served))
    if failed:
        # probes inconclusive (throttled) — keep requested depth; out-of-range
        # windows are cheap empties
        return None
    # every probe genuinely empty: conservative 3-month floor
    return today - timedelta(days=30 * 3)


def run_recent(args) -> int:
    """Recent mode: trailing --recent-hours per scope, no ledger.

    One GDELT call per scope; idempotent upserts make overlap with ledgered
    weekly windows harmless. Returns 0 even on partial failure (callers treat
    this as best-effort freshness); prints per-scope results for the log.
    """
    scopes = list(SCOPES) if args.scope == 'ALL' else [args.scope]
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(hours=args.recent_hours)
    t0 = time.monotonic()
    conn = get_connection()
    total_hist = total_items = 0
    consec_fail = 0
    failed_scopes: list[str] = []
    try:
        for scope in scopes:
            if args.max_seconds and time.monotonic() - t0 > args.max_seconds:
                print(f'⏸️  stopped early: time budget {args.max_seconds}s '
                      f'exhausted', flush=True)
                break
            if (args.max_consec_fail
                    and consec_fail >= args.max_consec_fail):
                print(f'⏸️  stopped early: {consec_fail} consecutive scope '
                      f'failures (GDELT penalty box) — cooling down',
                      flush=True)
                break
            arts = gdelt_window(QUERIES[scope], start, end,
                                retries=args.retries,
                                timespan=f'{args.recent_hours}h')
            if arts is None:
                consec_fail += 1
                failed_scopes.append(scope)
                print(f'[{scope}] recent {args.recent_hours}h FAILED',
                      flush=True)
                continue
            consec_fail = 0
            h = it = 0
            with conn.cursor() as cur:
                for a in arts:
                    headline = (a.get('title') or '').strip()
                    if not headline:
                        continue
                    try:
                        pub = datetime.strptime(
                            a.get('seendate', ''), '%Y%m%dT%H%M%SZ')
                    except ValueError:
                        continue
                    domain = (a.get('domain') or 'gdelt')[:80]
                    source = f'gdelt:{domain}'[:100]
                    entity = extract_entity(headline) or ''
                    cur.execute(HIST_SQL, (
                        pub, scope, entity[:100], headline[:2000],
                        source,
                        normalize_lang(a.get('language'), headline),
                        a.get('url')))
                    h += cur.rowcount
                    cur.execute(ITEMS_SQL, (
                        pub, pub.date(),
                        tag_scopes(headline, None, hint=scope),
                        entity[:100] or None, headline[:2000], None,
                        source, a.get('url'),
                        url_hash(a.get('url'), headline),
                        headline_hash(headline)))
                    it += cur.rowcount
            conn.commit()
            total_hist += h
            total_items += it
            print(f'[{scope}] recent {args.recent_hours}h '
                  f'articles={len(arts)} hist+{h} items+{it}', flush=True)
            time.sleep(SLEEP_S)
    finally:
        conn.close()
    print(f'\n✅ recent refresh done: silver.historical_news +{total_hist}, '
          f'silver.news_items +{total_items} '
          f'(window={args.recent_hours}h, scopes={len(scopes)})')
    if failed_scopes:
        print(f'⚠️  failed scopes ({len(failed_scopes)}): '
              f'{", ".join(failed_scopes)}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--months', type=int, default=3,
                    help='requested history depth (GDELT serving cap applies)')
    ap.add_argument('--scope', choices=list(SCOPES) + ['ALL'], default='ALL')
    ap.add_argument('--force', action='store_true',
                    help='ignore the completed-window ledger')
    ap.add_argument('--no-probe', action='store_true',
                    help='skip depth probing; trust --months (throttle-safe)')
    ap.add_argument('--max-seconds', type=int, default=0,
                    help='stop starting new windows after N seconds '
                         '(0 = unbounded); run still exits 0')
    ap.add_argument('--retries', type=int, default=RETRIES,
                    help='per-window GDELT attempts (default 5)')
    ap.add_argument('--max-consec-fail', type=int, default=0,
                    help='stop the run after N consecutive failed windows '
                         '(0 = disabled)')
    ap.add_argument('--recent-hours', type=int, default=0,
                    help='recent mode: fetch only the trailing H hours per '
                         'scope (one GDELT call per scope, no ledger); '
                         'ongoing freshness path for news_clusters')
    args = ap.parse_args()

    if args.recent_hours:
        return run_recent(args)

    scopes = list(SCOPES) if args.scope == 'ALL' else [args.scope]
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    requested_start = today - timedelta(days=30 * args.months)
    t0 = time.monotonic()

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(LEDGER_DDL)
    conn.commit()
    total_hist = total_items = 0
    failed_windows: list[str] = []
    skipped = 0
    consec_fail = 0
    stop_reason = None
    try:
        for scope in scopes:
            if stop_reason:
                break
            if args.no_probe:
                eff_start = requested_start
                print(f'[{scope}] probe skipped; effective start '
                      f'{eff_start.date()} (requested --months {args.months})',
                      flush=True)
            else:
                print(f'[{scope}] probing archive depth...', flush=True)
                probed_start = probe_depth(QUERIES[scope], today, args.months)
                eff_start = max(requested_start,
                                probed_start or requested_start)
                print(f'[{scope}] effective start {eff_start.date()} '
                      f'(requested {requested_start.date()}, probe cap '
                      f'{(probed_start or requested_start).date()})',
                      flush=True)

            w_end = today
            while w_end > eff_start:
                if args.max_seconds and time.monotonic() - t0 > args.max_seconds:
                    stop_reason = f'time budget {args.max_seconds}s exhausted'
                    break
                if (args.max_consec_fail
                        and consec_fail >= args.max_consec_fail):
                    stop_reason = (f'{consec_fail} consecutive window failures '
                                   f'(GDELT penalty box) — cooling down')
                    break
                w_start = max(w_end - timedelta(days=7), eff_start)
                if not args.force:
                    with conn.cursor() as cur:
                        cur.execute(
                            'SELECT 1 FROM silver.news_backfill_windows '
                            'WHERE scope=%s AND window_start=%s',
                            (scope, w_start.date()))
                        if cur.fetchone():
                            skipped += 1
                            w_end = w_start
                            continue
                arts = gdelt_window(QUERIES[scope], w_start, w_end,
                                    retries=args.retries)
                if arts is None:
                    consec_fail += 1
                    failed_windows.append(f'{scope} {w_start.date()}..{w_end.date()}')
                    print(f'[{scope}] {w_start.date()}..{w_end.date()} FAILED',
                          flush=True)
                else:
                    consec_fail = 0
                    h = it = 0
                    with conn.cursor() as cur:
                        for a in arts:
                            headline = (a.get('title') or '').strip()
                            if not headline:
                                continue
                            try:
                                pub = datetime.strptime(
                                    a.get('seendate', ''), '%Y%m%dT%H%M%SZ')
                            except ValueError:
                                continue
                            domain = (a.get('domain') or 'gdelt')[:80]
                            source = f'gdelt:{domain}'[:100]
                            entity = extract_entity(headline) or ''
                            cur.execute(HIST_SQL, (
                                pub, scope, entity[:100], headline[:2000],
                                source,
                                normalize_lang(a.get('language'), headline),
                                a.get('url')))
                            h += cur.rowcount
                            cur.execute(ITEMS_SQL, (
                                pub, pub.date(),
                                tag_scopes(headline, None, hint=scope),
                                entity[:100] or None, headline[:2000], None,
                                source, a.get('url'),
                                url_hash(a.get('url'), headline),
                                headline_hash(headline)))
                            it += cur.rowcount
                    conn.commit()
                    total_hist += h
                    total_items += it
                    with conn.cursor() as cur:
                        cur.execute(
                            'INSERT INTO silver.news_backfill_windows '
                            '(scope, window_start, articles) VALUES (%s, %s, %s) '
                            'ON CONFLICT (scope, window_start) DO NOTHING',
                            (scope, w_start.date(), len(arts)))
                    conn.commit()
                    print(f'[{scope}] {w_start.date()}..{w_end.date()} '
                          f'articles={len(arts)} hist+{h} items+{it}', flush=True)
                w_end = w_start
                if w_end > eff_start:
                    time.sleep(SLEEP_S)
    finally:
        conn.close()

    print(f'\n✅ backfill done: silver.historical_news +{total_hist}, '
          f'silver.news_items +{total_items}, windows_skipped={skipped}')
    if stop_reason:
        print(f'⏸️  stopped early: {stop_reason} (ledger resumes next run)')
    if failed_windows:
        print(f'⚠️  failed windows ({len(failed_windows)}):')
        for w in failed_windows:
            print(f'   - {w}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
