# TOOLS.md — research_agent

## Database
- Schema: openclaw_researcher
- Auth: Standard Static Password (via DB_PASSWORD, DB_HOST, DB_USER, DB_NAME env vars). Do NOT use IAM or boto3.
- Region: ap-southeast-1

## Key tables
- events, event_processing, strategy_workflow, strategy_lineage
- risk_config, gold_layer_state, routing_rules, workflow_events
- gold.stock_metrics_history, gold.ipo_data (for research queries)

## Quick SQL patterns
- Emit event: INSERT INTO openclaw_researcher.events (event_type, strategy_id, payload_json, source_agent, domain) VALUES (?,?,?,?,?)