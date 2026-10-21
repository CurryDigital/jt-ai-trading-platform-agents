-- 2026-08-12: silver.historical_news language tagging (kanban t_69e09f53)
-- lang = ISO 639-1 code (en, zh, ar, hi, ko, ru, ...).
-- Populated at ingest from GDELT article `language` metadata
-- (bronze/news/backfill_historical_news.py); legacy rows backfilled with a
-- Unicode-script heuristic (bronze/news/backfill_historical_news_lang.py).

ALTER TABLE silver.historical_news ADD COLUMN IF NOT EXISTS lang VARCHAR(16);

COMMENT ON COLUMN silver.historical_news.lang IS
  'ISO 639-1 code (en, zh, ar, hi, ko, ru, ...). From GDELT language metadata at ingest; Unicode-script heuristic for legacy rows.';

CREATE INDEX IF NOT EXISTS idx_historical_news_lang ON silver.historical_news(lang);
