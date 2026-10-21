-- Migration 010: HK IPO backfill support (task t_dc9123f7)
-- Adds grey-market (暗盤) session fields + AAStocks enrichment fields to silver.unified_ipo_calendar.

ALTER TABLE silver.unified_ipo_calendar
    ADD COLUMN IF NOT EXISTS grey_close        NUMERIC,
    ADD COLUMN IF NOT EXISTS grey_high         NUMERIC,
    ADD COLUMN IF NOT EXISTS grey_low          NUMERIC,
    ADD COLUMN IF NOT EXISTS grey_turnover     NUMERIC,
    ADD COLUMN IF NOT EXISTS grey_session_date DATE,
    ADD COLUMN IF NOT EXISTS grey_source       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS applied_lots_for_1_lot INTEGER;

-- offer_price must allow NULL: transfers of listing / listing-by-introduction have no offer price
ALTER TABLE silver.unified_ipo_calendar ALTER COLUMN offer_price DROP NOT NULL;

-- Fast lookup for strategy scans
CREATE INDEX IF NOT EXISTS idx_unified_ipo_calendar_listing_date
    ON silver.unified_ipo_calendar (listing_date);

COMMENT ON COLUMN silver.unified_ipo_calendar.grey_close IS 'Grey market (暗盤) close, session day before listing. Source: AAStocks/Phillip capture cron; history pre-2026-08 not available from free sources.';
