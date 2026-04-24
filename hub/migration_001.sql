-- ============================================================
-- Migration 001 — Bring schema in line with architecture.md
-- Run this ONCE against openclaw_researcher schema.
-- Idempotent: all ALTER ... IF NOT EXISTS / CREATE OR REPLACE.
-- ============================================================

SET search_path = openclaw_researcher, public;

-- ────────────────────────────────────────────────────────────
-- Gap 4a: domain column on events
-- ────────────────────────────────────────────────────────────
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'quant';

CREATE INDEX IF NOT EXISTS idx_events_domain ON events(domain);

-- ────────────────────────────────────────────────────────────
-- Gap 4b: domain column on routing_rules
-- ────────────────────────────────────────────────────────────
ALTER TABLE routing_rules
    ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'quant';

-- Drop the old single-column PK, replace with (event_type, domain) PK
-- so the same event_type can route differently per domain.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'routing_rules_pkey'
          AND conrelid = 'openclaw_researcher.routing_rules'::regclass
    ) THEN
        ALTER TABLE routing_rules DROP CONSTRAINT routing_rules_pkey;
    END IF;
END $$;

ALTER TABLE routing_rules
    ADD PRIMARY KEY (event_type, domain);

CREATE INDEX IF NOT EXISTS idx_routing_domain ON routing_rules(domain);

-- ────────────────────────────────────────────────────────────
-- Gap 4c: risk columns on strategy_workflow
-- ────────────────────────────────────────────────────────────
ALTER TABLE strategy_workflow
    ADD COLUMN IF NOT EXISTS risk_score       NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS risk_flags       JSONB,
    ADD COLUMN IF NOT EXISTS risk_approved    BOOLEAN,
    ADD COLUMN IF NOT EXISTS risk_notes       TEXT,
    ADD COLUMN IF NOT EXISTS risk_evaluated_at TIMESTAMPTZ;

-- ────────────────────────────────────────────────────────────
-- Gap 4d: extra columns on strategy_lineage
-- ────────────────────────────────────────────────────────────
ALTER TABLE strategy_lineage
    ADD COLUMN IF NOT EXISTS experiment_id    TEXT,
    ADD COLUMN IF NOT EXISTS risk_score       NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS param_set        JSONB,
    ADD COLUMN IF NOT EXISTS sharpe_oos       NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS max_drawdown     NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS trade_count_oos  INTEGER,
    ADD COLUMN IF NOT EXISTS promoted_at      TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_lineage_experiment ON strategy_lineage(experiment_id);

-- ────────────────────────────────────────────────────────────
-- Gap 4e: risk_config table (thresholds out of agent code)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_config (
    id              SERIAL PRIMARY KEY,
    threshold_name  TEXT NOT NULL UNIQUE,
    operator        TEXT NOT NULL,   -- '>', '<', '>=', '<='
    value           NUMERIC NOT NULL,
    description     TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Default thresholds (only inserted if table was just created / empty)
INSERT INTO risk_config (threshold_name, operator, value, description) VALUES
    ('max_drawdown',      '<',  -0.20, 'Max drawdown must not exceed -20%'),
    ('min_sharpe_oos',    '>',   0.50, 'OOS Sharpe must be above 0.5'),
    ('min_sharpe_ratio',  '>',   0.60, 'IS/OOS Sharpe ratio must be above 0.60'),
    ('high_turnover',     '<',   2.00, 'Annualised turnover must be below 200%'),
    ('low_trade_count',   '>',   30,   'OOS trade count must exceed 30'),
    ('tail_risk',         '<',   0.10, 'CVaR (95%) must be below 10%')
ON CONFLICT (threshold_name) DO NOTHING;

-- ────────────────────────────────────────────────────────────
-- Gap 5: Fix routing — backtest.completed → risk_agent (not qa_agent)
-- Then risk.evaluated → qa_agent
-- ────────────────────────────────────────────────────────────
-- Remove the old incorrect rule if it exists
DELETE FROM routing_rules
WHERE event_type = 'backtest.completed'
  AND target_agent IN ('qa', 'qa_quant', 'qr_qa')
  AND domain = 'quant';

-- Insert correct quant routing table
INSERT INTO routing_rules (event_type, domain, target_agent, enabled) VALUES
    ('experiment.started',  'quant', 'qr_data_validator', TRUE),
    ('dataset.ready',       'quant', 'qr_algo',         TRUE),
    ('backtest.completed',  'quant', 'qr_risk',         TRUE),  -- Fixed: was qa
    ('risk.evaluated',      'quant', 'qr_qa',           TRUE),  -- New leg
    ('qa.validated',        'quant', 'qr_exp_manager',        TRUE),
    ('workflow.stuck',      'quant', 'qr_monitor',      TRUE),
    ('system.startup',      'quant', 'qr_monitor',      TRUE)
ON CONFLICT (event_type, domain) DO UPDATE
    SET target_agent = EXCLUDED.target_agent,
        enabled      = EXCLUDED.enabled;

-- ────────────────────────────────────────────────────────────
-- Gap 6a: v_risk_work — pending backtest.completed for risk_agent
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_risk_work AS
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
       ON ep.event_id = e.event_id
      AND ep.agent_name = 'qr_risk'
WHERE e.event_type = 'backtest.completed'
  AND e.domain     = 'quant'
  AND ep.event_id IS NULL
ORDER BY e.created_at ASC;

-- ────────────────────────────────────────────────────────────
-- Gap 6b: v_exp_manager_work — pending qa.validated for exp_manager
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_exp_manager_work AS
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
       ON ep.event_id = e.event_id
      AND ep.agent_name = 'qr_exp_manager'
WHERE e.event_type = 'qa.validated'
  AND e.domain     = 'quant'
  AND ep.event_id IS NULL
ORDER BY e.created_at ASC;

-- ────────────────────────────────────────────────────────────
-- Gap 6c: v_monitor_overview — in-progress events with age
-- Joins event_processing (started) + events for type/experiment
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_monitor_overview AS
SELECT
    ep.event_id,
    ep.agent_name                                       AS agent_id,
    e.event_type,
    e.payload_json->>'experiment_id'                    AS experiment_id,
    e.strategy_id                                       AS workflow_id,
    e.domain,
    EXTRACT(EPOCH FROM (NOW() - ep.processed_at))/60    AS elapsed_minutes
FROM event_processing ep
JOIN events e ON e.id = ep.event_id
WHERE ep.processed_at IS NOT NULL
  AND e.domain = 'quant'
ORDER BY elapsed_minutes DESC;

-- ────────────────────────────────────────────────────────────
-- v_pending_events — events the Hub has NOT yet routed.
--
-- Dedup key: event_processing row with agent_name = 'qr_hub'.
-- Hub inserts this record immediately after dispatching, so the
-- next polling cycle skips events that were already routed.
-- This is separate from the agent processing records (de_agent etc.)
-- which use the same table but different agent_name values.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_pending_events AS
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
