-- ============================================================
-- Migration 008 — Per-strategy signal HISTORY for the detail page.
--
-- The detail page's Signals tab currently reads
-- consumption.strategies_signals_current, a latest-snapshot table
-- (one row per strategy/ticker, overwritten every cycle) — which is why
-- every signal shows the same "12h" age and there is no YTD list.
--
-- The append-only source already exists: gold.strategy_ticker_scores_history
-- (migration 005, snapshotted at the end of every signal cycle since
-- 2026-07-17). This view exposes it in the same vocabulary the frontend
-- uses (signal / signal_strength / confidence_score / price), one row per
-- strategy/ticker/day.
--
-- HONESTY NOTE: history begins at the first snapshot (2026-07-17). Days
-- before that do not exist and are NOT reconstructed here — a YTD panel
-- will genuinely start shallow and deepen daily. Backfilling pre-snapshot
-- "history" from anything else would be fabrication.
--
-- Also adds consumption.strategies_trades_history over
-- gold.paper_trades_synthetic (both open and closed paper positions with
-- real entry/exit prices), so the Trades tab can list the accumulated
-- paper ledger per strategy instead of only what happened today.
--
-- Idempotent: CREATE OR REPLACE VIEW. Safe to re-run.
-- Requires: migration 005 (strategy_ticker_scores_history).
-- ============================================================

SET search_path = consumption, gold, public;
SET client_min_messages = WARNING;

CREATE OR REPLACE VIEW consumption.strategies_signal_history AS
SELECT
    h.strategy_id,
    h.ticker,
    h.snapshot_date                                   AS signal_date,
    COALESCE(h.signal_action, 'HOLD')                 AS signal,
    ROUND(COALESCE(h.score, 0), 0)                    AS signal_strength,   -- 0-100
    ROUND(COALESCE(h.entry_score, h.score, 0), 0)     AS confidence_score,  -- 0-100
    p.close                                           AS price_on_date,
    h.snapshotted_at
FROM gold.strategy_ticker_scores_history h
LEFT JOIN LATERAL (
    SELECT close FROM silver.unified_prices up
    WHERE up.ticker = h.ticker AND up.date <= h.snapshot_date
      AND up.close IS NOT NULL
    ORDER BY up.date DESC
    LIMIT 1
) p ON TRUE
ORDER BY h.strategy_id, h.snapshot_date DESC, h.ticker;

CREATE OR REPLACE VIEW consumption.strategies_trades_history AS
SELECT
    t.strategy_id,
    t.ticker,
    t.direction,
    t.status,                       -- 'open' | 'closed'
    t.entry_date,
    t.entry_price,
    t.exit_date,
    t.exit_price,
    t.n_shares,
    t.pnl,
    t.pnl_pct,
    t.signal_weight,
    t.assigned_capital,
    t.created_at
FROM gold.paper_trades_synthetic t
ORDER BY t.strategy_id, t.entry_date DESC, t.ticker;

GRANT SELECT ON consumption.strategies_signal_history  TO openclaw_user;
GRANT SELECT ON consumption.strategies_trades_history  TO openclaw_user;

DO $$
DECLARE
    n_sig   INTEGER;
    n_days  INTEGER;
    n_trd   INTEGER;
BEGIN
    SELECT COUNT(*), COUNT(DISTINCT signal_date) INTO n_sig, n_days
    FROM consumption.strategies_signal_history;
    SELECT COUNT(*) INTO n_trd FROM consumption.strategies_trades_history;
    RAISE NOTICE 'Migration 008 complete: signal_history % rows over % days; trades_history % rows', n_sig, n_days, n_trd;
END $$;
