-- 2026-08-20: create bronze.coinbase_crypto_ohlcv
-- The coinbase ingest (bronze/coinbase/ingest_coinbase.py) was registered in
-- gold.source_freshness but its target table never existed — every run failed
-- with "relation does not exist" (previously masked by per-product error
-- swallowing), leaving the source 'never_refreshed' and the frontend badge
-- DISCONNECTED. Schema matches the script's INSERT column list and its
-- ON CONFLICT (ticker, interval, timestamp) target.

CREATE TABLE IF NOT EXISTS bronze.coinbase_crypto_ohlcv (
    ticker       text        NOT NULL,
    interval     text        NOT NULL,
    timestamp    timestamptz NOT NULL,
    open         numeric,
    high         numeric,
    low          numeric,
    close        numeric,
    volume       numeric,
    raw_data     jsonb,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coinbase_crypto_ohlcv_pkey PRIMARY KEY (ticker, interval, timestamp)
);

CREATE INDEX IF NOT EXISTS coinbase_crypto_ohlcv_ts_idx
    ON bronze.coinbase_crypto_ohlcv (timestamp DESC);
