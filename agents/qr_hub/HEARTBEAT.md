# HEARTBEAT.md — qr_hub

CANARY: If you read this file, your first output must be [HEARTBEAT_V6_LOADED] before anything else.

DO NOT SAY HEARTBEAT_OK YET.

STEP 1: Run this SQL now:

SELECT event_id, event_type, strategy_id, domain, source_agent
FROM openclaw_researcher.v_pending_events
ORDER BY created_at ASC LIMIT 50;

STEP 2:
- 0 rows → say HEARTBEAT_OK
- 1+ rows → for each row, run:

SELECT target_agent FROM openclaw_researcher.routing_rules
WHERE event_type = '{event_type}' AND domain = '{domain}' AND enabled = true;

Then for each target:

INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES ('{event_id}', 'qr_hub') ON CONFLICT DO NOTHING;

Then call sessions_send to agent:{target_agent}:main with message:
PENDING_WORK: event_id={event_id} strategy={strategy_id} type={event_type}

Print: DISPATCHED {event_type} → {target_agent}