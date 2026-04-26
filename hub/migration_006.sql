-- ============================================================
-- Migration 006 — Tier 1 unblock
--   1. Re-seed risk_config with names that match what
--      qr_risk and qr_qa actually look up at runtime.
--   2. Add clear_stale_gold_lock() so qr_monitor can
--      auto-recover from a gold layer wedged in 'locked'.
--   3. Wire qr_debate into routing as a parallel observer
--      of risk.evaluated (does NOT block qr_qa).
-- Idempotent: safe to re-run.
-- ============================================================

SET search_path = openclaw_researcher, public;

-- ────────────────────────────────────────────────────────────
-- 1. risk_config — replace mismatched seed values
-- ────────────────────────────────────────────────────────────
-- The earlier seeds used names ('max_drawdown', 'min_sharpe_oos', …)
-- that do not match what risk_agent.py / qa_agent.py look up by key.
-- Risk agent expects: high_drawdown, low_sharpe_oos, concentration_risk,
--                     overfitting_signal, low_trade_count, tail_risk
-- QA agent expects:   qa_min_sharpe_oos, qa_max_drawdown,
--                     qa_min_trade_count_oos, qa_min_sharpe_ratio_is_oos
-- Each entry is "operator + value" such that check_threshold(metric, op, value)
-- returns TRUE when the gate is BREACHED.

-- Drop legacy mismatched names so they can't shadow the correct ones.
DELETE FROM risk_config
WHERE name IN (
    'max_drawdown',
    'min_sharpe_oos',
    'min_sharpe_ratio',
    'high_turnover'
);

-- Risk gates (qr_risk reads `name NOT LIKE 'qa_%'`)
INSERT INTO risk_config (name, operator, value, description, enabled) VALUES
    ('high_drawdown',      '<',  -0.20, 'Flag if max_drawdown drops below -20%',                  TRUE),
    ('low_sharpe_oos',     '<',   0.50, 'Flag if OOS Sharpe is below 0.50',                       TRUE),
    ('concentration_risk', '>',   0.30, 'Flag if any single asset exceeds 30% exposure',          TRUE),
    ('overfitting_signal', '<',   0.60, 'Flag if IS/OOS Sharpe ratio collapses below 0.60',       TRUE),
    ('low_trade_count',    '<',   30,   'Flag if OOS trade count is below 30 (weak statistics)',  TRUE),
    ('tail_risk',          '>',   0.10, 'Flag if CVaR(95%) exceeds 10%',                          TRUE)
ON CONFLICT (name) DO UPDATE SET
    operator    = EXCLUDED.operator,
    value       = EXCLUDED.value,
    description = EXCLUDED.description,
    enabled     = EXCLUDED.enabled,
    updated_at  = NOW();

-- QA gates (qr_qa reads `name LIKE 'qa_%'`)
-- QA fails the gate when check_threshold(metric, op, value) is TRUE,
-- so the operator/value combo is "fail condition" not "pass condition".
INSERT INTO risk_config (name, operator, value, description, enabled) VALUES
    ('qa_min_sharpe_oos',          '<',   0.50, 'QA gate 2: fail if sharpe_oos < 0.50',                 TRUE),
    ('qa_max_drawdown',            '>',   0.20, 'QA gate 3: fail if |max_drawdown| > 0.20',             TRUE),
    ('qa_min_trade_count_oos',     '<',   30,   'QA gate 4: fail if trade_count_oos < 30',              TRUE),
    ('qa_min_sharpe_ratio_is_oos', '<',   0.60, 'QA gate 5: fail if sharpe_ratio_is_oos < 0.60',        TRUE)
ON CONFLICT (name) DO UPDATE SET
    operator    = EXCLUDED.operator,
    value       = EXCLUDED.value,
    description = EXCLUDED.description,
    enabled     = EXCLUDED.enabled,
    updated_at  = NOW();

-- ────────────────────────────────────────────────────────────
-- 2. clear_stale_gold_lock() — auto-recover wedged ETL locks
-- ────────────────────────────────────────────────────────────
-- The data validator skips events while gold_layer_state.state='locked'
-- and intentionally does NOT mark them processed, so that they retry
-- once ETL completes. If the ETL Manager crashes mid-refresh, the lock
-- is never cleared and validators loop forever. qr_monitor calls this
-- function on every heartbeat to break the deadlock.
CREATE OR REPLACE FUNCTION clear_stale_gold_lock(p_max_lock_hours INTEGER DEFAULT 12)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_cleared INTEGER := 0;
BEGIN
    UPDATE gold_layer_state
       SET state        = 'stale',
           locked_since = NULL,
           notes        = 'Auto-unlocked by qr_monitor after ' || p_max_lock_hours
                          || 'h: ETL refresh did not complete. Original notes: '
                          || COALESCE(notes, ''),
           updated_at   = NOW()
     WHERE state = 'locked'
       AND locked_since IS NOT NULL
       AND locked_since < NOW() - (p_max_lock_hours || ' hours')::INTERVAL;

    GET DIAGNOSTICS v_cleared = ROW_COUNT;
    RETURN v_cleared;
END $$;

COMMENT ON FUNCTION clear_stale_gold_lock(INTEGER) IS
    'Auto-clears gold_layer_state.locked rows older than p_max_lock_hours. '
    'Called from qr_monitor heartbeat. Returns rows updated.';

-- Make it visible to the agent role.
GRANT EXECUTE ON FUNCTION clear_stale_gold_lock(INTEGER) TO openclaw_user;

-- ────────────────────────────────────────────────────────────
-- 3. Routing — qr_debate as parallel observer of risk.evaluated
-- ────────────────────────────────────────────────────────────
-- qr_qa already consumes risk.evaluated directly (no debate dependency).
-- We add qr_debate as a *second* target so it runs in parallel and
-- emits debate.completed for telemetry. QA does not wait for it.
INSERT INTO routing_rules (event_type, domain, target_agent, enabled)
VALUES ('risk.evaluated', 'quant', 'qr_debate', TRUE)
ON CONFLICT (event_type, domain, target_agent) DO UPDATE
    SET enabled    = TRUE,
        updated_at = NOW();

-- And a routing rule for debate.completed → noop sink (audit only).
-- We keep this off-by-default to avoid creating dead-end events.
INSERT INTO routing_rules (event_type, domain, target_agent, enabled)
VALUES ('debate.completed', 'quant', 'qr_monitor', FALSE)
ON CONFLICT (event_type, domain, target_agent) DO NOTHING;

DO $$
BEGIN
    RAISE NOTICE 'Migration 006 complete. risk_config seeded with agent-aligned names; '
                 'clear_stale_gold_lock() created; qr_debate wired as parallel observer.';
END $$;
