-- 2026-08-30_hk_ipo_dataset_backfill.sql
-- Task t_dc9123f7: HK IPO dataset build (calendar 2015+, grey market, performance)

-- Bronze: raw AAStocks listed-IPO table rows (one per IPO)
CREATE TABLE IF NOT EXISTS bronze.aastocks_ipo_listed_raw (
    symbol              text PRIMARY KEY,          -- e.g. '02261'
    stock_name          text,
    listing_date        date,
    lot_size            integer,
    market_cap_range    text,                       -- e.g. '6.20-6.65' (B HKD) or single value
    offer_price         numeric,                    -- fixed offer price if shown
    listing_price       numeric,                    -- final offer price
    oversub_rate        numeric,                    -- retail over-subscription multiple (x)
    applied_lots_for_1  text,
    one_lot_success_pct numeric,
    debut_chg_pct       numeric,
    acc_chg_pct         numeric,
    scraped_at          timestamp DEFAULT now()
);

-- Bronze: raw AAStocks per-IPO HTML pages (company-summary / company-news)
CREATE TABLE IF NOT EXISTS bronze.aastocks_ipo_page_raw (
    symbol      text NOT NULL,
    page        text NOT NULL,                      -- 'summary' | 'news'
    content     text,
    http_status integer,
    scraped_at  timestamp DEFAULT now(),
    PRIMARY KEY (symbol, page)
);

-- Bronze: HKEX annual market statistics new-listings rows
CREATE TABLE IF NOT EXISTS bronze.hkex_annual_newlist_raw (
    code            text NOT NULL,
    listing_date    date NOT NULL,
    board           text,                           -- 'MAIN' | 'GEM'
    company_name    text,
    shares_offered  bigint,
    offer_price     numeric,
    funds_raised_m  numeric,                        -- HK$ millions
    source_year     integer,
    parsed_at       timestamp DEFAULT now(),
    PRIMARY KEY (code, listing_date)
);

-- Silver: grey-market (暗盤) session data, one row per IPO
CREATE TABLE IF NOT EXISTS silver.unified_ipo_grey_market (
    ticker              text PRIMARY KEY,           -- '02261.HK'
    grey_session_date   date,
    grey_open           numeric,
    grey_high           numeric,
    grey_low            numeric,
    grey_close          numeric,
    grey_turnover       numeric,                    -- HKD
    grey_return_pct     numeric,                    -- (grey_close/offer - 1)*100
    source              text,                       -- 'AAStocks(Futu)' etc.
    updated_at          timestamp DEFAULT now()
);

-- Bronze HKEX table: extras captured from Fact Book parse
ALTER TABLE bronze.hkex_annual_newlist_raw
    ADD COLUMN IF NOT EXISTS subscription_rate numeric,
    ADD COLUMN IF NOT EXISTS industry          text,
    ADD COLUMN IF NOT EXISTS listing_method    text;

-- Silver calendar: price range + allocation extras
ALTER TABLE silver.unified_ipo_calendar
    ADD COLUMN IF NOT EXISTS offer_price_low      numeric,
    ADD COLUMN IF NOT EXISTS offer_price_high     numeric,
    ADD COLUMN IF NOT EXISTS lot_size             integer,
    ADD COLUMN IF NOT EXISTS one_lot_success_pct  numeric,
    ADD COLUMN IF NOT EXISTS funds_raised_hkd     numeric,
    ADD COLUMN IF NOT EXISTS data_source          text;

-- Silver performance: first-day OHLC + return_1d
ALTER TABLE silver.unified_ipo_performance
    ADD COLUMN IF NOT EXISTS offer_price        numeric,
    ADD COLUMN IF NOT EXISTS first_day_date     date,
    ADD COLUMN IF NOT EXISTS first_day_open     numeric,
    ADD COLUMN IF NOT EXISTS first_day_high     numeric,
    ADD COLUMN IF NOT EXISTS first_day_low      numeric,
    ADD COLUMN IF NOT EXISTS first_day_close    numeric,
    ADD COLUMN IF NOT EXISTS first_day_volume   bigint,
    ADD COLUMN IF NOT EXISTS return_1d          double precision;
