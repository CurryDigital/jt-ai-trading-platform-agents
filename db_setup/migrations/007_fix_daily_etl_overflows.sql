-- Migration: fix daily ETL issues discovered 2026-07-17
-- 1. markets_stocks_overview.top_strategy_score numeric(6,4) overflows when score=100
-- 2. silver.unified_prices missing 'source' column used by promote_ibkr.py

-- Ensure schemas exist (idempotent)
CREATE SCHEMA IF NOT EXISTS consumption;
CREATE SCHEMA IF NOT EXISTS silver;

-- 1. Widen top_strategy_score to fit 100.00 and future values.
-- Two views depend on this column from this table; drop and recreate them.
DROP VIEW IF EXISTS consumption.v_markets_stocks;
DROP VIEW IF EXISTS consumption.stock;

ALTER TABLE consumption.markets_stocks_overview
    ALTER COLUMN top_strategy_score TYPE numeric(10,4);

CREATE OR REPLACE VIEW consumption.v_markets_stocks AS
SELECT ticker,
    name,
    sector,
    industry,
    market,
    price,
    change_pct,
    volume,
    trend,
    rsi_14,
    market_cap,
    pe_ratio,
    top_strategy_score,
    signal,
    signal_strength,
    updated_at
FROM consumption.markets_stocks_overview
ORDER BY top_strategy_score DESC NULLS LAST;

CREATE OR REPLACE VIEW consumption.stock AS
SELECT id,
    ticker,
    name,
    sector,
    industry,
    market,
    price,
    change_pct,
    change_value,
    volume,
    avg_volume,
    volume_ratio,
    trend,
    rsi_14,
    distance_to_52w_high_pct,
    distance_to_52w_low_pct,
    market_cap,
    pe_ratio,
    forward_pe,
    pb_ratio,
    dividend_yield,
    strategy_signals,
    top_strategy_score,
    updated_at,
    signal,
    signal_strength,
    asset_class
FROM consumption.markets_stocks_overview;

-- 2. Add source column to silver.unified_prices used by promote_ibkr.py INSERT
ALTER TABLE silver.unified_prices
    ADD COLUMN IF NOT EXISTS source varchar(50);

DO $$
BEGIN
    RAISE NOTICE 'top_strategy_score widened to numeric(10,4) in consumption.markets_stocks_overview';
    RAISE NOTICE 'v_markets_stocks and stock views recreated';
    RAISE NOTICE 'source column added to silver.unified_prices';
END $$;
