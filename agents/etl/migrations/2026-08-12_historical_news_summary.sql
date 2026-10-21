-- 2026-08-12: silver.historical_news article lede/summary (kanban t_2b413d87)
-- summary = plain-text article lede/body (HTML-stripped, <= 4000 chars).
-- Sources, in precedence order:
--   1. RSS feed summary (silver/news/clean_news.py, from bronze.raw_news
--      raw_content payload 'summary') — free, at ingest time.
--   2. silver.news_items.body joined on url (one-time + ongoing backfill in
--      bronze/news/fetch_article_ledes.py).
--   3. Live article fetch + trafilatura extraction for GDELT urls
--      (bronze/news/fetch_article_ledes.py).
-- Sentinel semantics: NULL = not yet attempted; '' (empty) = attempted, no
-- text extractable (paywall / bot-block / dead link) — never retried.
-- Consumer: consumption/market/build_news_clusters.py embeds
-- headline + first ~200 words of summary when present.

ALTER TABLE silver.historical_news ADD COLUMN IF NOT EXISTS summary TEXT;

COMMENT ON COLUMN silver.historical_news.summary IS
  'Plain-text article lede/body (<=4000 chars). NULL=not attempted, empty=attempted-no-content. Populated by clean_news.py (RSS) and fetch_article_ledes.py (join + trafilatura).';

-- Fetcher query pattern: recent rows still needing a fetch attempt.
CREATE INDEX IF NOT EXISTS idx_historical_news_summary_pending
  ON silver.historical_news (date DESC)
  WHERE summary IS NULL;
