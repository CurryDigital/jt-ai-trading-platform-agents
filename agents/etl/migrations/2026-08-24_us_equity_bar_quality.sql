-- 2026-08-24 (kanban t_d97f3b82): Guard Yahoo synthetic zero-volume flat bars
-- + surface them in a gold quality view.
--
-- Context: around corporate actions (AVB 2.793:1 merger exchange 2026-08-17;
-- EQR 2026-08-18; EA 2026-08-05..10, self-healed) Yahoo's v8 chart API serves
-- synthetic placeholder bars: volume=0, open=high=low=close pinned to the prior
-- close. These flowed bronze -> silver -> gold as if they were real sessions.
--
-- 1) bronze.yf_suspect_bars — quarantine for suspect rows withheld by the
--    ingest guard in bronze/yfinance/ingest_yfinance_prices.py. A row is
--    resolved (resolved_at set) when a real bar later lands for (ticker,date).
-- 2) gold.v_us_equity_bar_quality — row-level view over (a) zero-volume flat
--    bars already sitting in gold.daily_ohlcv (pre-guard contamination) and
--    (b) unresolved quarantined suspects. Downstream/frontend can alert on
--    zero_volume_flat_rows_total > 0.

BEGIN;

CREATE TABLE IF NOT EXISTS bronze.yf_suspect_bars (
    ticker          varchar(50)  NOT NULL,
    date            date         NOT NULL,
    open            numeric(18,8),
    high            numeric(18,8),
    low             numeric(18,8),
    close           numeric(18,8),
    volume          bigint,
    adjusted_close  numeric(18,8),
    reason          varchar(100) NOT NULL DEFAULT 'zero_volume_flat_placeholder',
    detected_at     timestamptz  NOT NULL DEFAULT now(),
    resolved_at     timestamptz,
    PRIMARY KEY (ticker, date)
);

CREATE OR REPLACE VIEW gold.v_us_equity_bar_quality AS
WITH us_equities AS (
    SELECT ticker
    FROM gold.asset_registry
    WHERE market = 'US'
      AND asset_class IN ('STOCK', 'ETF')
      AND is_active = TRUE
),
flat_gold AS (
    -- Pre-guard contamination already promoted to gold (AVB 2026-08-17..20,
    -- EQR 2026-08-18..20, EA 2026-08-05..10): volume=0 AND perfectly flat OHLC.
    SELECT d.ticker, d.date, d.open, d.high, d.low, d.close, d.volume,
           'gold.daily_ohlcv'::text AS layer
    FROM gold.daily_ohlcv d
    JOIN us_equities u USING (ticker)
    WHERE d.volume = 0
      AND d.open = d.high AND d.high = d.low AND d.low = d.close
),
flat_quarantine AS (
    -- Post-guard: suspects withheld from bronze and quarantined, still
    -- unresolved (Yahoo has not served a real bar yet).
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

COMMIT;
