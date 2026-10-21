#!/usr/bin/env python3
"""
backfill_news_clusters_daily.py — per-day historical story clusters (kanban
t_3955c4f6).

Reads:   silver.historical_news (one UTC calendar day at a time, scoped by
         category)
Writes:  consumption.news_clusters_daily (one row per story cluster per day)

Why a successor table (not consumption.news_clusters):
  The live table's PK is (window_hours, cluster_id) and cluster_id =
  sha1(cat|lower(canonical_headline))[:16]. Per-day historical builds reuse
  canonical headlines across days -> same cluster_id under one window_hours
  value -> PK collision. news_clusters_daily addresses rows by
  (window_date, cluster_id) instead:
    - a story continuing across days KEEPS the same cluster_id (same formula
      as the live table), which is what the News attention timeline needs to
      stitch multi-day stories;
    - each day is independently rebuildable (DELETE WHERE window_date = ...)
      with no risk to other days or to the live 48h rolling table.

Semantics / decisions (qr_etl):
  - window_date = UTC calendar day of the silver rows (date::date).
  - impact_score/impact_components are computed AS-OF the day end
    (reference now = window_date + 1 day), so recency/attention describe the
    story on that day, not today.
  - llm_* columns are left NULL on backfilled rows: consumption.news_outlook
    history does not cover the backfill range and joining today's outlook to
    a months-old cluster would be wrong. (extract_clusters.py may stamp
    recent days separately; the join key is the same cluster_id formula.)
  - sim_threshold is stored per row for provenance: the whole table is
    rebuilt when the user picks the final threshold (sweep companion task),
    and this column records which value produced each build.

Run:
  etl-news-venv/bin/python consumption/market/backfill_news_clusters_daily.py \
      [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--threshold 0.82] \
      [--rebuild] [--limit-days N] [--dry-run]

  Default range = full silver.historical_news span. Days already present in
  news_clusters_daily are SKIPPED unless --rebuild (resume-safe after a
  SIGTERM; each day commits independently).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import numpy as np  # noqa: E402
from db import get_connection  # noqa: E402

import build_news_clusters as bnc  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS consumption.news_clusters_daily (
    window_date        DATE         NOT NULL,
    cluster_id         VARCHAR(32)  NOT NULL,
    window_hours       INTEGER      NOT NULL DEFAULT 24,
    canonical_headline TEXT         NOT NULL,
    story_count        INTEGER      NOT NULL,
    outlet_count       INTEGER      NOT NULL,
    first_seen_utc     TIMESTAMP,
    last_seen_utc      TIMESTAMP,
    asset_class        VARCHAR(8)   NOT NULL,
    driver_tags        TEXT[]       NOT NULL DEFAULT '{}',
    tickers            TEXT[]       NOT NULL DEFAULT '{}',
    llm_direction      VARCHAR(10),
    llm_confidence     NUMERIC(4,3),
    llm_rationale      TEXT,
    impact_score       INTEGER      NOT NULL DEFAULT 0,
    impact_components  JSONB,
    members            JSONB        NOT NULL DEFAULT '[]',
    sim_threshold      NUMERIC(4,3) NOT NULL,
    computed_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (window_date, cluster_id)
);
CREATE INDEX IF NOT EXISTS news_clusters_daily_cid_idx
    ON consumption.news_clusters_daily (cluster_id);
CREATE INDEX IF NOT EXISTS news_clusters_daily_class_date_idx
    ON consumption.news_clusters_daily (asset_class, window_date);
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', type=date.fromisoformat, default=None,
                    help='first UTC day to build (default: silver min date)')
    ap.add_argument('--end', type=date.fromisoformat, default=None,
                    help='last UTC day to build, inclusive (default: silver max date)')
    ap.add_argument('--threshold', type=float, default=bnc.SIM_THRESHOLD)
    ap.add_argument('--rebuild', action='store_true',
                    help='rebuild days even if already present')
    ap.add_argument('--limit-days', type=int, default=None,
                    help='process at most N days (validation runs)')
    ap.add_argument('--dry-run', action='store_true',
                    help='cluster but roll back all writes')
    return ap.parse_args()


def fetch_day(cur, day: date):
    cur.execute(
        """SELECT id, date, category, entity_name, headline, source, lang, url
           FROM silver.historical_news
           WHERE category = ANY(%s)
             AND date >= %s AND date < %s + INTERVAL '1 day'
           ORDER BY date DESC, id DESC""",
        (bnc.ASSET_CLASSES, day, day))
    return cur.fetchall()


def preclean(rows):
    """Same contract as build_news_clusters.main step 1: strip '(copy)',
    drop url-less rows, drop exact title+outlet dupes."""
    items, seen = [], set()
    for rid, dt, cat, ent, head, src, lang, url in rows:
        norm = bnc.normalize_headline(head or '')
        if not norm or not url:
            continue
        outlet = (src or '').replace('gdelt:', '')
        key = (cat, norm.lower(), outlet.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append({'id': rid, 'dt': dt, 'cat': cat, 'entity': ent or '',
                      'headline': norm, 'outlet': outlet, 'lang': lang or None,
                      'url': url})
    return items


def embed_headlines(model, headlines: list) -> np.ndarray:
    """embed_all but with a caller-owned model instance (loaded once per
    process, not once per category per day)."""
    vecs = np.array(list(model.embed(headlines)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def build_day_records(items, model, threshold, ref_now, known_tickers):
    """Cluster one day's items and return row tuples for
    news_clusters_daily. ref_now is the as-of timestamp (day end) used for
    recency/attention impact components. llm_* stays NULL (see module doc)."""
    out_clusters = []
    for cat in bnc.ASSET_CLASSES:
        idxs = [i for i, it in enumerate(items) if it['cat'] == cat]
        if not idxs:
            continue
        vecs = embed_headlines(model,
                               [items[i]['headline'] for i in idxs])
        for cl in bnc.cluster_items([items[i] for i in idxs], vecs, threshold):
            out_clusters.append((cat, [idxs[i] for i in cl]))

    records = []
    canon_best = {}  # lower(canonical) -> records index; per-day dedupe
    for cat, member_idxs in out_clusters:
        members = [items[i] for i in member_idxs]
        canonical = min(members,
                        key=lambda m: (bnc.outlet_rank(m['outlet']), m['dt']))
        canon_norm = canonical['headline'].lower()
        first_seen = min(m['dt'] for m in members)
        last_seen = max(m['dt'] for m in members)
        outlets = sorted({m['outlet'] for m in members if m['outlet']})
        text_blob = ' '.join(m['headline'] for m in members)
        age_h = (ref_now - last_seen).total_seconds() / 3600.0 if last_seen else 999.0
        tickers = bnc.extract_tickers(members, known_tickers)
        cid = hashlib.sha1(f"{cat}|{canon_norm}".encode()).hexdigest()[:16]
        comp = bnc.impact_components(members, text_blob, age_h, None, ref_now)
        impact_score = sum(comp.values())
        members_json = [{'headline': m['headline'], 'outlet': m['outlet'],
                         'published_at': m['dt'].isoformat(), 'url': m['url'],
                         'lang': m['lang']}
                        for m in sorted(members, key=lambda m: m['dt'],
                                        reverse=True)]
        rec = (
            cid, canonical['headline'], len(members), len(outlets),
            first_seen, last_seen, cat, bnc.driver_tags(text_blob), tickers,
            None, None, None,
            impact_score, json.dumps(comp),
            json.dumps(members_json, ensure_ascii=False), threshold)
        prev_i = canon_best.get(canon_norm)
        if prev_i is None:
            canon_best[canon_norm] = len(records)
            records.append(rec)
        else:
            prev = records[prev_i]
            if (rec[2], rec[12]) > (prev[2], prev[12]):  # story_count, impact
                records[prev_i] = rec
    return records


INSERT_SQL = """
INSERT INTO consumption.news_clusters_daily
   (window_date, cluster_id, canonical_headline, story_count,
    outlet_count, first_seen_utc, last_seen_utc, asset_class,
    driver_tags, tickers, llm_direction, llm_confidence,
    llm_rationale, impact_score, impact_components, members,
    sim_threshold)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""


