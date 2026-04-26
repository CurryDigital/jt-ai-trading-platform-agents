# HEARTBEAT.md — qr_monitor (every 30 min)

```
schedule: */30 * * * *
target:   agent:qr_monitor:main
message:  Health cycle. Run steps 0-4 from AGENTS.md: gold-layer auto-unlock, stuck-event detection, orphan detection, gold-layer audit, and (Sundays) weekly maintenance. Only escalate breaches that genuinely exceed thresholds.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose | Side effect |
|------|---------|-------------|
| 0 | `clear_stale_gold_lock(12)` — auto-unlock ETL locks > 12h old | UPDATE `gold_layer_state` |
| 1 | Compare `v_monitor_overview.elapsed_minutes` against `TIMEOUT_THRESHOLDS` | requeue / escalate / fail |
| 2 | Find events with no `event_processing` row (hub never routed them) | log only — qr_architect resolves drift |
| 3 | Audit `v_gold_layer_status` for staleness or partial states | log + MEMORY entry |
| 4 | Weekly maintenance (Sundays only) | git snapshot, MEMORY archive, learning promotion |

## Exit conditions

- All steps return clean → log `HEARTBEAT_OK`.
- ≥1 escalation → log `Monitor: {N} stuck, {M} orphans, gold={state}, locks_cleared={L}` and emit `workflow.stuck` events as required.
- DB connection failure → log error and exit. The next 30-min cycle retries from step 0; we do **not** retry inside one heartbeat.

## What this heartbeat does NOT do

- Does not call any agent's logic. Liveness is the only verb.
- Does not delete `events` rows. Only `event_processing` (on requeue) and `gold_layer_state` (on auto-unlock) get mutated.
- Does not relay alerts to the operator. That's qr_idea_intake's job — qr_monitor emits `workflow.stuck`, the hub routes it, idea_intake formats and sends.
