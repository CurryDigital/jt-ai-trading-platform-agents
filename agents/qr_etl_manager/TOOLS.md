# TOOLS.md

## Database
- Schema: openclaw_researcher
- Auth: Standard Static Password (via DB_PASSWORD, DB_HOST, DB_USER, DB_NAME env vars). Do NOT use IAM or boto3.
- Region: ap-southeast-1

## Key tables
- events, event_processing, strategy_workflow, strategy_lineage
- risk_config, gold_layer_state, routing_rules, workflow_events

## Quick SQL patterns
- Pending events: SELECT * FROM openclaw_researcher.v_pending_events
- Mark processed: INSERT INTO event_processing (event_id, agent_name) VALUES (?,?) ON CONFLICT DO NOTHING
- Emit event: INSERT INTO events (event_type, strategy_id, payload_json, source_agent, domain) VALUES (?,?,?,?,?)

## Full schema: run `cat docs/schema.md` for complete DDL
