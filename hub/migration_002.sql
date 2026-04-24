-- ============================================================
-- Migration 002 — Fix errors from migration_001
-- Safe to run multiple times (idempotent).
-- ============================================================

SET search_path = openclaw_researcher, public;

-- ────────────────────────────────────────────────────────────
-- Fix 1: risk_config — table exists with different column name.
-- Check actual column name and insert using correct name.
-- ────────────────────────────────────────────────────────────
DO $$
DECLARE
    col_name TEXT;
BEGIN
    -- Find whatever the name column is actually called
    SELECT column_name INTO col_name
    FROM information_schema.columns
    WHERE table_schema = 'openclaw_researcher'
      AND table_name   = 'risk_config'
      AND column_name IN ('threshold_name', 'name')
    LIMIT 1;

    IF col_name = 'name' THEN
        -- Table uses 'name' column — insert with that
        EXECUTE $q$
            INSERT INTO risk_config (name, operator, value, description) VALUES
                ('max_drawdown',      '<',  -0.20, 'Max drawdown must not exceed -20%'),
                ('min_sharpe_oos',    '>',   0.50, 'OOS Sharpe must be above 0.5'),
                ('min_sharpe_ratio',  '>',   0.60, 'IS/OOS Sharpe ratio must be above 0.60'),
                ('high_turnover',     '<',   2.00, 'Annualised turnover must be below 200%'),
                ('low_trade_count',   '>',   30,   'OOS trade count must exceed 30'),
                ('tail_risk',         '<',   0.10, 'CVaR (95%) must be below 10%')
            ON CONFLICT (name) DO NOTHING
        $q$;
        RAISE NOTICE 'risk_config: inserted using column name=name';
    ELSIF col_name = 'threshold_name' THEN
        EXECUTE $q$
            INSERT INTO risk_config (threshold_name, operator, value, description) VALUES
                ('max_drawdown',      '<',  -0.20, 'Max drawdown must not exceed -20%'),
                ('min_sharpe_oos',    '>',   0.50, 'OOS Sharpe must be above 0.5'),
                ('min_sharpe_ratio',  '>',   0.60, 'IS/OOS Sharpe ratio must be above 0.60'),
                ('high_turnover',     '<',   2.00, 'Annualised turnover must be below 200%'),
                ('low_trade_count',   '>',   30,   'OOS trade count must exceed 30'),
                ('tail_risk',         '<',   0.10, 'CVaR (95%) must be below 10%')
            ON CONFLICT (threshold_name) DO NOTHING
        $q$;
        RAISE NOTICE 'risk_config: inserted using column name=threshold_name';
    ELSE
        RAISE NOTICE 'risk_config: could not find name column, skipping insert';
    END IF;
END $$;

-- ────────────────────────────────────────────────────────────
-- Fix 2 & 3 & 4: Drop and recreate all 4 views with correct
-- column references (e.id not e.event_id, correct aliases).
-- ────────────────────────────────────────────────────────────

-- v_risk_work
DROP VIEW IF EXISTS v_risk_work;
CREATE VIEW v_risk_work AS
SELECT
    e.id                                          AS event_id,
    e.event_type,
    e.strategy_id,
    e.domain,
    e.payload_json,
    e.source_agent,
    e.created_at,
    EXTRACT(EPOCH FROM (NOW() - e.created_at))/60 AS age_minutes
FROM events e
LEFT JOIN event_processing ep
       ON ep.event_id  = e.id
      AND ep.agent_name = 'qr_risk'
WHERE e.event_type = 'backtest.completed'
  AND e.domain     = 'quant'
  AND ep.event_id IS NULL
ORDER BY e.created_at ASC;

-- v_exp_manager_work
DROP VIEW IF EXISTS v_exp_manager_work;
CREATE VIEW v_exp_manager_work AS
SELECT
    e.id                                          AS event_id,
    e.event_type,
    e.strategy_id,
    e.domain,
    e.payload_json,
    e.source_agent,
    e.created_at,
    EXTRACT(EPOCH FROM (NOW() - e.created_at))/60 AS age_minutes
FROM events e
LEFT JOIN event_processing ep
       ON ep.event_id  = e.id
      AND ep.agent_name = 'qr_exp_manager'
WHERE e.event_type = 'qa.validated'
  AND e.domain     = 'quant'
  AND ep.event_id IS NULL
ORDER BY e.created_at ASC;

-- v_monitor_overview
DROP VIEW IF EXISTS v_monitor_overview;
CREATE VIEW v_monitor_overview AS
SELECT
    ep.event_id,
    ep.agent_name                                    AS agent_id,
    e.event_type,
    e.payload_json->>'experiment_id'                 AS experiment_id,
    e.strategy_id                                    AS workflow_id,
    e.domain,
    EXTRACT(EPOCH FROM (NOW() - ep.processed_at))/60 AS elapsed_minutes
FROM event_processing ep
JOIN events e ON e.id = ep.event_id
WHERE ep.processed_at IS NOT NULL
  AND e.domain = 'quant'
ORDER BY elapsed_minutes DESC;

-- v_pending_events — hub routing dedup
-- Must drop first because we're changing column alias (id -> event_id)
DROP VIEW IF EXISTS v_pending_events;
CREATE VIEW v_pending_events AS
SELECT
    e.id          AS event_id,
    e.event_type,
    e.strategy_id,
    e.domain,
    e.source_agent,
    e.payload_json,
    e.created_at
FROM events e
LEFT JOIN event_processing ep
       ON ep.event_id   = e.id
      AND ep.agent_name = 'qr_hub'
WHERE ep.event_id IS NULL
ORDER BY e.created_at ASC;

-- ────────────────────────────────────────────────────────────
-- Verify
-- ────────────────────────────────────────────────────────────
DO $$
BEGIN
    RAISE NOTICE 'Migration 002 complete. Views created: v_risk_work, v_exp_manager_work, v_monitor_overview, v_pending_events';
END $$;