def main() -> int:
    args = parse_args()
    t0 = time.time()
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()  # DDL must survive the rollback fallback below
    with conn.cursor() as cur:
        cur.execute(
            """SELECT min(date)::date, max(date)::date
               FROM silver.historical_news WHERE category = ANY(%s)""",
            (bnc.ASSET_CLASSES,))
        silver_min, silver_max = cur.fetchone()
        start = args.start or silver_min
        end = args.end or silver_max
        if not args.rebuild:
            cur.execute(
                """SELECT window_date FROM consumption.news_clusters_daily
                   WHERE window_date BETWEEN %s AND %s""", (start, end))
            done = {r[0] for r in cur.fetchall()}
        else:
            done = set()
        cur.execute("SELECT DISTINCT ticker FROM gold.daily_ohlcv")
        known_tickers = {r[0] for r in cur.fetchall()}
        try:
            cur.execute("""SELECT DISTINCT ticker
                           FROM consumption.portfolio_positions_current
                           WHERE status = 'ACTIVE'""")
            known_tickers |= {r[0] for r in cur.fetchall()}
        except Exception:
            conn.rollback()

    days = []
    d = start
    while d <= end:
        if d not in done:
            days.append(d)
        d += timedelta(days=1)
    if args.limit_days:
        days = days[: args.limit_days]
    print(f'range {start}..{end}: {len(days)} days to build '
          f'({len(done)} already present), threshold={args.threshold}, '
          f'dry_run={args.dry_run}', flush=True)
    if not days:
        print('nothing to do', flush=True)
        conn.close()
        return 0

    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=bnc.EMBED_MODEL)

    total_clusters = 0
    for i, day in enumerate(days, 1):
        td = time.time()
        with conn.cursor() as cur:
            rows = fetch_day(cur, day)
        items = preclean(rows)
        if not items:
            print(f'[{i}/{len(days)}] {day}: 0 rows after pre-clean, skipped',
                  flush=True)
            continue
        ref_now = datetime.combine(day + timedelta(days=1), datetime.min.time())
        records = build_day_records(items, model, args.threshold, ref_now,
                                    known_tickers)
        n_singletons = sum(1 for r in records if r[2] == 1)
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM consumption.news_clusters_daily '
                'WHERE window_date = %s', (day,))
            cur.executemany(
                INSERT_SQL,
                [(day,) + r for r in records])
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
        total_clusters += len(records)
        print(f'[{i}/{len(days)}] {day}: {len(rows)} rows -> {len(items)} kept '
              f'-> {len(records)} clusters '
              f'({100.0 * n_singletons / max(len(records), 1):.1f}% singletons) '
              f'in {time.time() - td:.1f}s', flush=True)

    conn.close()
    dt = time.time() - t0
    print(f'{"DRY-RUN " if args.dry_run else ""}done: {total_clusters} clusters '
          f'across {len(days)} days in {dt:.0f}s '
          f'({dt / max(len(days), 1):.1f}s/day)', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
