-- migration_005_cleanup.sql
-- Clean up legacy routing_rules rows and unblock the pipeline.
-- Safe to re-run (idempotent).

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 1: Remove legacy routing_rules rows with JSON array target_agent values
-- These are leftover from the old PK=(event_type, domain) schema where
-- target_agent was stored as a Postgres array literal like "{qr_monitor,qr_idea_intake}".
-- The migration_004 seeded individual rows — these old ones are now redundant.
-- ─────────────────────────────────────────────────────────────────────────────

DELETE FROM openclaw_researcher.routing_rules
WHERE target_agent LIKE '{%'
   OR target_agent LIKE '"%';

-- Also remove the platform system.startup → tradinghub row (not a real agent)
DELETE FROM openclaw_researcher.routing_rules
WHERE target_agent = 'tradinghub';

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 2: Verify clean state — should show only individual agent names
-- ─────────────────────────────────────────────────────────────────────────────

-- (Run manually to verify)
-- SELECT event_type, domain, target_agent, enabled
-- FROM openclaw_researcher.routing_rules
-- ORDER BY domain, event_type, target_agent;

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 3: Mark stale experiments as failed to unblock the pipeline
-- These are strategy_workflow rows stuck in non-terminal states
-- that were created before the routing fixes.
-- This frees up the intake flood control (currently at 39, limit is 10).
-- ─────────────────────────────────────────────────────────────────────────────

-- First, log what we're about to clean up
INSERT INTO openclaw_researcher.workflow_events
    (event_type, agent, from_status, to_status, data)
SELECT
    'bulk_cleanup',
    'migration_005',
    status,
    'failed',
    jsonb_build_object(
        'strategy_id', strategy_id,
        'reason', 'Cleared by migration_005: stale experiment from pre-fix pipeline',
        'original_status', status,
        'age_hours', EXTRACT(epoch FROM now() - created_at) / 3600
    )
FROM openclaw_researcher.strategy_workflow
WHERE status NOT IN ('completed', 'failed', 'golden', 'rejected')
  AND created_at < NOW() - INTERVAL '2 hours';

-- Now mark them failed
UPDATE openclaw_researcher.strategy_workflow
SET status = 'failed',
    result = 'stale_cleanup',
    last_error = 'Cleared by migration_005: stale experiment from pre-fix pipeline',
    last_error_at = NOW(),
    updated_at = NOW()
WHERE status NOT IN ('completed', 'failed', 'golden', 'rejected')
  AND created_at < NOW() - INTERVAL '2 hours';

-- ─────────────────────────────────────────────────────────────────────────────
-- Step 4: Also mark corresponding stale events as processed by the hub
-- so they don't get re-dispatched when the hub restarts.
-- Only for events older than 2 hours that were never fully processed.
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
SELECT e.id, 'qr_hub'
FROM openclaw_researcher.events e
LEFT JOIN openclaw_researcher.event_processing ep
    ON e.id = ep.event_id AND ep.agent_name = 'qr_hub'
WHERE ep.event_id IS NULL
  AND e.created_at < NOW() - INTERVAL '2 hours'
ON CONFLICT (event_id, agent_name) DO NOTHING;

COMMIT;
