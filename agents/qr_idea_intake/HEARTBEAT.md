# HEARTBEAT.md — qr_idea_intake (every 5 min)

Check for QA results to notify operator:

STOP. Execute this query explicitly casting UUIDs to text:
SQL:
SELECT e.id FROM openclaw_researcher.events e
LEFT JOIN openclaw_researcher.event_processing ep
  ON e.id::text = ep.event_id::text AND ep.agent_name = 'qr_idea_intake'
WHERE e.event_type IN ('qa.validated','workflow.stuck','etl.partial','etl.failed')
  AND e.domain = 'quant' AND ep.event_id IS NULL LIMIT 1;

If a row is returned → format result and notify operator via Telegram per AGENTS.md. Then mark as processed in event_processing.
If 0 rows: HEARTBEAT_OK