-- ============================================================
-- Migration 006 — Bridge the strategy-id spaces (OPERATOR_NOTES.md P0-2).
--
-- Three id spaces coexist today:
--   gold.strategy_registry.strategy_id   VARCHAR semantic ids ("cl_cot_trend")
--   gold.strategy_backtests.strategy_id  SMALLINT (signal-agent numeric ids)
--   agents/signals registry.json         INTEGER ids 1-20
--
-- Consequence (verified live): update_strategy_registry.py joins
-- backtests.strategy_id::varchar = registry.strategy_id, which can never
-- match ("11" != "cl_cot_trend"), so OOS stats sync 0 rows and the frontend
-- shows "Trades (OOS): —" for nearly every strategy.
--
-- This migration adds the bridge column. It does NOT invent the mapping —
-- which numeric backtest id corresponds to which semantic registry id is
-- operator knowledge (qr_research owns the backtest runs). Backfill with:
--
--   UPDATE gold.strategy_backtests
--   SET registry_strategy_id = '<semantic id>'
--   WHERE strategy_id = <numeric id>;
--
-- The sync scripts prefer registry_strategy_id when present and fall back
-- to the old (never-matching) cast otherwise, so partial backfill degrades
-- gracefully: mapped strategies sync, unmapped ones stay blank — honestly.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS. Safe to re-run.
-- ============================================================

SET search_path = gold, public;
SET client_min_messages = WARNING;

ALTER TABLE gold.strategy_backtests
    ADD COLUMN IF NOT EXISTS registry_strategy_id VARCHAR(50);

COMMENT ON COLUMN gold.strategy_backtests.registry_strategy_id IS
    'Semantic id in gold.strategy_registry this backtest belongs to. '
    'Backfilled by the operator (migration 006); NULL = unmapped, and '
    'unmapped backtests are excluded from registry OOS-stat sync.';

CREATE INDEX IF NOT EXISTS strategy_backtests_registry_id_idx
    ON gold.strategy_backtests (registry_strategy_id, run_date DESC)
    WHERE registry_strategy_id IS NOT NULL;

DO $$
DECLARE
    n_total  INTEGER;
    n_mapped INTEGER;
BEGIN
    SELECT COUNT(*), COUNT(registry_strategy_id)
    INTO n_total, n_mapped
    FROM gold.strategy_backtests;
    RAISE NOTICE 'Migration 006 complete: strategy_backtests bridge column ready (%/% rows mapped — backfill the rest per the header)', n_mapped, n_total;
END $$;
