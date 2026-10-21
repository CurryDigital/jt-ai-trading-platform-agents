-- 2026-09-21 (kanban t_0013f4cc): purge NULL-close no-bar rows + enforce close NOT NULL
--
-- Root cause: pre-2026-07-10 bronze yfinance ingest wrote Yahoo's all-NaN
-- weekend/holiday frame rows (P1-7 guard added 2026-07-10 stopped new ones),
-- and a 2026-07-04 one-off universe backfill wrote pre-listing calendar-grid
-- placeholders for FNGU/FBTC/IBIT/JEPQ/BITO. clean_unified_prices.py merged
-- them into silver with no NULL filter; its simple-path GREATEST(close,0.0001)
-- log-return hack then fabricated returns_log ~= -15.8 on those rows.
-- Impact (qr_research audit 2026-09-18): rolling indicators go NaN for a full
-- window after each NULL row (SMA200 dead 200d); same strategy + same DB gave
-- 34 vs 48 OOS trades, Sharpe 0.57 vs 1.00, depending on dropna.
--
-- 3 partial rows (BA 2026-06-03, BR 2026-06-01/02: OHLC set, close/volume
-- NULL) were repaired from a fresh Yahoo fetch BEFORE this migration; the
-- remaining 7,120 rows are pure no-bar rows (all OHLCV NULL) and are deleted.

BEGIN;

-- 1. Silver: delete no-bar rows
DELETE FROM silver.unified_prices WHERE close IS NULL;

-- 2. Bronze: delete the same residue so no future merge/oneoff re-promotes it
DELETE FROM bronze.yf_prices WHERE close IS NULL;

-- 3. DB-level enforcement: a price row without a close is meaningless and
--    must fail loudly at insert time, not land silently.
ALTER TABLE silver.unified_prices ALTER COLUMN close SET NOT NULL;
ALTER TABLE bronze.yf_prices     ALTER COLUMN close SET NOT NULL;

COMMIT;
