-- migration_004.sql
-- Fix routing_rules PK to allow multiple target agents per (event_type, domain).
-- Seed all routing rules to match HubRouter.ROUTING_TABLE so SDK event discovery works.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 1: Drop old PK (event_type, domain) and recreate with target_agent
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE openclaw_researcher.routing_rules
    DROP CONSTRAINT IF EXISTS routing_rules_pkey;

ALTER TABLE openclaw_researcher.routing_rules
    ADD PRIMARY KEY (event_type, domain, target_agent);

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 2: Seed all routing rules from ROUTING_TABLE
-- Uses ON CONFLICT to be idempotent (safe to re-run).
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO openclaw_researcher.routing_rules (event_type, domain, target_agent, enabled)
VALUES
    -- Quant domain — pipeline routing
    ('experiment.started',   'quant', 'qr_data_validator', true),
    ('dataset.ready',        'quant', 'qr_algo',           true),
    ('backtest.completed',   'quant', 'qr_risk',           true),
    ('risk.evaluated',       'quant', 'qr_qa',             true),
    ('qa.validated',         'quant', 'qr_exp_manager',    true),
    ('qa.validated',         'quant', 'qr_idea_intake',    true),
    ('workflow.stuck',       'quant', 'qr_monitor',        true),
    ('workflow.stuck',       'quant', 'qr_idea_intake',    true),
    ('system.startup',       'quant', 'qr_monitor',        true),
    ('etl.completed',        'quant', 'qr_monitor',        true),
    ('etl.partial',          'quant', 'qr_monitor',        true),
    ('etl.partial',          'quant', 'qr_idea_intake',    true),
    ('etl.failed',           'quant', 'qr_monitor',        true),
    ('etl.failed',           'quant', 'qr_idea_intake',    true),
    ('etl.operator_alert',   'quant', 'qr_idea_intake',    true),
    ('etl.refresh_requested','quant', 'qr_etl_manager',    true),
    -- Platform domain
    ('feature.requested',    'platform', 'platform_dev',     true),
    ('code.generated',       'platform', 'qa_code',          true),
    ('code.tested',          'platform', 'platform_ops',     true),
    ('deployment.completed', 'platform', 'platform_monitor', true),
    ('system.startup',       'platform', 'platform_monitor', true)
ON CONFLICT (event_type, domain, target_agent) DO UPDATE
    SET enabled = EXCLUDED.enabled,
        updated_at = NOW();

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 3: Clean up any hub_router entries from old route scripts (C1 fix)
-- The canonical Hub agent name is qr_hub, not hub_router.
-- ─────────────────────────────────────────────────────────────────────────────

-- Mark events processed by hub_router as also processed by qr_hub
-- so they don't get re-dispatched when the canonical hub runs.
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
SELECT event_id, 'qr_hub'
FROM openclaw_researcher.event_processing
WHERE agent_name = 'hub_router'
ON CONFLICT (event_id, agent_name) DO NOTHING;

COMMIT;
