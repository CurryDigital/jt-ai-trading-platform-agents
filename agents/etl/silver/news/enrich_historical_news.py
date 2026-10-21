#!/usr/bin/env python3
"""Production enrichment runner for silver.historical_news (kanban t_9be92903,
handoff from qr_research t_f7f1c624).

Reads silver.historical_news (+ risk_hits from silver.news_items via
date/headline join), computes the full enrichment set with scorer
`lexicon-finvader1-lm1`, and writes a staging CSV keyed on historical_news.id.

qr_etl adaptations vs the research original:
  - DB access via shared/scripts/db.py (DB_* env from env/etl.env, direct RDS,
    sslmode=require) instead of the research SSH tunnel on 127.0.0.1:5433.
  - TickerExtractor.from_db() (gold.asset_registry live) instead of the CSV
    snapshot, so registry additions are picked up automatically.
  - --apply: load the staging CSV and apply it in ONE transaction (temp table
    + COPY + UPDATE, mirrors enrichment/apply_backfill.sql, idempotent on id).
  - --dedupe: run the canonical pure-SQL dedupe recompute
    (enrichment/dedupe.sql) after apply. Incremental runs only dedupe within
    batch, so the daily hook always passes --dedupe to keep dup_group_id
    canonical cross-batch (SQL md5 gid is the canonical producer).

Label rule: scorer.py lexicon-finvader1-lm1 (calibrated macro-F1 0.609).
Language gate: DB `lang` column (GDELT) when present, else langdetect.

Usage (daily hook, pipeline C):
  enrich_historical_news.py --since YYYY-MM-DD --apply --dedupe
Full re-run (backfill):
  enrich_historical_news.py --apply --dedupe
"""
import argparse
import csv
import hashlib
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)

from db import get_connection  # noqa: E402

from scorer import (SCORER_ID, score_headline, label_from_scores,  # noqa: E402
                    normalize_headline, risk_hits, impact_label, detect_lang)
from extract_tickers import TickerExtractor  # noqa: E402

_PUNCT = re.compile(r"[^a-z0-9]+")

STAGING_COLUMNS = ["id", "sent_score", "vader_score", "lm_score", "sent_label",
                   "lang", "tickers", "impact", "dup_group_id", "dup_count",
                   "scorer", "scored_at"]

APPLY_SQL = """
CREATE TEMP TABLE news_enrich_staging (
  id           integer PRIMARY KEY,
  sent_score   numeric,
  vader_score  numeric,
  lm_score     numeric,
  sent_label   varchar(8),
  lang         varchar(8),
  tickers      text[],
  impact       varchar(8),
  dup_group_id bigint,
  dup_count    integer,
  scorer       varchar(32),
  scored_at    timestamp
) ON COMMIT DROP;
"""

APPLY_UPDATE_SQL = """
UPDATE silver.historical_news h
SET sent_score   = s.sent_score,
    vader_score  = s.vader_score,
    lm_score     = s.lm_score,
    sent_label   = s.sent_label,
    lang         = COALESCE(s.lang, h.lang),
    tickers      = s.tickers,
    impact       = s.impact,
    dup_group_id = s.dup_group_id,
    dup_count    = s.dup_count,
    scorer       = s.scorer,
    scored_at    = s.scored_at
FROM news_enrich_staging s
WHERE h.id = s.id;
"""

# Canonical pure-SQL dedupe recompute (enrichment/dedupe.sql). The md5-based
# gid differs from this runner's Python group_id only in normalization edge
# cases; group MEMBERSHIP is equivalent. The SQL refresh is the canonical
# producer — always run it after an incremental apply.
DEDUPE_SQL = """
WITH norm AS (
  SELECT id,
         date::date AS d,
         btrim(regexp_replace(lower(headline), '[^a-z0-9]+', ' ', 'g')) AS nh
  FROM silver.historical_news
),
grp AS (
  SELECT id,
         ('x' || substr(md5(d::text || '|' || nh), 1, 16))::bit(64)::bigint AS gid,
         COUNT(*) OVER (PARTITION BY d, nh) AS cnt
  FROM norm
)
UPDATE silver.historical_news h
SET dup_group_id = CASE WHEN g.cnt > 1 THEN g.gid ELSE NULL END,
    dup_count    = g.cnt
FROM grp g
WHERE h.id = g.id
  AND (h.dup_count IS DISTINCT FROM g.cnt
       OR h.dup_group_id IS DISTINCT FROM CASE WHEN g.cnt > 1 THEN g.gid ELSE NULL END);
"""


