-- ============================================================
-- 015_signal_setups_price_note.sql  (t_071207e4, 2026-08-05)
--
-- consumption.signal_setups:
--   1. ADD `price` — latest close from gold.daily_ohlcv per ticker, so
--      GET /api/signals/universe can return price alongside change_pct.
--      All 120 current signal_evaluations tickers have daily_ohlcv
--      coverage (verified 2026-08-05). Appended as the LAST column so
--      CREATE OR REPLACE VIEW succeeds without dropping dependents.
--   2. CLEAN `note` — engine-config JSON blobs ({"engine": ...,
--      "config_rank": ...}) are NULLed at the view so the UI shows
--      nothing instead of config junk. Source fix lives in
--      build_signal_redesign.py (stops writing JSON into
--      gold.signal_evaluations.note); this view guard protects against
--      any legacy rows or future writers.
-- ============================================================

SET search_path = consumption, gold, public;

CREATE OR REPLACE VIEW consumption.signal_setups AS
SELECT
    e.market,
    e.ticker,
    MAX(e.name)                                     AS name,
    ARRAY_AGG(e.family_key ORDER BY e.family_key)   AS families,
    -- Direction wins ties by majority; ARRAY_AGG keeps audit; UI uses majority.
    MODE() WITHIN GROUP (ORDER BY e.direction)      AS direction,
    AVG(e.potential)::NUMERIC(6,2)                  AS potential,
    AVG(e.change_pct)::NUMERIC(8,4)                 AS change_pct,
    -- Concatenate distinct human notes; JSON engine-config blobs are
    -- pre-NULLed in the subquery (string_agg skips NULLs; all-NULL -> NULL).
    LEFT(STRING_AGG(DISTINCT e.clean_note, ' · ' ORDER BY e.clean_note), 200) AS note,
    MAX(e.updated_at)                               AS updated_at,
    -- Latest close; constant per ticker, so MAX() is just the group reducer.
    MAX(px.close)::NUMERIC(14,4)                    AS price
FROM (
    SELECT *,
           CASE WHEN note LIKE '{%' THEN NULL ELSE note END AS clean_note
    FROM gold.signal_evaluations
) e
LEFT JOIN LATERAL (
    SELECT d.close
    FROM gold.daily_ohlcv d
    WHERE d.ticker = e.ticker
    ORDER BY d.date DESC
    LIMIT 1
) px ON TRUE
GROUP BY e.market, e.ticker
ORDER BY e.market, potential DESC;
