# HEARTBEAT.md — qr_hub (every 30 min)

```
schedule: */30 * * * *
target:   agent:qr_hub:main
message:  Routing cycle. Pull v_pending_events, route each per routing_rules, dedup via event_processing, fire sessions_send. Then run the 15-minute redispatch watchdog. See AGENTS.md for full SQL.
```

## What runs every cycle

This file is a pointer to the workflow in `AGENTS.md`. Two stages, in order:

1. **Dispatch** — `AGENTS.md::Workflow::Step 1+2`. Pull pending, look up target, mark, fire.
2. **Watchdog** — `AGENTS.md::Workflow::Step 3`. Catch dispatches that never woke their target.

## Exit conditions

- 0 rows in v_pending_events AND 0 rows in the watchdog query → log `HEARTBEAT_OK` and exit.
- ≥1 dispatch fired → log final count: `DISPATCHED {N} events`. Exit.
- Re-dispatch watchdog fired → log `REDISPATCHED {N} events`. Exit.
- DB connection failure → log error and exit. Do **not** retry inside one heartbeat.

## What this heartbeat does NOT do

- It does not call any other agent's logic. Routing is the only verb.
- It does not interpret payloads. Payloads pass through verbatim.
- It does not delete or mutate `events` rows. Only `event_processing` is written.
- It does not handle `workflow.stuck` — that's qr_monitor's 30-min cycle (same cadence, different responsibility).
