-- 2026-09-02 (kanban t_e71cffde): HK IPO subscription-window feed + day10/day20 returns
--
-- 1. silver.unified_ipo_performance: 10th/20th trading-day returns (decimal
--    fractions, offer -> close), matching the API's on-the-fly day-20 lateral
--    (OFFSET 19 over silver.unified_prices from listing_date).
-- 2. silver.unified_ipo_calendar: subscription-window fields populated by the
--    new silver/refresh_ipo_upcoming_daily.py (AAStocks upcoming-IPO feed).
-- 3. bronze.aastocks_ipo_upcoming_raw: raw landing table for that feed.

ALTER TABLE silver.unified_ipo_performance
    ADD COLUMN IF NOT EXISTS return_10d double precision,
    ADD COLUMN IF NOT EXISTS return_20d double precision;

ALTER TABLE silver.unified_ipo_calendar
    ADD COLUMN IF NOT EXISTS application_start date,
    ADD COLUMN IF NOT EXISTS application_end date,
    ADD COLUMN IF NOT EXISTS allotment_date date;

CREATE TABLE IF NOT EXISTS bronze.aastocks_ipo_upcoming_raw (
    symbol            varchar(8) PRIMARY KEY,        -- '02041' (5-digit zero-padded)
    stock_name        varchar(200),
    industry          varchar(200),
    offer_price_text  varchar(40),                   -- '15.42' | '14.45-19.55' | 'N/A'
    lot_size          integer,
    entry_fee         numeric(14,2),
    closing_date      date,                          -- application close (from list)
    grey_market_date  date,
    listing_date      date,
    application_start date,                          -- offer period open (detail page)
    application_end   date,                          -- offer period close (detail page)
    price_set_date    date,
    allotment_date    date,
    sponsor           text,
    scraped_at        timestamp without time zone DEFAULT now()
);
