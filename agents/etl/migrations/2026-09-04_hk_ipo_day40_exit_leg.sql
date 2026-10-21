-- 2026-09-04_hk_ipo_day40_exit_leg.sql
-- Task t_bcd1f540: durable day-40 (exit-leg) columns on gold.hk_ipo_performance.
--
-- The post-listing drift rule enters at the 20th trading day and exits at the
-- 40th. The backend (hkex.py /api/hkex/ipos) currently computes the day-40
-- close per request via a LATERAL on silver.unified_prices (OFFSET 39). These
-- columns make the exit leg durable in gold, same handoff pattern as
-- return_day20_pct (t_e71cffde). Values are backfilled by
-- gold/ipo/build_ipo_data.py (SQL_PERFORMANCE) which now lands them from
-- silver.unified_prices with the recycled-ticker next-listing guard.

BEGIN;

ALTER TABLE gold.hk_ipo_performance
    ADD COLUMN IF NOT EXISTS return_day40_pct numeric(10,4),
    ADD COLUMN IF NOT EXISTS exit_day40_price numeric(10,4),
    ADD COLUMN IF NOT EXISTS exit_day40_date date;

COMMIT;
