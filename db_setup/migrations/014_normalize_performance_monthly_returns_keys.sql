-- Migration 014: normalize consumption.performance_monthly_returns keys
--
-- Background: one-off backfills replaced this table with a strategy-level grouped
-- view (fixed by migration 013). This follow-up migration:
--   1. Coerces any lingering UPPERCASE portfolio_type values to lowercase so the
--      two ETL writers (performance_strategy_results.py and
--      portfolio_performance_attribution.py) do not create duplicate
--      (portfolio_type, year, month) rows.
--   2. Adds a trigger that forces portfolio_type to lowercase on every INSERT /
--      UPDATE, preventing future casing drift from ad-hoc scripts or manual
--      INSERTs.
--
-- Idempotent: UPDATE is harmless when no rows exist; trigger is recreated.

BEGIN;

-- 1. Normalize existing data. This may raise a unique violation if both 'paper'
--    and 'PAPER' keys exist for the same month; in that case the rows should be
--    reconciled manually. The current ETL scripts now both write lowercase 'paper'.
UPDATE consumption.performance_monthly_returns
SET portfolio_type = LOWER(portfolio_type)
WHERE portfolio_type <> LOWER(portfolio_type);

UPDATE consumption.performance_strategy_attribution
SET portfolio_type = LOWER(portfolio_type)
WHERE portfolio_type <> LOWER(portfolio_type);

-- 2. Trigger function to keep portfolio_type lowercase in both tables.
CREATE OR REPLACE FUNCTION consumption.trg_lower_portfolio_type()
RETURNS TRIGGER AS $$
BEGIN
    NEW.portfolio_type := LOWER(NEW.portfolio_type);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS lower_portfolio_type ON consumption.performance_monthly_returns;
CREATE TRIGGER lower_portfolio_type
    BEFORE INSERT OR UPDATE ON consumption.performance_monthly_returns
    FOR EACH ROW
    EXECUTE FUNCTION consumption.trg_lower_portfolio_type();

DROP TRIGGER IF EXISTS lower_portfolio_type_attr ON consumption.performance_strategy_attribution;
CREATE TRIGGER lower_portfolio_type_attr
    BEFORE INSERT OR UPDATE ON consumption.performance_strategy_attribution
    FOR EACH ROW
    EXECUTE FUNCTION consumption.trg_lower_portfolio_type();

COMMIT;
