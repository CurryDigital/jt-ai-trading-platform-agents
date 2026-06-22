-- ============================================================
-- Migration 001 — source_freshness table for per-source SLAs.
-- Safe to re-run (idempotent).
--
-- Problem solved:
--   gold_layer_state has one row with a single 'state' column. Whether
--   data is fresh is binary, but the pipeline has ~8 sources with
--   different cadences. Operator can't tell "yfinance fresh, FMP stale"
--   from looking at gold_layer_state — they see one cell.
--
--   This table holds per-source freshness with an expected cadence so
--   a single SQL query surfaces which source is overdue:
--
--     SELECT source, max_date, expected_frequency, staleness_hours
--     FROM   gold.source_freshness
--     WHERE  staleness_hours > expected_max_staleness_hours
--     ORDER  BY staleness_hours DESC;
-- ============================================================

SET search_path = gold, openclaw_researcher, public;

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.source_freshness (
    source                       TEXT PRIMARY KEY,
    asset_class                  TEXT,          -- equity / crypto / fx / commodity / macro
    max_date                     DATE,          -- the latest business date this source covers
    expected_frequency           TEXT NOT NULL, -- 'daily' | 'hourly' | 'weekly' | 'on_demand'
    expected_max_staleness_hours INTEGER NOT NULL DEFAULT 24,
    last_refreshed_at            TIMESTAMPTZ,
    last_checked_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error                   TEXT,          -- populated on last failure
    notes                        TEXT
);

COMMENT ON TABLE  gold.source_freshness IS
    'Per-source ETL freshness SLA. One row per bronze source. Populated by daily_refresh.sh after each source completes.';
COMMENT ON COLUMN gold.source_freshness.expected_max_staleness_hours IS
    'Operator threshold. (NOW() - last_refreshed_at) > this hours → source is overdue.';

-- Derived: staleness_hours as a column so dashboards do not have to compute it.
CREATE OR REPLACE VIEW gold.v_source_freshness AS
SELECT
    source,
    asset_class,
    max_date,
    expected_frequency,
    expected_max_staleness_hours,
    last_refreshed_at,
    last_checked_at,
    last_error,
    notes,
    EXTRACT(EPOCH FROM (NOW() - COALESCE(last_refreshed_at, last_checked_at))) / 3600.0
        AS staleness_hours,
    CASE
        WHEN last_refreshed_at IS NULL THEN 'never_refreshed'
        WHEN EXTRACT(EPOCH FROM (NOW() - last_refreshed_at)) / 3600.0
             > expected_max_staleness_hours THEN 'stale'
        ELSE 'fresh'
    END AS freshness_status
FROM gold.source_freshness;

GRANT SELECT ON gold.source_freshness  TO openclaw_user;
GRANT SELECT ON gold.v_source_freshness TO openclaw_user;
GRANT INSERT, UPDATE ON gold.source_freshness TO openclaw_user;

-- Seed initial SLAs — bronze scripts UPSERT into this table after success.
-- Operator can tune `expected_max_staleness_hours` without re-deploying code.
INSERT INTO gold.source_freshness
    (source, asset_class, expected_frequency, expected_max_staleness_hours, notes)
VALUES
    ('yfinance',  'equity',    'daily',  30, 'Equity OHLCV — runs daily ~07:00 UTC'),
    ('binance',   'crypto',    'daily',  30, 'Crypto klines — 1d resolution'),
    ('fmp',       'equity',    'daily',  30, 'Financial Modeling Prep — prices + earnings'),
    ('ibkr',      'fx',        'daily',  30, 'IBKR FX bars via EC2 runner'),
    ('hkex',      'equity',    'daily',  30, 'HKEX IPO calendar'),
    ('fred',      'macro',     'daily',  48, 'FRED macro indicators — some series weekly'),
    ('cftc',      'fx',        'weekly', 192, 'CFTC COT report — released Fridays'),
    ('coinbase',  'crypto',    'daily',  30, 'Coinbase OHLCV — fallback for binance')
ON CONFLICT (source) DO UPDATE SET
    asset_class                  = EXCLUDED.asset_class,
    expected_frequency           = EXCLUDED.expected_frequency,
    expected_max_staleness_hours = EXCLUDED.expected_max_staleness_hours,
    notes                        = EXCLUDED.notes;

DO $$
BEGIN
    RAISE NOTICE 'Migration 001 complete. Operator query:';
    RAISE NOTICE '  SELECT * FROM gold.v_source_freshness WHERE freshness_status = ''stale'';';
END $$;
