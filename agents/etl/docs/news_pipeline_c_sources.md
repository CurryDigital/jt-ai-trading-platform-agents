# Pipeline C (news) — source audit, scorer decision, backfill depth

**Date:** 2026-08-07 · **Owner:** qr_etl · **Task:** kanban t_572bda38 (regime forecast v2 Phase 0)

## Pipeline shape

```
scripts/pipeline_c_news.sh  (cron 08:45 UTC Mon-Fri, job qr_etl.pipeline_c_news)
  1. bronze/news/ingest_news.py            RSS + GDELT last-24h  -> bronze.raw_news
  2. silver/news/clean_news.py             normalize/dedupe/scope -> silver.news_items
  3. gold/market/build_news_sentiment_daily.py  score + aggregate -> gold.news_sentiment_daily
```

Freshness contract: `gold.source_freshness` row `news_pipeline_c`
(expected_max_staleness_hours=30), written by the gold step; stage rows
`bronze:ingest_news`, `silver:clean_news` also tracked. Pipeline C is NOT in
pipeline B's dependency chain — B must read news features staleness-aware
(frame doc layer-3 rule: stale >2d -> downweight news block to 0).

## Source audit (all probed live 2026-08-07)

| Source | Status | Scope | Notes |
|---|---|---|---|
| FMP news (v3/v4 legacy + /stable/) | DEAD / paywalled | — | legacy endpoints retired; /stable/news/* = "Restricted Endpoint" under current subscription |
| CNBC Top / Economy RSS | LIVE | US | |
| MarketWatch topstories / marketpulse RSS | LIVE | US | |
| Yahoo Finance RSS | LIVE | US | |
| Fed press RSS | LIVE | US | low volume, high signal |
| Investing.com news_1 (latest) | LIVE | US | |
| SCMP Business / Markets RSS | LIVE | HK | |
| HongKongFP RSS | LIVE | HK | broad HK, replaces RTHK (URL dead, returns HTML) |
| CoinDesk / CoinTelegraph / The Block RSS | LIVE | CRYPTO | |
| ForexLive RSS | LIVE | FX | replaces FXStreet (Cloudflare) + DailyFX (Akamai 403) |
| Investing.com news_25 (forex) | LIVE | FX | |
| Mining.com RSS | LIVE | METAL | |
| Investing.com news_11 (commodities) | LIVE | METAL | replaces Kitco (no public RSS; HTML at all probed paths) + goldsilver.com (Cloudflare) |
| GDELT DOC 2.0 API | LIVE, rate-limited | all | see throttling notes |

Blocked/dead and intentionally not used: FXStreet, DailyFX, Kitco,
goldsilver.com (bot-walled), RTHK (dead URL), The Standard HK (HTML),
fxempire (broken encoding), FMP (subscription).

## GDELT throttling (operational)

Published limit 1 req / 5s; from this box 429s appear at <10s spacing
(shared-IP throttle, cooldown observed >3 min after bursts). Daily ingest uses
20s spacing + 4 retries x 60s backoff; a partially-failed GDELT scope is a
soft failure (RSS covers the floor volume). Backfill uses 15s spacing + 5
retries x 120s backoff and logs failed windows for re-run (fully idempotent:
historical_news unique constraint + news_items url_hash).

## Historical backfill — actual depth vs 24-month target

**Target:** 24 months/scope into `silver.historical_news`.
**Serving depth (corrected 2026-08-07, kanban t_e8e6fe4c):** GDELT DOC 2.0
serves **>= 18 months** — live probe from this box (US backfill query, weekly
windows, 20s spacing) returned full 250-article pages for windows 7mo back
(2026-01-02..09) and 18mo back (2025-02-06..13). The earlier "~6 month serving
cap" recorded here was WRONG: it was an artifact of `probe_depth()` only
testing 6mo/4mo back and hard-capping the effective start at today-6mo (and of
429 throttle streaks being misread as empty windows — empty windows return
HTTP 200 with `articles=[]`, NOT 429). `probe_depth()` now probes
18/15/12/9/6/4 months back, skips depths beyond `--months`, and treats request
failures as inconclusive (never lowers the cap).

**Achieved (verified 2026-08-11, kanban t_e8e6fe4c ACCEPTANCE PASS):**
`silver.historical_news` covers **2025-08-12/13 → 2026-08-08+ for all 5
scopes** (12 months): US 12,310 / CRYPTO 11,743 / METAL 11,043 / FX 10,322 /
HK 9,763 articles. `gold.news_sentiment_daily` re-backfilled over the same
range: 2025-08-12 → 2026-08-10, 1,795 rows (357 days x 5 scopes). Backfill
ledger `silver.news_backfill_windows` deepest per scope 2025-08-12/13
(62-119 windows/scope). The chunk cron was removed on 2026-08-11 after
acceptance passed; deeper-than-12mo windows were NOT exhaustively fetched
(24mo target not met — GDELT serves >=18mo per probe, so 13-18mo remains
fetchable on demand). Execution
model (corrected 2026-08-07 pm): unbounded one-shot runs were SIGTERMed by
the cron script timeout (~17-27 min) with ~50% of windows 429ing through
5x120s retries. Replaced by a RECURRING CHUNK runner
(`qr_etl.news_backfill_chunk`, every 2h at :43 odd hours UTC, clear of
pipelines A/B/C) running `backfill_historical_news.py --months 24 --no-probe
--max-seconds 480 --retries 2 --max-consec-fail 3` + a historical scoring
pass. `--no-probe` is required under throttle: deep probes that 429 are
"inconclusive" individually, but the cap is max(SERVED probes), so throttled
deep probes silently collapsed the effective start to 6mo in both one-shot
runs. Out-of-range windows return cheap empties and are ledgered with 0
articles. Weekly windows, 250-record cap per query truncates peak news
weeks. Resume ledger `silver.news_backfill_windows(scope, window_start)`
makes every chunk idempotent: completed windows are skipped, failed windows
(429 streaks) are re-fetched on later ticks. The chunk job was removed on
2026-08-11 once the 12-month acceptance passed (per-scope MIN(date) <=
2025-08-15); re-create it if deeper-than-12mo coverage is ever requested.

Consequence per frame doc §3 open-decision #3: **Phase 2 model training gates
on accumulated history** — silver.news_items accumulates daily from
2026-08-07; with the corrected >=18-month GDELT depth plus forward
accumulation, 24 months of contiguous history is reachable around 2027-02
without a paid archive (GDELT GKG 2.1 via BigQuery, NewsAPI paid,
Bloomberg/Reuters licence remain options for deeper history).

Per-source native RSS depth: 10–60 latest items only (no archive value).

## Sentiment scorer decision (frame doc open-question #1)

**Chosen: lexicon** (`lexicon-vader1` = VADER compound + 60-term finance
overlay + risk-keyword counter), NOT LLM batch. Rationale: no LLM API key is
provisioned for ETL cron use; the only keys on this box are the agent's
interactive provider credentials (kimi-coding / copilot pool) — unsuitable
inside a headless daily cron and an unsustainable runtime dependency. Lexicon
is free, deterministic, reproducible over the backfill.

**LLM swap path:** score function is isolated in
`build_news_sentiment_daily.score_unscored()`. To upgrade: NULL out
`sent_score` for the target window, implement an `llm-*` scorer writing the
same columns (`sent_score`, `sent_label`, `risk_hits`, `scorer`,
`scored_at`), re-run with `--backfill`. Aggregates recompute from per-item
scores — no schema change.

## Table contracts

- `silver.news_items` — dedupe key `url_hash` (canonical URL, else normalized
  headline); `scopes text[]` (multi-scope items kept once, fanned out at
  aggregate time); per-item `sent_score/sent_label/risk_hits/scorer`.
- `silver.historical_news` — pre-existing archive table (date, category=scope,
  entity_name, headline, source); written only by the backfill.
- `gold.news_sentiment_daily` — per (date, scope): sent_mean, sent_dispersion,
  news_volume, volume_z (trailing 60d, NULL until >=20 obs), risk_keyword_hits,
  high_severity_event (gold.macro_event_flags.severity='heavy'), scored_items,
  scorer. Rows upserted for all 5 scopes daily (0-volume days included).

## Known gaps / follow-ups

- `/api/settings/data-sources` (qr_frontend backend,
  `workspace/jt-ai-trading-platform/backend/app/main.py`) is a HARDCODED list —
  it does not read `gold.source_freshness`, so pipeline C freshness cannot
  surface there without a frontend change. Follow-up card filed.
- gold.news_sentiment (7 hardcoded display headlines from
  build_market_news.py) is untouched — retirement is research/frontend-owned
  per the frame doc, NOT Phase 0.
- Acceptance "5 consecutive clean weekday runs" starts 2026-08-10 (first
  scheduled tick after today; today's 08:45 run fires same-day).