def dedupe_key(date_str: str, headline: str) -> str:
    """Normalized-headline + date group key. Aggressive normalization: keep
    only [a-z0-9] tokens — deterministic and immune to GDELT spacing."""
    norm = _PUNCT.sub(" ", (headline or "").lower()).strip()
    return f"{date_str}|{norm}"


def group_id(key: str) -> int:
    """Stable signed-64-bit group id from the dedupe key."""
    digest = hashlib.md5(key.encode("utf-8")).digest()
    v = int.from_bytes(digest[:8], "big", signed=False)
    return v - (1 << 64) if v >= (1 << 63) else v


def apply_staging(conn, csv_path: str) -> int:
    """Load staging CSV into a temp table and UPDATE historical_news.
    One transaction; idempotent (keyed on id). Returns rows updated."""
    cur = conn.cursor()
    cur.execute(APPLY_SQL)
    with open(csv_path, "r", encoding="utf-8") as f:
        cur.copy_expert(
            "COPY news_enrich_staging FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')",
            f)
    cur.execute(APPLY_UPDATE_SQL)
    n = cur.rowcount
    conn.commit()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="only rows with date >= since")
    ap.add_argument("--out", default=os.path.join(HERE, "enrichment", "enrichment_staging.csv"))
    ap.add_argument("--apply", action="store_true",
                    help="apply the staging CSV to silver.historical_news after writing")
    ap.add_argument("--dedupe", action="store_true",
                    help="run canonical SQL dedupe recompute after apply")
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()
    where = "WHERE h.date >= %s" if args.since else ""
    params = (args.since,) if args.since else ()
    cur.execute(f"""
        SELECT h.id, h.date, h.category, h.entity_name, h.headline, h.lang,
               ni.risk_hits
        FROM silver.historical_news h
        LEFT JOIN (
            SELECT DISTINCT ON (date, headline) date, headline, risk_hits
            FROM silver.news_items
            ORDER BY date, headline, risk_hits DESC NULLS LAST
        ) ni ON ni.date = h.date::date AND ni.headline = h.headline
        {where}
        ORDER BY h.id
    """, params)
    rows = cur.fetchall()
    print(f"rows read: {len(rows)}")

    if not rows:
        conn.close()
        print("nothing to do")
        return

    x = TickerExtractor.from_db(conn)

    # pass 1: score + extract + dedupe keys
    recs = []
    groups = defaultdict(list)
    for rid, dt, cat, ent, hl, lang, ni_risk in rows:
        date_str = str(dt)[:10]
        lang_final = lang or detect_lang(normalize_headline(hl))
        if lang_final == "en":
            s = score_headline(hl)
            label = label_from_scores(s)
            sent, vbase, lm = s["fin_vader_score"], s["vader_score"], s["lm_score"]
        else:
            label, sent, vbase, lm = None, None, None, None
        ticks = x.extract(hl, cat)
        key = dedupe_key(date_str, hl)
        rec = {
            "id": rid, "date": date_str, "category": cat,
            "sent_score": sent, "vader_score": vbase, "lm_score": lm,
            "sent_label": label, "lang": lang_final, "tickers": ticks,
            "risk": ni_risk if ni_risk is not None else risk_hits(hl),
            "key": key,
        }
        groups[key].append(rid)
        recs.append(rec)

    # pass 2: dup groups + impact (within-batch; --dedupe canonicalizes)
    from collections import Counter
    stats = Counter()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out_rows = []
    for rec in recs:
        gids = groups[rec["key"]]
        dup_count = len(gids)
        gid = group_id(rec["key"]) if dup_count > 1 else None
        impact = impact_label(rec["risk"], dup_count)
        stats[f"label={rec['sent_label']}"] += 1
        stats[f"cat={rec['category']}"] += 1
        if dup_count > 1:
            stats["dup_rows"] += 1
        if rec["tickers"]:
            stats["with_tickers"] += 1
        if rec["lang"] != "en":
            stats["non_en"] += 1
        out_rows.append([
            rec["id"], rec["sent_score"], rec["vader_score"], rec["lm_score"],
            rec["sent_label"], rec["lang"],
            "{" + ",".join(rec["tickers"]) + "}" if rec["tickers"] else "{}",
            impact, gid if gid is not None else "", dup_count,
            SCORER_ID, now,
        ])

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(STAGING_COLUMNS)
        w.writerows(out_rows)
    print(f"wrote {args.out}: {len(out_rows)} rows")

    if args.apply:
        n = apply_staging(conn, args.out)
        print(f"applied: {n} rows updated in silver.historical_news")
    if args.apply and args.dedupe:
        cur.execute(DEDUPE_SQL)
        print(f"dedupe recompute: {cur.rowcount} rows updated")
        conn.commit()

    conn.close()
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")


if __name__ == "__main__":
    main()
