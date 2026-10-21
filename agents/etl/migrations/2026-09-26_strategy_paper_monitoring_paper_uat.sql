-- Migration: 2026-09-26
-- Purpose: FIX monitoring trigger design gap (kanban t_a44c50e1, follow-up of
--          t_fbbde37e / crisis_safe_haven_vt_19 orphan incident).
--
-- Root cause: 2026-07-25_v_pipeline_ui_feed_current_year_wr_paper_monitoring.sql
-- synced gold.strategy_paper_monitoring.is_active with STRICT equality
-- execution_mode = 'PAPER'. A PAPER_UAT sleeve therefore ALWAYS showed
-- monitoring off: promoting crisis_safe_haven_vt_19 PAPER -> PAPER_UAT on
-- 2026-08-31 auto-darkened its monitoring (deactivated_at 2026-08-31 22:04),
-- and the dark UI later motivated flipping the registry to SIMULATION to
-- 'match' (t_fcfe5f4f) while the UAT account still held $52k.
--
-- Decision (recorded in t_a44c50e1, 2026-09-25): monitoring ON for PAPER_UAT —
-- it is a live rehearsal track that needs MORE monitoring, not less.
--
-- Changes:
--  1. Trigger predicate: execution_mode IN ('PAPER', 'PAPER_UAT').
--  2. Reseed gold.strategy_paper_monitoring under the new predicate so any
--     existing PAPER_UAT rows flip active immediately (idempotent).
--
-- The v_pipeline_ui_feed view needs no change: it reads is_active from
-- gold.strategy_paper_monitoring; the mode column already renders
-- 'PAPER_TRADING' whenever is_paper_monitoring is true.

CREATE OR REPLACE FUNCTION gold.trg_sync_strategy_paper_monitoring()
RETURNS TRIGGER AS $$
DECLARE
    -- PAPER_UAT is a live rehearsal track (broker-facing) and must be
    -- monitored at least as strictly as PAPER (kanban t_a44c50e1).
    v_active boolean := (NEW.execution_mode IN ('PAPER', 'PAPER_UAT')
                         AND NEW.status NOT IN ('paused', 'retired'));
BEGIN
    IF v_active THEN
        INSERT INTO gold.strategy_paper_monitoring
            (strategy_id, is_active, activated_at, deactivated_at, updated_at)
        VALUES
            (NEW.strategy_id, TRUE, NOW(), NULL, NOW())
        ON CONFLICT (strategy_id) DO UPDATE SET
            is_active      = TRUE,
            activated_at   = COALESCE(gold.strategy_paper_monitoring.activated_at, NOW()),
            deactivated_at = NULL,
            updated_at     = NOW();
    ELSE
        INSERT INTO gold.strategy_paper_monitoring
            (strategy_id, is_active, activated_at, deactivated_at, updated_at)
        VALUES
            (NEW.strategy_id, FALSE, NULL, NOW(), NOW())
        ON CONFLICT (strategy_id) DO UPDATE SET
            is_active      = FALSE,
            deactivated_at = COALESCE(gold.strategy_paper_monitoring.deactivated_at, NOW()),
            updated_at     = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger itself is unchanged (same name/events); the function body carries
-- the fix. Re-assert for completeness.
DROP TRIGGER IF EXISTS trg_sync_strategy_paper_monitoring ON gold.strategy_registry;
CREATE TRIGGER trg_sync_strategy_paper_monitoring
    AFTER INSERT OR UPDATE OF execution_mode, status ON gold.strategy_registry
    FOR EACH ROW
    EXECUTE FUNCTION gold.trg_sync_strategy_paper_monitoring();

-- Reseed under the new predicate (idempotent).
INSERT INTO gold.strategy_paper_monitoring
    (strategy_id, is_active, activated_at, deactivated_at, updated_at)
SELECT
    strategy_id,
    (execution_mode IN ('PAPER', 'PAPER_UAT') AND status NOT IN ('paused', 'retired')),
    CASE WHEN execution_mode IN ('PAPER', 'PAPER_UAT') AND status NOT IN ('paused', 'retired') THEN NOW() ELSE NULL END,
    CASE WHEN execution_mode NOT IN ('PAPER', 'PAPER_UAT') OR status IN ('paused', 'retired') THEN NOW() ELSE NULL END,
    NOW()
FROM gold.strategy_registry
ON CONFLICT (strategy_id) DO UPDATE SET
    is_active      = EXCLUDED.is_active,
    activated_at   = COALESCE(gold.strategy_paper_monitoring.activated_at, EXCLUDED.activated_at),
    deactivated_at = COALESCE(gold.strategy_paper_monitoring.deactivated_at, EXCLUDED.deactivated_at),
    updated_at     = NOW();

COMMENT ON FUNCTION gold.trg_sync_strategy_paper_monitoring() IS
    'Keeps gold.strategy_paper_monitoring in sync with strategy_registry. '
    'Monitored := execution_mode IN (PAPER, PAPER_UAT) AND status NOT IN (paused, retired). '
    'PAPER_UAT included since 2026-09-26 (kanban t_a44c50e1): strict-PAPER equality '
    'auto-darkened monitoring on PAPER->PAPER_UAT promotion and masked a $52k UAT orphan.';
