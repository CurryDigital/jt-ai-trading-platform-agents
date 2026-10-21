-- 2026-09-05 (kanban t_59228b1e): pre-subscription filings feed (HKEXnews A1/PHIP)
--
-- Problem: IPO tab ANNOUNCED stage was always empty because gold.hk_ipo_calendar
-- only gained rows once application/listing dates existed (NLR + AAStocks feeds).
-- HK IPOs that have filed (A1 application proof / PHIP) but not yet opened
-- subscription never appeared.
--
-- Fix:
--   1. gold.hk_ipo_calendar.listing_date DROP NOT NULL so pre-subscription
--      placeholder rows (listing_date NULL, offer_price NULL, application
--      dates NULL) can be stored; frontend stageOf() classifies those as
--      'announced'. offer_price was already nullable.
--   2. bronze.hkex_ipo_appindex_raw  - raw HKEXnews appindex JSON snapshots.
--   3. silver.hk_ipo_filings         - normalized filing tracker (one row per
--      HKEX applicant id + board), reconciled to real stock codes via the
--      HKEXnews 'listed' appindex file (deterministic id -> st mapping).

BEGIN;

ALTER TABLE gold.hk_ipo_calendar ALTER COLUMN listing_date DROP NOT NULL;

CREATE TABLE IF NOT EXISTS bronze.hkex_ipo_appindex_raw (
    id          bigserial PRIMARY KEY,
    file_name   text NOT NULL,           -- e.g. appactive_app_sehk_e.json
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    payload     jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS hkex_ipo_appindex_raw_file_fetched
    ON bronze.hkex_ipo_appindex_raw (file_name, fetched_at DESC);

CREATE TABLE IF NOT EXISTS silver.hk_ipo_filings (
    applicant_id       bigint NOT NULL,           -- HKEXnews appindex 'id'
    board              varchar(4) NOT NULL,       -- 'MAIN' | 'GEM'
    company_name_en    varchar(255) NOT NULL,
    company_name_zh    varchar(255),
    filing_stage       varchar(4) NOT NULL,       -- 'A1' | 'PHIP'
    first_filing_date  date,                      -- earliest Application Proof doc
    latest_event_date  date,                      -- appindex 'd' (latest doc date)
    phip_date          date,                      -- latest PHIP doc date (PHIP rows)
    listed_stock_code  varchar(5),                -- from applisted 'st', once listed
    status             varchar(10) NOT NULL DEFAULT 'active',  -- active | listed | lapsed
    source_udate       date,                      -- feed 'uDate' (feed freshness)
    first_seen_at      timestamp NOT NULL DEFAULT now(),
    updated_at         timestamp NOT NULL DEFAULT now(),
    PRIMARY KEY (board, applicant_id)
);

COMMIT;
