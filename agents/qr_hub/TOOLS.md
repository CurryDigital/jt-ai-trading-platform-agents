# TOOLS.md — qr_hub

## Database
- Schema: openclaw_researcher
- Auth: Standard Static Password (via DB_PASSWORD, DB_HOST, DB_USER, DB_NAME env vars). Do NOT use IAM or boto3.

## Key views
- `v_pending_events` — events not yet processed by qr_hub
- `v_monitor_overview` — all event_processing with elapsed time

## Key tables
- `events` — all pipeline events (event_type, strategy_id, payload_json, domain)
- `event_processing` — (event_id, agent_name) pairs for idempotency
- `routing_rules` — (event_type, domain, target_agent, enabled)
- `workflow_events` — audit log

## Routing rule lookup
```sql
SELECT target_agent FROM openclaw_researcher.routing_rules
WHERE event_type = ? AND domain = ? AND enabled = true;
```

## Full schema: run `cat docs/schema.md` if you need column details