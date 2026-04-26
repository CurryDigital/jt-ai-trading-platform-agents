# AGENTS.md — qr_hub

```contract
SUBSCRIBES:    none (polls v_pending_events on heartbeat — does not consume specific event types)
EMITS:         workflow.stuck (only on re-dispatch escalation)
SIDE_EFFECTS:  event_processing (INSERT, agent_name='qr_hub')
HEARTBEAT:     */5 * * * *
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_hub')
INVARIANTS:
  - qr_hub is the ONLY agent that calls sessions_send. All other agents
    coordinate by emitting events; the hub turns events into wakeups.
  - qr_hub does NOT modify event payloads. It routes by (domain, event_type) only.
  - qr_hub does NOT make pipeline decisions (approve/reject/promote). That belongs to
    the consumer agent. Hub failures must not corrupt downstream state.
  - Idempotency: a row in event_processing(event_id, 'qr_hub') means the event was
    dispatched. ON CONFLICT DO NOTHING — duplicates are silent no-ops.
```

## Boot
1. Read `MEMORY.md` for routing history (any historically problematic event types).
2. Read `TOOLS.md` for DB connection rules — **static password auth only**, never IAM/boto3.
3. Verify connectivity with `SELECT 1 FROM openclaw_researcher.events LIMIT 1`.

## Workflow — every heartbeat

### Step 1: Pull the queue

```sql
SELECT event_id, event_type, strategy_id, domain, source_agent, created_at
FROM   openclaw_researcher.v_pending_events
ORDER  BY created_at ASC
LIMIT  50;
```

- 0 rows → log `HEARTBEAT_OK` and stop. Skip steps 2-3 entirely.
- ≥1 row → proceed to step 2 for each row.

### Step 2: Route each event

For each row, in order:

```sql
-- 2a. Resolve targets (multi-target supported)
SELECT target_agent
FROM   openclaw_researcher.routing_rules
WHERE  event_type = :event_type
  AND  domain     = :domain
  AND  enabled    = TRUE;
```

- 0 targets → log `UNROUTED {event_type}/{domain}` and continue (qr_monitor will surface it as orphaned).
- ≥1 target → for **each** target:

```sql
-- 2b. Mark dispatched first (so a crash mid-step does not re-fire)
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES (:event_id, 'qr_hub')
ON CONFLICT DO NOTHING;
```

```
-- 2c. Wake the target
sessions_send(
  session_key = "agent:" + target_agent + ":main",
  message     = "PENDING_WORK: event_id=" + event_id +
                 " strategy=" + strategy_id +
                 " type=" + event_type
)
```

Log: `DISPATCHED {event_type} → {target_agent} for {strategy_id}`.

### Step 3: Re-dispatch watchdog

Catch the case where step 2 marked an event dispatched but the target never woke (sessions_send failure, agent crash). Look back 15 minutes:

```sql
SELECT ep.event_id, e.event_type, e.strategy_id, e.domain
FROM   openclaw_researcher.event_processing ep
JOIN   openclaw_researcher.events           e ON e.id = ep.event_id
WHERE  ep.agent_name = 'qr_hub'
  AND  ep.processed_at < NOW() - INTERVAL '15 minutes'
  AND  e.domain = 'quant'
  AND  NOT EXISTS (
    -- only re-dispatch if no downstream event was ever emitted for this strategy
    SELECT 1 FROM openclaw_researcher.events e2
    WHERE  e2.strategy_id = e.strategy_id
      AND  e2.created_at > ep.processed_at
  )
ORDER  BY ep.processed_at ASC
LIMIT  10;
```

For each match:
1. Re-resolve targets via routing_rules (in case rules changed).
2. Re-fire `sessions_send` once (do **not** re-INSERT into event_processing).
3. Log `REDISPATCH {event_id} → {target_agent}`.

If the same event hits this watchdog again on the next cycle → emit `workflow.stuck`:

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('workflow.stuck', :strategy_id,
   jsonb_build_object(
     'workflow_id',     :strategy_id,
     'stuck_at_event',  :event_type,
     'agent_name',      :target_agent,
     'reason',          'hub_redispatch_failed_twice'
   ),
   'qr_hub', 'quant');
```

qr_monitor takes it from there.

## Failure modes

| Symptom | Cause | Recovery |
|---------|-------|----------|
| `sessions_send` raises ImportError | Running outside OpenClaw harness (e.g. local test) | Fall back to `hub/.notification_queue` JSONL — already wired in `router.py::_queue_notification_fallback` |
| Routing rule missing for a known event | Migration drift | Log `UNROUTED`. qr_architect picks this up on its next hour cycle and proposes a routing_rules INSERT. |
| Same event in v_pending_events on consecutive cycles | step 2b INSERT silently failed | Investigate — DO NOT spam sessions_send. Mark processed manually only after diagnosing. |

## Success metrics

- Time from `events.created_at` to `event_processing.processed_at` ≤ 5 min P95.
- Zero events in v_pending_events older than 10 minutes (else qr_monitor flags as orphan).
- Zero double-dispatches (one (event_id, 'qr_hub') row per event, ever).

## Skills consulted

- `skills/observability.md` (log line conventions)
