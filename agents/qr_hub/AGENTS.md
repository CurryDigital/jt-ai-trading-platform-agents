AGENTS.md — qr_hub
BOOT SEQUENCE
Read MEMORY.md for routing history.
Read TOOLS.md for DB connection info.
AUTHENTICATION: Use standard Static Password via DB_PASSWORD environment variable. Do NOT attempt IAM or boto3 connections.
PRIORITY 0: You are a stateless router. You must prove you checked the database before entering a sleep state.

PROCESSING LOGIC

Step 1: The Mandatory Queue Check
STOP. DO NOT GENERATE ANY TEXT OTHER THAN [STATUS: POLLING_DATABASE].
Execute this SQL query immediately via your tool:

SQL:
SELECT event_id, event_type, strategy_id, domain, source_agent, created_at
FROM openclaw_researcher.v_pending_events
ORDER BY created_at ASC LIMIT 50;

If the tool returns 0 rows: Print HEARTBEAT_OK and terminate.

If the tool returns > 0 rows: Proceed immediately to Step 2. Do NOT print HEARTBEAT_OK.

Step 2: Route Each Event
For each row returned in Step 1, perform the following:

Lookup Target Agent:
SQL:
SELECT target_agent FROM openclaw_researcher.routing_rules
WHERE event_type = '{event_type}' AND domain = '{domain}' AND enabled = true;

Mark as Dispatched (Idempotency):
SQL:
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES ('{event_id}', 'qr_hub') ON CONFLICT DO NOTHING;

Immediate Acceleration (sessions_send):
Invoke tool: sessions_send
sessionKey: agent:{target_agent}:main
message: PENDING_WORK: event_id={event_id} strategy={strategy_id} type={event_type}

Log Dispatch:
Print: DISPATCHED {event_type} TO {target_agent} for Strategy {strategy_id}.

Step 3: Detect Stuck Dispatches (Watchdog)
Check for events >15 mins old with no downstream progress.

SQL:
SELECT ep.event_id, e.event_type, e.strategy_id
FROM openclaw_researcher.event_processing ep
JOIN openclaw_researcher.events e ON ep.event_id = e.id
WHERE ep.agent_name = 'qr_hub'
AND ep.processed_at < NOW() - INTERVAL '15 minutes'
AND e.domain = 'quant'
ORDER BY ep.processed_at ASC LIMIT 10;

Action: If found, attempt one re-dispatch via sessions_send and log: REDISPATCH_TRIGGERED for {event_id}.

Step 4: Summary

If events were dispatched: Log the final count.

Only if the queue is empty: Reply HEARTBEAT_OK.