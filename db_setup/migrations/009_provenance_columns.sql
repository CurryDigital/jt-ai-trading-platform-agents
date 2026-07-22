-- ============================================================
-- Migration 009 — Provenance columns (PIPELINE_DESIGN.md principle 1).
--
-- Make "where did this row come from" a first-class, queryable fact so an
-- estimate or a synthetic fill can never again be mistaken for a measurement
-- at the point of display. Two columns, both with a safe DEFAULT so existing
-- writers that omit them keep working unchanged:
--
--   gold.strategy_ticker_scores.signal_source  DEFAULT 'computed'
--       'computed' = criteria/S9/relative-momentum/paper-runner
--       'ingested' = from a qr_research live-signals JSON
--
--   gold.trade_executions.execution_source     DEFAULT 'real'
--       'real'      = actual broker fill
--       'synthetic' = modelled paper fill (e.g. backfill_strategy_live_data.py)
--
-- Vocabulary is mirrored in agents/etl/shared/scripts/quality.py.
--
-- BACKFILL is EVIDENCE-BASED, not guessed:
--   * ticker scores whose criteria_met JSON carries a 'source_signal_file'
--     key were written by an ingest script → 'ingested'; the rest 'computed'.
--   * trade_executions in a paper/sim mode with NO ibkr_order_id cannot be
--     real broker fills (a real IBKR fill always has an order id) → the
--     synthetic rows backfill_strategy_live_data.py wrote. Marked 'synthetic'.
--     ⚠️ OPERATOR: eyeball the counts the verify step prints before trusting
--     downstream "live P&L" — see OPERATOR_NOTES.md flag 6.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + guarded backfill. Safe to re-run.
-- ============================================================

SET search_path = gold, public;
SET client_min_messages = WARNING;

-- ── strategy_ticker_scores.signal_source ─────────────────────────────────
ALTER TABLE gold.strategy_ticker_scores
    ADD COLUMN IF NOT EXISTS signal_source VARCHAR(12) NOT NULL DEFAULT 'computed';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'strategy_ticker_scores_signal_source_chk'
    ) THEN
        ALTER TABLE gold.strategy_ticker_scores
            ADD CONSTRAINT strategy_ticker_scores_signal_source_chk
            CHECK (signal_source IN ('computed','ingested'));
    END IF;
END $$;

-- Evidence-based backfill: ingest scripts stamp source_signal_file in criteria_met.
UPDATE gold.strategy_ticker_scores
SET signal_source = 'ingested'
WHERE signal_source = 'computed'
  AND criteria_met::text LIKE '%source_signal_file%';

-- ── trade_executions.execution_source ────────────────────────────────────
ALTER TABLE gold.trade_executions
    ADD COLUMN IF NOT EXISTS execution_source VARCHAR(12) NOT NULL DEFAULT 'real';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'trade_executions_execution_source_chk'
    ) THEN
        ALTER TABLE gold.trade_executions
            ADD CONSTRAINT trade_executions_execution_source_chk
            CHECK (execution_source IN ('real','synthetic'));
    END IF;
END $$;

-- Evidence-based backfill: a paper/sim fill with no broker order id is not a
-- real fill. Real IBKR fills always carry ibkr_order_id.
UPDATE gold.trade_executions
SET execution_source = 'synthetic'
WHERE execution_source = 'real'
  AND execution_mode IN ('PAPER','SIMULATION','paper','simulation')
  AND (ibkr_order_id IS NULL OR ibkr_order_id = '');

-- ── consumption: real-only execution views for the detail page ───────────
-- The detail page's "Live WR / Live P&L" must count only REAL fills; today
-- it treats synthetic rows (and open, unrealized positions) as if they were
-- realized live trades. This view is the honest source for live metrics.
CREATE OR REPLACE VIEW consumption.execution_fills_real AS
SELECT
    id::VARCHAR              AS fill_id,
    ibkr_order_id::VARCHAR    AS order_id,
    strategy_id,
    ticker,
    quantity::NUMERIC        AS qty,
    price::NUMERIC            AS price,
    pnl::NUMERIC             AS pnl,
    pnl_pct::NUMERIC         AS pnl_pct,
    executed_at              AS ts
FROM gold.trade_executions
WHERE execution_source = 'real'
ORDER BY executed_at DESC;

GRANT SELECT ON consumption.execution_fills_real TO openclaw_user;

DO $$
DECLARE
    n_ingested INTEGER; n_computed INTEGER;
    n_synth INTEGER; n_real INTEGER;
BEGIN
    SELECT COUNT(*) FILTER (WHERE signal_source='ingested'),
           COUNT(*) FILTER (WHERE signal_source='computed')
      INTO n_ingested, n_computed FROM gold.strategy_ticker_scores;
    SELECT COUNT(*) FILTER (WHERE execution_source='synthetic'),
           COUNT(*) FILTER (WHERE execution_source='real')
      INTO n_synth, n_real FROM gold.trade_executions;
    RAISE NOTICE 'Migration 009 complete.';
    RAISE NOTICE '  strategy_ticker_scores: % ingested / % computed', n_ingested, n_computed;
    RAISE NOTICE '  trade_executions: % SYNTHETIC / % real  <-- operator: verify the synthetic count matches backfill_strategy_live_data expectations', n_synth, n_real;
END $$;
