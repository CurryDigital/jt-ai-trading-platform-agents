# news_clusters_daily — historical per-day story clusters (kanban t_3955c4f6)

Status: full-year build LIVE at threshold 0.80 (2025-08-12 .. , kept current
through yesterday UTC by a freshness guard in scripts/news_clusters_refresh.sh,
kanban t_3a8e2528). The guard gates on max(window_date) via one cheap psql
probe per 2h tick and builds at most 10 days per tick (~42s/day) when stale.
NOTE: a full rebuild at a NEW final threshold is still gated on the user's
similarity-threshold decision; the incremental guard always builds at 0.80
to match existing provenance.

## Table: consumption.news_clusters_daily

Successor to consumption.news_clusters for history. The live table keeps
serving the rolling 48h window untouched; this table is addressed per day.

| column | type | notes |
|---|---|---|
| window_date | DATE | UTC calendar day of the silver rows (PK part 1) |
| cluster_id | VARCHAR(32) | sha1(cat\|lower(canonical_headline))[:16] — SAME formula as live table; a story continuing across days keeps its id (PK part 2) |
| window_hours | INTEGER | always 24 (contract compat with live table) |
| canonical_headline | TEXT | highest-authority member; ties → earliest first_seen |
| story_count | INTEGER | == jsonb_array_length(members) (QA-enforced) |
| outlet_count | INTEGER | distinct member outlets |
| first_seen_utc / last_seen_utc | TIMESTAMP | member span within the day |
| asset_class | VARCHAR(8) | US / HK / CRYPTO / FX / METAL (clustering never merges across classes) |
| driver_tags | TEXT[] | same heuristics as live builder |
| tickers | TEXT[] | validated platform tickers (gold.daily_ohlcv ∪ active positions) |
| llm_direction / llm_confidence / llm_rationale | — | NULL on backfilled rows (news_outlook has no history for the range; same join key if later stamped) |
| impact_score | INTEGER | exact sum of impact_components (QA-enforced) |
| impact_components | JSONB | {attention, coverage, recency, keyword_impact, llm_impact}; computed AS-OF day end (ref_now = window_date + 1), so recency/attention describe the story ON that day. Breadth gate (t_46609992, applied 2026-08-13): story_count=1 rows are capped at impact_score 25 — recency/keyword/llm scaled into the budget left after coverage+attention, exact sum preserved |
| members | JSONB | [{headline, outlet, published_at, url, lang}] newest first |
| sim_threshold | NUMERIC(4,3) | provenance: threshold that produced the row (0.820 for pilot) |
| computed_at | TIMESTAMP | build time |

Indexes: PK(window_date, cluster_id), (cluster_id), (asset_class, window_date).

## Builder

`consumption/market/backfill_news_clusters_daily.py` (etl-news-venv,
fastembed paraphrase-multilingual-MiniLM-L12-v2 — same model/venv as the
live 48h builder, so embeddings are comparable across the two tables).

```
etl-news-venv/bin/python consumption/market/backfill_news_clusters_daily.py \
    [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--threshold 0.82] \
    [--rebuild] [--limit-days N] [--dry-run]
```

- Default range = full silver.historical_news span (2025-08-12 .. today).
- Idempotent + resume-safe: days already in the table are skipped unless
  --rebuild; each day commits independently (SIGTERM-safe).
- Throughput measured: ~6-9s per normal day (~150-270 rows), ~42s worst
  day (1,202 rows, GDELT-inflated). Full year ≈ 40-60 min, single process,
  embedding model loaded once.
- Reuses build_news_clusters.py functions verbatim (pre-clean contract,
  greedy cosine clustering, canonical/outlet authority, driver tags,
  tickers, impact components) — no logic drift between live and history.

## Endpoint contract (for qr_frontend, GET /api/news/clusters extension)

Current live behavior (unchanged): no params → rolling 48h window from
consumption.news_clusters at max(computed_at).

Proposed extension to serve the News attention timeline + reliability panel:

1. `GET /api/news/clusters?date=YYYY-MM-DD`
   → rows from consumption.news_clusters_daily WHERE window_date = :date,
   ordered by impact_score DESC. Same JSON shape as the live endpoint
   (identical column semantics); add `window_date` and `sim_threshold` to
   each cluster object.
2. `GET /api/news/clusters/timeline?from=YYYY-MM-DD&to=YYYY-MM-DD[&asset_class=US]`
   → per-day aggregate for the attention chart:
   `SELECT window_date, asset_class, count(*) AS stories,
           sum(story_count) AS articles, max(impact_score) AS top_impact
    FROM consumption.news_clusters_daily
    WHERE window_date BETWEEN :from AND :to
    GROUP BY 1, 2 ORDER BY 1`
3. Multi-day story stitching: GROUP BY cluster_id across window_date —
   same id = same canonical story; the timeline can render story lifespan
   (first/last window_date, per-day story_count) with one query.
4. Availability endpoint (optional):
   `SELECT min(window_date), max(window_date), count(DISTINCT window_date)`
   so the UI can grey out days with no data (silver has gaps: e.g. parts of
   Jul 2026 — only 27 distinct days in July; weekends/holidays are thin).

Caveat the UI should surface: rows carry sim_threshold; when the final
threshold lands and the year is rebuilt, cluster shapes (and singleton
rate) will change — nothing else in the contract changes.

## Pilot QA (2026-07-30..2026-08-12, threshold 0.82)

- 3,782 clusters / 14 days; per-day 56..961 clusters, avg story_count
  1.11..1.63.
- Integrity: 0 empty members, 0 impact-sum mismatches, 0 story_count vs
  len(members) mismatches, tickers validated (SPY, GC=F, ...).
- Multi-day continuity verified: stories span 3+ days under one
  cluster_id (e.g. 'US stocks hold near records on hopes of an agreement
  with Iran').
- Singleton rate 80-94%/day at 0.82 — same under-collapse as the live
  window; this is why the full-year run waits for the threshold decision.
