-- ============================================================
-- Migration 003 — Gold Layer State + Data Validator view
-- Safe to run multiple times (idempotent).
-- ============================================================
-- Implements refinement 2: gold layer lock mechanism.
-- The ETL Manager writes to gold_layer_state after every refresh.
-- The Data Validator reads this before running quality gates.
-- If state is 'stale' or 'locked', the validator blocks the
-- experiment and emits workflow.stuck rather than validating
-- against outdated data.
-- ============================================================

SET search_path = openclaw_researcher, public;

-- ────────────────────────────────────────────────────────────
-- TABLE: gold_layer_state
-- Single-row truth table for gold layer readiness.
-- ETL Manager owns all writes. Data Validator reads only.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold_layer_state (
    id              SERIAL PRIMARY KEY,
    state           TEXT        NOT NULL DEFAULT 'stale',
    -- state values:
    --   'ready'   → gold layer is fresh, experiments may proceed
    --   'stale'   → ETL has not run yet today, data may be outdated
    --   'locked'  → ETL refresh is currently running, do not validate
    --   'partial' → some sources failed, gold layer has known gaps
    refreshed_at    TIMESTAMPTZ,          -- when last full etl.completed fired
    sources_ok      JSONB,                -- list of sources that succeeded
    sources_failed  JSONB,                -- list of sources that failed + reasons
    locked_since    TIMESTAMPTZ,          -- set when ETL starts, cleared on finish
    notes           TEXT,                 -- human-readable explanation of state
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed with one row so ETL Manager can UPDATE rather than INSERT/upsert
INSERT INTO gold_layer_state (state, notes)
VALUES ('stale', 'Initial state — ETL Manager has not run yet.')
ON CONFLICT DO NOTHING;

-- Ensure only one row ever exists
CREATE UNIQUE INDEX IF NOT EXISTS gold_layer_state_singleton
    ON gold_layer_state ((true));

-- ────────────────────────────────────────────────────────────
-- VIEW: v_data_validator_work
-- Data Validator reads this before processing any experiment.
-- Replaces v_de_work (which referenced qr_de).
-- ────────────────────────────────────────────────────────────
DROP VIEW IF EXISTS v_de_work;

CREATE OR REPLACE VIEW v_data_validator_work AS
SELECT
    e.id                                           AS event_id,
    e.event_type,
    e.strategy_id,
    e.domain,
    e.payload_json,
    e.source_agent,
    e.created_at,
    EXTRACT(EPOCH FROM (NOW() - e.created_at))/60  AS age_minutes,
    gls.state                                      AS gold_layer_state,
    gls.refreshed_at                               AS gold_refreshed_at,
    gls.sources_failed                             AS gold_sources_failed
FROM events e
LEFT JOIN event_processing ep
       ON ep.event_id   = e.id
      AND ep.agent_name = 'qr_data_validator'
LEFT JOIN gold_layer_state gls ON true  -- single row join
WHERE e.event_type = 'experiment.started'
  AND e.domain     = 'quant'
  AND ep.event_id IS NULL
ORDER BY e.created_at ASC;

-- ────────────────────────────────────────────────────────────
-- VIEW: v_gold_layer_status
-- Convenience view for Monitor and operator queries.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_gold_layer_status AS
SELECT
    state,
    refreshed_at,
    EXTRACT(EPOCH FROM (NOW() - refreshed_at))/3600  AS hours_since_refresh,
    sources_ok,
    sources_failed,
    locked_since,
    notes,
    updated_at
FROM gold_layer_state;

-- ────────────────────────────────────────────────────────────
-- Update v_monitor_overview to include gold layer state
-- ────────────────────────────────────────────────────────────
DROP VIEW IF EXISTS v_monitor_overview;
CREATE VIEW v_monitor_overview AS
SELECT
    ep.event_id,
    ep.agent_name                                    AS agent_id,
    e.event_type,
    e.payload_json->>'experiment_id'                 AS experiment_id,
    e.strategy_id                                    AS workflow_id,
    e.domain,
    EXTRACT(EPOCH FROM (NOW() - ep.processed_at))/60 AS elapsed_minutes,
    gls.state                                        AS gold_layer_state
FROM event_processing ep
JOIN events e ON e.id = ep.event_id
LEFT JOIN gold_layer_state gls ON true
WHERE ep.processed_at IS NOT NULL
  AND e.domain = 'quant'
ORDER BY elapsed_minutes DESC;

DO $$
BEGIN
    RAISE NOTICE 'Migration 003 complete. Created: gold_layer_state table, v_data_validator_work, v_gold_layer_status. Updated: v_monitor_overview.';
END $$;
