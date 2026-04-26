# HEARTBEAT.md — Autonomous schedules

Each block below declares one scheduled wakeup. The scheduler reads the
fenced `cron` block; the prose tells the agent what to do once awake.
Per-agent heartbeats live in `agents/<id>/HEARTBEAT.md`.

Format (machine-parseable — do not change keys):

```
schedule: <cron>          # UTC, 5-field crontab
target:   agent:<id>:main # session key the scheduler wakes
message:  <one paragraph instruction sent as the wake message>
```

---

## Hub dispatch (every 5 min)

`qr_hub` polls `v_pending_events`, routes each via `sessions_send`, and
records the dedup row. Without this loop nothing else fires.

```
schedule: */5 * * * *
target:   agent:qr_hub:main
message:  Routing cycle. Read v_pending_events LIMIT 50, dispatch each event to its target_agent(s) per routing_rules, INSERT into event_processing with agent_name='qr_hub'. Then check v_monitor_overview for events stuck > 15 minutes since dispatch and emit workflow.stuck for each.
```

## Pipeline health (every 30 min)

`qr_monitor` clears stale gold-layer locks (>12h), re-queues stuck events
once, and escalates after the second strike.

```
schedule: */30 * * * *
target:   agent:qr_monitor:main
message:  Health cycle. (1) Call openclaw_researcher.clear_stale_gold_lock(12) to break wedged ETL locks. (2) Read v_monitor_overview, compare elapsed_minutes against TIMEOUT_THRESHOLDS; first strike → re-queue + workflow.stuck(requeued=true), second strike → mark workflow failed. (3) Read orphaned events with no event_processing row; log and warn. Only escalate breaches that are real.
```

## Self-improvement (hourly)

`qr_architect` audits the contract surface against the running code and
opens diffs against AGENTS.md / .py when they drift. It never auto-merges.

```
schedule: 0 * * * *
target:   agent:qr_architect:main
message:  Drift audit. For each agent, read agents/<id>/AGENTS.md::contract and compare against routing_rules + the agent's .py SUBSCRIBES/EMITS. If they disagree, write a proposal to .learnings/ARCHITECTURE_DRIFT.md. Promote to MEMORY.md only after the same drift is observed 3 cycles in a row.
```

## Macro scan (every 2h)

`qr_macro_sentinel` watches for geopolitical events that should seed
experiments.

```
schedule: 0 */2 * * *
target:   agent:qr_macro_sentinel:main
message:  Macro scan. Rotate through the watchlist queries. For each significant event log to .learnings/MACRO_EVENTS.md with confidence ∈ {low,medium,high}. Only emit experiment.started when confidence=high AND a historical precedent is in MEMORY.md. Otherwise queue for the operator to triage.
```

## Idea generation (every 6h)

`qr_researcher` expands the search tree when the pipeline is quiet.

```
schedule: 0 */6 * * *
target:   agent:qr_researcher:main
message:  Idea cycle. If COUNT(strategy_workflow WHERE status NOT IN ('completed','failed','golden','rejected')) >= FLOOD_CONTROL_LIMIT, exit OK. Otherwise pick 1-2 underexplored cells from skills/strategy_registry.md, draft hypotheses, and emit experiment.started. Do not duplicate a param_set seen in the last 30 days.
```

## ETL refresh (daily 14:00 UTC = 22:00 SGT)

`qr_etl_manager` runs bronze→silver→gold. Locks the gold layer at start,
unlocks on finish (success/partial/failed). qr_monitor breaks the lock if
this never finishes.

```
schedule: 0 14 * * *
target:   agent:qr_etl_manager:main
message:  Daily refresh. UPDATE gold_layer_state SET state='locked', locked_since=NOW(). Run bronze sources in dependency order. Run daily_refresh.sh for silver/gold/consumption. UPDATE gold_layer_state with final state ∈ {ready, partial, stale}. Emit etl.completed | etl.partial | etl.failed.
```

## Variant generation (daily 16:00 UTC = 00:00 SGT)

`qr_exp_manager` seeds tomorrow's experiments from today's winners.

```
schedule: 0 16 * * *
target:   agent:qr_exp_manager:main
message:  Nightly cycle. Query strategy_lineage for sharpe_oos > EXP_NIGHTLY_TOP_SHARPE in the last EXP_NIGHTLY_LOOKBACK_DAYS. If any: generate EXP_PHASE2_VARIANTS variants around the best param_set per family. If none: seed EXP_NIGHTLY_FALLBACK_COUNT random experiments across underexplored types in skills/strategy_registry.md. Report one line: "Today: N completed, M passed QA, top Sharpe OOS: X.XX".
```

## Weekly summary (Sun 00:00 UTC = Sun 08:00 SGT)

```
schedule: 0 0 * * 0
target:   agent:qr_exp_manager:main
message:  Weekly summary. Query strategy_lineage for the past 7 days. Report total experiments, QA pass rate, top 3 by sharpe_oos, most common rejection gate, and a one-sentence direction for next week's parameter search. Send via qr_idea_intake to operator.
```

---

## Operator overrides

The operator can pause any heartbeat by inserting:

```sql
UPDATE openclaw_researcher.routing_rules
SET enabled = FALSE
WHERE event_type = '<scheduled trigger event>' AND domain = 'quant';
```

There is no global pause switch by design. Disabling the hub stops
dispatching but agents will still accept direct wakes from the operator.
