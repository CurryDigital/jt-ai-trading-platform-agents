-- Migration: contract-month futures prices (Phase A, task t_822b6365)
-- Date: 2026-09-26
-- Purpose: Dedicated landing + normalized tables for Databento contract-month
--          futures data (GLBX.MDP3). Contract-month rows must NOT enter
--          silver.unified_prices (one-row-per-ticker-date assumption is
--          load-bearing for gold rebuilds and the paper engine).

BEGIN;

-- Raw landing: one row per (root, raw_symbol, date) as delivered by Databento.
CREATE TABLE IF NOT EXISTS bronze.databento_futures_contracts (
    root               TEXT        NOT NULL,              -- e.g. 'GC', 'CL', 'ZW'
    contract_month     TEXT        NOT NULL,              -- 'YYYY-MM' expiry month
    raw_symbol         TEXT        NOT NULL,              -- Databento raw symbol, e.g. 'GCZ0'
    expiry             DATE,                              -- last trade date (definition schema)
    first_notice_date  DATE,                              -- definition schema, NULL when n/a
    date               DATE        NOT NULL,              -- trading day
    open               NUMERIC,
    high               NUMERIC,
    low                NUMERIC,
    settle_close       NUMERIC,                           -- official daily settlement
    volume             BIGINT,
    open_interest      BIGINT,                            -- statistics schema
    raw_data           JSONB,                             -- full source record(s)
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (root, raw_symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_databento_fut_root_month
    ON bronze.databento_futures_contracts (root, contract_month, date);

-- Normalized contract-month series, deduped.
-- PK (root, contract_month, date) per Phase A spec.
CREATE TABLE IF NOT EXISTS silver.futures_contract_prices (
    root               TEXT        NOT NULL,
    contract_month     TEXT        NOT NULL,              -- 'YYYY-MM'
    expiry             DATE,
    first_notice_date  DATE,
    date               DATE        NOT NULL,
    open               NUMERIC,
    high               NUMERIC,
    low                NUMERIC,
    settle_close       NUMERIC,
    volume             BIGINT,
    open_interest      BIGINT,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (root, contract_month, date)
);

CREATE INDEX IF NOT EXISTS idx_fut_contract_prices_date
    ON silver.futures_contract_prices (date);

COMMIT;
