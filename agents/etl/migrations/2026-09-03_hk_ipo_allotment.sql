-- 2026-09-03 (kanban t_49215d54): HK IPO allotment results (one-lot win rate,
-- tier allocation tables, clawback / final retail tranche).
--
-- Source: HKEXnews "ALLOTMENT RESULTS" announcements (standardized template:
-- "ALLOTMENT RESULTS DETAILS" summary box + "BASIS OF ALLOCATION" tier tables).
-- Settles the open question blocking the S2 IPO subscription strategy.
--
-- 1. bronze.hkex_ipo_allotment_raw: resumable audit, one row per attempted IPO.
-- 2. silver.hk_ipo_allotment: clean per-IPO allotment mechanics.

CREATE TABLE IF NOT EXISTS bronze.hkex_ipo_allotment_raw (
    ticker_code     text NOT NULL,               -- '02550' (5-digit zero-padded)
    listing_date    date NOT NULL,
    status          text NOT NULL,               -- ok | partial_summary | partial_table
                                                 -- | no_stock_id | no_allot_doc
                                                 -- | parse_fail | error
    payload         jsonb,                       -- full parsed dict (pools, summary)
    doc_url         text,
    doc_title       text,
    snippet         text,
    error           text,
    stock_id        text,
    n_docs          integer,
    attempted_at    timestamptz DEFAULT now(),
    PRIMARY KEY (ticker_code, listing_date)
);

CREATE TABLE IF NOT EXISTS silver.hk_ipo_allotment (
    ticker                        varchar(10)  NOT NULL,   -- '2550.HK'
    listing_date                  date         NOT NULL,
    one_lot_win_rate              numeric(8,2),            -- %, pool-A first tier ballot
    allotment_table               jsonb,                   -- {pool_a:[...], pool_b:[...]}
    retail_valid_applications     integer,
    retail_successful_applications integer,
    oversub_retail_ann            numeric(14,2),           -- announcement "Subscription level"
    oversub_intl_ann              numeric(14,2),
    clawback_triggered            boolean,
    retail_shares_initial         bigint,
    retail_shares_reallocated     bigint,
    retail_shares_final           bigint,
    retail_pct_final              numeric(6,2),            -- % of global offering (post-clawback)
    source_url                    text,
    parse_status                  text NOT NULL,
    scraped_at                    timestamptz DEFAULT now(),
    PRIMARY KEY (ticker, listing_date)
);

CREATE INDEX IF NOT EXISTS ix_hk_ipo_allotment_date
    ON silver.hk_ipo_allotment (listing_date);

-- 3. gold consumption view (research agents read gold.*; allotment rows are
--    immutable post-listing so a live view is sufficient, no promote step).
CREATE OR REPLACE VIEW gold.hk_ipo_allotment AS
SELECT ticker, listing_date, one_lot_win_rate, allotment_table,
       retail_valid_applications, retail_successful_applications,
       oversub_retail_ann, oversub_intl_ann, clawback_triggered,
       retail_shares_initial, retail_shares_reallocated, retail_shares_final,
       retail_pct_final, source_url, parse_status, scraped_at
FROM silver.hk_ipo_allotment;
