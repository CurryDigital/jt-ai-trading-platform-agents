# AGENTS.md — qr_monitor

```contract
SUBSCRIBES:    workflow.stuck, system.startup, etl.completed, etl.partial, etl.failed
EMITS:         workflow.stuck (escalation), workflow_failed (audit only — workflow_events table)
SIDE_EFFECTS:  event_processing (DELETE on requeue), workflow_events (INSERT),
               strategy_workflow (UPDATE status='failed'),
               gold_layer_state (UPDATE via clear_stale_gold_lock)
HEARTBEAT:     */30 * * * *
IDEMPOTENCY:   workflow_events row with event_type='monitor_requeue' per (event_id) — one requeue per event, ever.
INVARIANTS:
  - First strike: requeue once. Second strike: escalate to failed. Never a third try.
  - Monitor never overrides QA decisions. It only watches for liveness.
  - Gold-layer locks older than GOLD_LAYER_LOCK_TIMEOUT_HOURS (12h) are auto-cleared
    so a crashed ETL cannot stall every experiment indefinitely.
```

## Boot
1. Read `MEMORY.md` for known-bad threshold patterns and recurring breach signatures.
2. Load `agents.shared.constants::TIMEOUT_THRESHOLDS` and `GOLD_LAYER_LOCK_TIMEOUT_HOURS`.

## Trigger sources

| Trigger | Action |
|---------|--------|
| 30m heartbeat | full health cycle (steps 0-4 below) |
| Hub wake on `workflow.stuck` | format alert, no recovery — qr_idea_intake notifies operator |
| Hub wake on `etl.failed` / `etl.partial` | log to MEMORY for ETL pattern detection |
| Hub wake on `system.startup` | log boot, exit |

## Workflow — every 30-min heartbeat

### Step 0: Auto-unlock wedged gold layer

```sql
SELECT openclaw_researcher.clear_stale_gold_lock(12);
```

Returns the count of locks cleared. If > 0 → log `Cleared {N} stale gold locks`. The data validator on its next event will see `state='stale'` and emit `workflow.stuck`, which the operator will see via qr_idea_intake.

### Step 1: Stuck-event detection

```sql
SELECT
  event_id, agent_id, event_type, experiment_id, workflow_id,
  elapsed_minutes, gold_layer_state
FROM   openclaw_researcher.v_monitor_overview
WHERE  elapsed_minutes > 0
ORDER  BY elapsed_minutes DESC;
```

For each row, compare `elapsed_minutes` against `TIMEOUT_THRESHOLDS[event_type]`:

```python
TIMEOUT_THRESHOLDS = {
  'experiment.started': 15,
  'dataset.ready':      10,
  'backtest.completed': 30,
  'risk.evaluated':      5,
  'debate.completed':    5,
  'qa.validated':        5,
}
```

If `elapsed > threshold`:

1. **Count prior strikes** for this workflow:

   ```sql
   SELECT COUNT(*) FROM openclaw_researcher.events
   WHERE  event_type = 'workflow.stuck'
     AND  payload_json->>'workflow_id' = :workflow_id;
   ```

2. **Decision**:

   | Strikes so far | Action |
   |----------------|--------|
   | 0              | requeue (DELETE the event_processing row), emit `workflow.stuck(requeued=true)` |
   | 1              | emit `workflow.stuck(requeued=false)` (escalation — qr_idea_intake notifies operator) |
   | ≥ 2            | mark `strategy_workflow.status='failed'`, write `workflow_failed` audit event, do not emit further |

3. Always write to `workflow_events` so the next cycle can see what happened.

### Step 2: Orphan detection

Events the hub never picked up (no row in event_processing at all):

```sql
SELECT
  e.id AS event_id, e.event_type, e.strategy_id AS workflow_id,
  EXTRACT(epoch FROM now() - e.created_at)/60 AS age_minutes
FROM   openclaw_researcher.events e
LEFT JOIN openclaw_researcher.event_processing ep ON e.id = ep.event_id
WHERE  e.domain = 'quant'
  AND  e.event_type IN ('experiment.started','dataset.ready','backtest.completed',
                        'risk.evaluated','debate.completed','qa.validated')
  AND  ep.event_id IS NULL
  AND  e.created_at < NOW() - INTERVAL '5 minutes'
ORDER  BY e.created_at ASC LIMIT 50;
```

For each match where `age > TIMEOUT_THRESHOLDS[event_type]`:

- Log: `ORPHAN: event {id} type={type} workflow={wid} age={age}m — never routed by hub`.
- This is a hub-side failure, not a downstream agent failure. Do **not** requeue (no event_processing row to delete). qr_architect will diff routing_rules against ROUTING_TABLE on its hour cycle.

### Step 3: Gold-layer health audit

```sql
SELECT state, refreshed_at, sources_failed, hours_since_refresh, locked_since
FROM   openclaw_researcher.v_gold_layer_status;
```

| Condition | Action |
|-----------|--------|
| `hours_since_refresh > 36` | Log `Gold layer stale ({h}h)`. The next ETL cycle will refresh. |
| `state='locked' AND locked_since > 12h ago` | Already handled in step 0 — should be impossible by here. If we still see it, escalate (DB function failure). |
| `state='partial' AND length(sources_failed) > 1` | Log per-source failure count. Append to MEMORY for pattern detection. |

### Step 4: Weekly maintenance (Sundays only)

If `EXTRACT(DOW FROM NOW()) = 0`:

1. **Workspace snapshot:** `git -C /home/ubuntu/.openclaw/workspace/quant_research add -A && git commit -m "weekly snapshot $(date -I)"` (no remote push — operator does that).
2. **Memory archival:** move `MEMORY.md` lines older than 30 days to `MEMORY_archive_YYYY-MM.md`.
3. **Learning promotion:** for each `.learnings/*.md` entry with `Recurrence-Count: ≥3`, append to `MEMORY.md` and tag the source line `[promoted YYYY-MM-DD]`.

### Step 5: Summary

```
Monitor: {N} stuck (req={R}, esc={E}, failed={F}), {O} orphans, gold={state} ({h}h), locks_cleared={L}
```

If everything is `0`: log `HEARTBEAT_OK`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| `clear_stale_gold_lock` SQL function missing | Migration 006 not applied. Log error and continue (defensive — agent must not crash on DB drift). qr_architect picks this up on its hour cycle. |
| Same workflow stuck for 6 cycles | Already escalated to `failed` after cycle 2. No further action — operator owns the recovery. |
| Orphan count rising over multiple cycles | Hub is not running. Check `agent:qr_hub:main` session liveness. Page operator if persistent. |

## Success metrics

- Mean time to detection (MTTD) of a stuck workflow ≤ 30 min.
- Mean time to recovery (MTTR) for transient stalls ≤ 60 min (one requeue cycle).
- 0 false escalations per quarter (escalations that recovered without operator intervention).
- 0 wedged gold-layer locks lasting > 13 h.

## Skills consulted

- `skills/self_healing.md` — recovery patterns, timeout calibration history
- `skills/observability.md` — log line conventions
