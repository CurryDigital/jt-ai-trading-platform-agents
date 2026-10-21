-- Migration: news enrichment layer for silver.historical_news (kanban t_9be92903,
-- handoff from qr_research t_f7f1c624; gates PASS: macro-F1 0.609, ticker precision 99.5%).
-- Additive nullable columns -> zero-downtime. gold.news_sentiment_daily UNTOUCHED.

-- DDL for silver.historical_news enrichment (task t_f7f1c624)
-- qr_etl owns application. All columns nullable → zero-downtime.
-- lang already exists (GDELT-sourced); do NOT re-add.

ALTER TABLE silver.historical_news
  ADD COLUMN IF NOT EXISTS sent_score     numeric,       -- fin-VADER compound (label driver)
  ADD COLUMN IF NOT EXISTS vader_score    numeric,       -- stock VADER compound (news_items comparable)
  ADD COLUMN IF NOT EXISTS lm_score       numeric,       -- Loughran-McDonald polarity (research use)
  ADD COLUMN IF NOT EXISTS sent_label     varchar(8),    -- bull | bear | neutral | NULL (non-English)
  ADD COLUMN IF NOT EXISTS impact         varchar(8),    -- High | Med | Low (heuristic, see manifest)
  ADD COLUMN IF NOT EXISTS tickers        text[],        -- extracted tickers, category-scoped
  ADD COLUMN IF NOT EXISTS dup_group_id   bigint,        -- NULL when dup_count = 1
  ADD COLUMN IF NOT EXISTS dup_count      integer,       -- rows sharing normalized headline + date
  ADD COLUMN IF NOT EXISTS scorer         varchar(32),   -- 'lexicon-finvader1-lm1'
  ADD COLUMN IF NOT EXISTS scored_at      timestamp;

-- API-facing view for GET /api/news/by-asset
CREATE OR REPLACE VIEW silver.v_news_enriched AS
SELECT id, date, category, entity_name, headline, source, url, lang,
       sent_label, sent_score, lm_score, impact, tickers, dup_count, dup_group_id
FROM silver.historical_news;

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_hn_sent_label ON silver.historical_news (category, sent_label);
CREATE INDEX IF NOT EXISTS idx_hn_tickers    ON silver.historical_news USING gin (tickers);
CREATE INDEX IF NOT EXISTS idx_hn_dup_group  ON silver.historical_news (dup_group_id) WHERE dup_group_id IS NOT NULL;
