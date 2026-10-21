-- 016_news_pipeline_c.sql
-- Pipeline C (news): silver normalized items + gold daily sentiment aggregates.
-- 2026-08-07 qr_etl — regime forecast v2 Phase 0 (kanban t_572bda38).

BEGIN;

-- ---------------------------------------------------------------------------
-- silver.news_items — normalized, deduped, scope-tagged news items.
-- Dedupe key: url_hash (sha256 of canonical url, else normalized headline).
-- Scopes: text[] — an item can belong to multiple scopes (e.g. "Fed gold").
-- sent_* columns are written by gold/market/build_news_sentiment_daily.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.news_items (
    id            BIGSERIAL PRIMARY KEY,
    published_at  TIMESTAMP NOT NULL,
    date          DATE NOT NULL,
    scopes        TEXT[]  NOT NULL DEFAULT '{}',
    entity_name   VARCHAR(100),
    headline      TEXT NOT NULL,
    body          TEXT,
    source        VARCHAR(100),
    url           TEXT,
    url_hash      VARCHAR(64) NOT NULL,
    headline_hash VARCHAR(64),
    sent_score    NUMERIC(6,4),      -- -1..+1 per-item compound score
    sent_label    VARCHAR(8),        -- bull / bear / neu
    risk_hits     INTEGER,           -- risk keyword hits in this item
    scorer        VARCHAR(20),       -- 'lexicon-vader1' / future 'llm-*'
    scored_at     TIMESTAMP,
    ingested_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT news_items_url_hash_key UNIQUE (url_hash)
);
CREATE INDEX IF NOT EXISTS news_items_date_idx     ON silver.news_items (date DESC);
CREATE INDEX IF NOT EXISTS news_items_scopes_idx   ON silver.news_items USING GIN (scopes);
CREATE INDEX IF NOT EXISTS news_items_unscored_idx ON silver.news_items (date) WHERE sent_score IS NULL;

-- ---------------------------------------------------------------------------
-- gold.news_sentiment_daily — per (date, scope) aggregates for regime v2.
-- sent_mean: mean of per-item compound scores across items (item = unit of
--   volume, so the mean IS volume-weighted per the frame doc).
-- volume_z: news_volume z-score vs trailing 60d of this table.
-- high_severity_event: 1 when gold.macro_event_flags.severity='heavy' that date.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.news_sentiment_daily (
    id                  BIGSERIAL PRIMARY KEY,
    date                DATE NOT NULL,
    scope               VARCHAR(8) NOT NULL,
    sent_mean           NUMERIC(6,4),
    sent_dispersion     NUMERIC(6,4),
    news_volume         INTEGER NOT NULL DEFAULT 0,
    volume_z            NUMERIC(8,4),
    risk_keyword_hits   INTEGER NOT NULL DEFAULT 0,
    high_severity_event INTEGER NOT NULL DEFAULT 0,
    scored_items        INTEGER NOT NULL DEFAULT 0,
    scorer              VARCHAR(20),
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT news_sentiment_daily_date_scope_key UNIQUE (date, scope),
    CONSTRAINT news_sentiment_daily_scope_check
        CHECK (scope IN ('US','HK','CRYPTO','FX','METAL'))
);
CREATE INDEX IF NOT EXISTS news_sentiment_daily_scope_date_idx
    ON gold.news_sentiment_daily (scope, date DESC);

COMMIT;
