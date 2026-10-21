-- 2026-09-17_hk_ipo_performance_ticker_unique.sql
-- Task t_a6b7e5aa: gold.hk_ipo_performance had 2 rows each for recycled
-- tickers 2076.HK (listings 2022-12-22 + 2025-07-04) and 9868.HK
-- (2021-07-07 + 2024-01-15). Every backend consumer (hkex.py, 6 sites)
-- joins on ticker ONLY -> fan-out (GET /api/hkex/ipos returned 1928 rows
-- instead of 1926, doubled aggregates).
--
-- gold.hk_ipo_calendar is keyed on ticker (frontend convention: LATEST
-- listing). gold.hk_ipo_performance now follows the same contract:
-- exactly one row per ticker, for the canonical (calendar) listing_date.
-- Generator filter added in gold/ipo/build_ipo_data.py (SQL_PERFORMANCE);
-- per-event history remains in silver.unified_ipo_performance.
--
-- 1) drop non-canonical rows
-- 2) unique index so any future generator regression fails loudly instead
--    of silently re-duping the API.

BEGIN;

DELETE FROM gold.hk_ipo_performance p
WHERE p.listing_date <> (
    SELECT c.listing_date FROM gold.hk_ipo_calendar c
    WHERE c.ticker = p.ticker
);

CREATE UNIQUE INDEX IF NOT EXISTS hk_ipo_performance_ticker_uidx
    ON gold.hk_ipo_performance (ticker);

COMMIT;
