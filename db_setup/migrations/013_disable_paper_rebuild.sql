-- ============================================================
-- Migration 013 — Allow strategies to opt out of automatic paper rebalancing.
--
-- Use case: strategies whose paper_trades_synthetic ledger is manually curated
-- (e.g. historical simulation ingestion). Setting disable_paper_rebuild=TRUE
-- prevents rebuild_paper_positions.py from closing/opening positions automatically.
--
-- Idempotent. Safe to re-run.
-- ============================================================

SET search_path = gold, public;
SET client_min_messages = WARNING;

ALTER TABLE gold.strategy_registry
    ADD COLUMN IF NOT EXISTS disable_paper_rebuild BOOLEAN NOT NULL DEFAULT FALSE;

-- Existing rows retain FALSE; only new/explicit opt-outs become TRUE.

COMMENT ON COLUMN gold.strategy_registry.disable_paper_rebuild IS
    'When TRUE, rebuild_paper_positions.py skips this strategy (manual ledger).';

GRANT UPDATE (disable_paper_rebuild) ON gold.strategy_registry TO openclaw_user;

DO $$
DECLARE n_enabled INT;
BEGIN
    SELECT COUNT(*) INTO n_enabled FROM gold.strategy_registry WHERE disable_paper_rebuild = TRUE;
    RAISE NOTICE 'Migration 013: disable_paper_rebuild column ready. Currently enabled for % strategies.', n_enabled;
END $$;
