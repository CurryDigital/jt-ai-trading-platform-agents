# TOOLS.md — qr_hub

## Database

- **Schema:** `openclaw_researcher`
- **Auth:** Static password from `/home/ubuntu/.openclaw/.env::DB_PASSWORD`. **Do not** use IAM tokens or boto3 — caused intermittent connection drops; see `hub/router.py::HubRouter._get_conn`.
- **Region:** `ap-southeast-1`
- **Connection rule:** open per-call, close in `finally`. Hub is short-lived; pooling is unnecessary and adds failure modes.

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `event_processing` | `INSERT` (`agent_name='qr_hub'`) | every dispatch |
| `events`           | `INSERT` (only `workflow.stuck`) | escalation after second redispatch failure |

## Tables I read

- `events`             — payload + metadata
- `event_processing`   — to confirm dedup + watchdog lookback
- `routing_rules`      — `(event_type, domain, target_agent, enabled)`
- `v_pending_events`   — primary work queue
- `v_monitor_overview` — for the watchdog query

## SQL patterns

| Purpose | Statement |
|---------|-----------|
| Pull queue | `SELECT … FROM v_pending_events ORDER BY created_at ASC LIMIT 50;` |
| Resolve targets | `SELECT target_agent FROM routing_rules WHERE event_type=:t AND domain=:d AND enabled;` |
| Mark dispatched | `INSERT INTO event_processing (event_id, agent_name) VALUES (:id, 'qr_hub') ON CONFLICT DO NOTHING;` |
| Watchdog | see `AGENTS.md::Workflow::Step 3` |

## OpenClaw harness

- `sessions_send(session_key, message)` — **only this agent calls it**. Any other agent attempting to call sessions_send is a bug. The hub's monopoly on dispatch is what makes the audit trail trustworthy.
- Fallback: when `sessions_send` is unavailable (testing outside the harness), `hub/router.py` writes to `hub/.notification_queue` (JSONL, one event per line). Pickup logic for that file lives outside qr_hub's responsibility.

## Constants imported

```python
from agents.shared.constants import SCHEMA, QUANT_DOMAIN, PLATFORM_DOMAIN
```

## Denied

- No web access. No filesystem writes outside `hub/.notification_queue`.
- No reads from `strategy_workflow`, `strategy_lineage`, `risk_config`, or `gold_layer_state`. Hub is domain-blind by design — touching strategy state is what makes routers turn into orchestrators, and that's the exact failure mode we avoid.
- No write to any table other than `event_processing` + (escalation only) `events`.
