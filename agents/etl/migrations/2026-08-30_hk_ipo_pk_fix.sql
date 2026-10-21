-- 2026-08-30_hk_ipo_pk_fix.sql
-- Task t_3ad38fa3: fix duplicate-ticker PK ambiguity in HK IPO tables.
-- 12 tickers have multiple calendar listings (recycled tickers); performance
-- and gold tables keyed on ticker only collapse them into one arbitrary row.
--
-- 1) silver.unified_ipo_performance: ipo_date -> listing_date, PK (ticker, listing_date)
-- 2) gold.hk_ipo_performance: PK (ticker) -> (ticker, listing_date)

BEGIN;

ALTER TABLE silver.unified_ipo_performance
    RENAME COLUMN ipo_date TO listing_date;
ALTER TABLE silver.unified_ipo_performance
    DROP CONSTRAINT unified_ipo_performance_pkey;
ALTER TABLE silver.unified_ipo_performance
    ADD CONSTRAINT unified_ipo_performance_pkey PRIMARY KEY (ticker, listing_date);

ALTER TABLE gold.hk_ipo_performance
    DROP CONSTRAINT hk_ipo_performance_pkey;
ALTER TABLE gold.hk_ipo_performance
    ADD CONSTRAINT hk_ipo_performance_pkey PRIMARY KEY (ticker, listing_date);

-- gold.hk_ipo_calendar must mirror silver cardinality: 116 silver rows have
-- no offer_price (unknown at source), so the NOT NULL constraint is wrong.
ALTER TABLE gold.hk_ipo_calendar ALTER COLUMN offer_price DROP NOT NULL;
-- same on gold.hk_ipo_performance (107 silver performance rows lack offer_price)
ALTER TABLE gold.hk_ipo_performance ALTER COLUMN offer_price DROP NOT NULL;

COMMIT;
