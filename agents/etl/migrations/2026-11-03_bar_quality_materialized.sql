-- 2026-11-03 (kanban t_96e90169): Convert gold.v_us_equity_bar_quality from a
-- plain VIEW to a MATERIALIZED VIEW (same name, same columns).
--
-- Incident: /api/system/freshness (backend app/main.py) aggregates this view on
-- every frontend poll. As a plain view, the flat_gold branch was a parallel
-- sequential scan of gold.daily_ohlcv (4.3M rows / ~800MB) per call:
--   - 608k rows match volume=0; 538k match the full flat predicate globally
--     (legit zero-trade days, mostly non-US) — a partial index on volume=0 is
--     NOT selective enough (planner correctly ignored it).
--   - Only ~1.1k rows survive the us_equities (US active STOCK/ETF) join.
-- Frontend 10s aborts do not cancel server-side queries, so each poll added
-- another multi-minute scan; 11 concurrent leaders + parallel workers
-- saturated the burstable RDS (16:20-16:40 UTC) and starved all other
-- endpoints (/api/system/health db:unreachable, overview >10s, gateway 500).
--
-- Fix: materialize the row set (1,224 rows as of 2026-11-03) and refresh it
-- via agents/etl/gold/refresh_bar_quality_mv.py (cron qr_etl.bar_quality_mv_refresh,
-- after pipeline A 08:30 UTC and after yf_us_postclose_topup 22:30 UTC).
-- Backend aggregate latency: 100s+ -> ~0.1s. No consumer changes needed.
--
-- NOTE: idx_gold_daily_ohlcv_zerovol_flat (partial, WHERE volume=0), created
-- during incident triage, was dropped — 608k entries, not selective, pure
-- write overhead on the ingest-hot table.

BEGIN;

DROP VIEW IF EXISTS gold.v_us_equity_bar_quality;

CREATE MATERIALIZED VIEW gold.v_us_equity_bar_quality AS
WITH us_equities AS (
    SELECT ticker
    FROM gold.asset_registry
    WHERE market = 'US'
      AND asset_class IN ('STOCK', 'ETF')
      AND is_active = TRUE
),
flat_gold AS (
    SELECT d.ticker, d.date, d.open, d.high, d.low, d.close, d.volume,
           'gold.daily_ohlcv'::text AS layer
    FROM gold.daily_ohlcv d
    JOIN us_equities u USING (ticker)
    WHERE d.volume = 0
      AND d.open = d.high AND d.high = d.low AND d.low = d.close
),
flat_quarantine AS (
    SELECT s.ticker, s.date, s.open, s.high, s.low, s.close, s.volume,
           'bronze.yf_suspect_bars'::text AS layer
    FROM bronze.yf_suspect_bars s
    JOIN us_equities u USING (ticker)
    WHERE s.resolved_at IS NULL
),
all_flat AS (
    SELECT * FROM flat_gold
    UNION ALL
    SELECT * FROM flat_quarantine
)
SELECT
    a.ticker                                                      AS offending_ticker,
    a.date,
    a.open, a.high, a.low, a.close, a.volume,
    a.layer,
    (SELECT max(date) FROM all_flat)                              AS latest_suspect_date,
    COUNT(*) OVER ()                                              AS zero_volume_flat_rows_total,
    COUNT(*) OVER (PARTITION BY a.ticker)                         AS ticker_suspect_rows
FROM all_flat a
ORDER BY a.date DESC, a.ticker;

-- (offending_ticker, date, layer) is unique across both branches
-- (each branch keyed on (ticker,date)); enables REFRESH ... CONCURRENTLY.
CREATE UNIQUE INDEX idx_v_us_equity_bar_quality_uq
    ON gold.v_us_equity_bar_quality (offending_ticker, date, layer);

DROP INDEX IF EXISTS gold.idx_gold_daily_ohlcv_zerovol_flat;

COMMIT;
