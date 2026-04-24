# TOOLS.md

## Database
- Schema: openclaw_researcher
- Auth: Standard Static Password (via DB_PASSWORD, DB_HOST, DB_USER, DB_NAME env vars). Do NOT use IAM or boto3.
- Region: ap-southeast-1

## Key tables
- events, event_processing, strategy_workflow, strategy_lineage
- risk_config, gold_layer_state, routing_rules, workflow_events
- views: v_pending_events (for Hub), v_qr_data_validator_work, v_qr_algo_work

## Quick SQL patterns
- Pending events: SELECT id AS event_id, event_type, strategy_id, payload_json, created_at FROM openclaw_researcher.v_qr_algo_work LIMIT 1;
- Mark processed: INSERT INTO openclaw_researcher.event_processing (event_id, agent_name) VALUES (?,?) ON CONFLICT DO NOTHING
- Emit event: INSERT INTO openclaw_researcher.events (event_type, strategy_id, payload_json, source_agent, domain) VALUES (?,?,?,?,?)

## Full schema: run `cat docs/schema.md` for complete DDL