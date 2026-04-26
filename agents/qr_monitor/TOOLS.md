# TOOLS.md — qr_monitor

## Database

- **Schema:** `openclaw_researcher`
- **Auth:** Static password from `/home/ubuntu/.openclaw/.env::DB_PASSWORD` (NOT IAM/boto3 — see `hub/router.py::HubRouter._get_conn`).
- **Region:** `ap-southeast-1`

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `event_processing` | `DELETE` | requeue (first strike on a stuck event) |
| `workflow_events`  | `INSERT` (`monitor_requeue`, `workflow.stuck`, `workflow_failed`) | every breach |
| `events`           | `INSERT` (`workflow.stuck`) | strike count 0 or 1 |
| `strategy_workflow`| `UPDATE status='failed'` | second strike |
| `gold_layer_state` | `UPDATE` (via `clear_stale_gold_lock` function) | step 0 every cycle |

## Tables / views I read

- `v_monitor_overview`        — primary work queue (in-flight events + elapsed)
- `v_gold_layer_status`       — gold layer staleness audit
- `events`                    — for prior strike counting
- `workflow_events`           — for requeue idempotency check
- `strategy_workflow`         — to verify strategy still exists before marking failed

## SQL patterns

All canonical queries live in `AGENTS.md`. Quick reference:

| Purpose | Statement |
|---------|-----------|
| Auto-unlock | `SELECT openclaw_researcher.clear_stale_gold_lock(12);` |
| Stuck events | `SELECT * FROM v_monitor_overview WHERE elapsed_minutes > 0 ORDER BY elapsed_minutes DESC;` |
| Orphan check | see `AGENTS.md::Workflow::Step 2` |
| Strike count | `SELECT COUNT(*) FROM events WHERE event_type='workflow.stuck' AND payload_json->>'workflow_id'=:wid;` |
| Requeue dedup | `SELECT 1 FROM workflow_events WHERE event_type='monitor_requeue' AND data->>'event_id'=:eid LIMIT 1;` |

## OpenClaw harness

- **No `sessions_send`.** Monitor never wakes other agents — it emits events and lets the hub dispatch.
- Reads `agents/shared/constants.py::TIMEOUT_THRESHOLDS, GOLD_LAYER_LOCK_TIMEOUT_HOURS`.

## Constants imported

```python
from agents.shared.constants import (
    SCHEMA, AGENT_MONITOR as AGENT_ID,
    TIMEOUT_THRESHOLDS,
    GOLD_LAYER_LOCK_TIMEOUT_HOURS,
)
```

## External tools

- **Sundays only:** `git` against `/home/ubuntu/.openclaw/workspace/quant_research` for the weekly snapshot. No `git push` — operator owns remote sync.

## Denied

- No web access.
- No `sessions_send` calls (would violate the hub's dispatch monopoly).
- No write to `risk_config` or `routing_rules` (those belong to operator + qr_architect).
- No mutation of `strategy_lineage` (qr_qa owns it; lineage is append-only).
