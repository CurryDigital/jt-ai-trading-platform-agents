-- Apply enrichment staging CSV to silver.historical_news (task t_f7f1c624)
-- Input: enrichment_staging.csv produced by enrich_historical_news.py
-- Idempotent: keyed on id; safe to re-run.

BEGIN;

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
);

-- psql: \copy news_enrich_staging FROM 'enrichment_staging.csv' WITH (FORMAT csv, HEADER true, NULL '');
-- (or psycopg2 copy_expert from the pipeline)

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

COMMIT;

-- Verification:
-- SELECT category, sent_label, COUNT(*) FROM silver.historical_news
--  GROUP BY 1,2 ORDER BY 1,2;
-- SELECT COUNT(*) FILTER (WHERE scored_at IS NULL) AS unscored FROM silver.historical_news;
