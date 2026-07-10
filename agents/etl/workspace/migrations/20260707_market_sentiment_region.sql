ALTER TABLE gold.market_sentiment_facts
  DROP CONSTRAINT IF EXISTS market_sentiment_facts_id_check,
  DROP CONSTRAINT IF EXISTS market_sentiment_facts_pkey,
  ADD COLUMN IF NOT EXISTS region character varying(8) NOT NULL DEFAULT 'US',
  ADD COLUMN IF NOT EXISTS regime character varying(32),
  ADD COLUMN IF NOT EXISTS vix_sma60 numeric,
  ADD COLUMN IF NOT EXISTS vix_z60 numeric,
  ADD PRIMARY KEY (region);
