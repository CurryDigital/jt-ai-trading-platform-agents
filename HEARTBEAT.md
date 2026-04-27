# HEARTBEAT.md — Autonomous schedules

**One cadence. Every agent wakes every 30 minutes.** Time-bound work is
self-gated by the agent against `workflow_events`, not by a custom cron.
This keeps the scheduler boring, missed wakeups recover automatically on
the next cycle, and the operator only has to reason about a single
interval.

Per-agent heartbeats live in `agents/<id>/HEARTBEAT.md` and inherit the
schedule below.

Format (machine-parseable — do not change keys):

```
schedule: */30 * * * *   # 5-field crontab in UTC
target:   agent:<id>:main
message:  <one paragraph instruction the harness sends as the wake message>
```

---

## The fleet — 13 agents, one schedule

```
schedule: */30 * * * *
target:   agent:qr_hub:main
message:  Routing cycle. Drain v_pending_events, route each row per routing_rules, dedup via event_processing(agent_name='qr_hub'), fire sessions_send to each target. Then run the 15-minute redispatch watchdog and emit workflow.stuck after the second strike. Full SQL in agents/qr_hub/AGENTS.md.
```

```
schedule: */30 * * * *
target:   agent:qr_monitor:main
message:  Health cycle. (1) clear_stale_gold_lock(12). (2) v_monitor_overview vs TIMEOUT_THRESHOLDS — first strike requeue, second strike escalate, third strike fail. (3) orphan detection. (4) gold-layer audit. (5) Sundays — workspace snapshot, MEMORY archive, learning promotion.
```

```
schedule: */30 * * * *
target:   agent:qr_data_validator:main
message:  Drain v_qr_data_validator_work. Gold-layer gate first; if locked/stale, skip without marking processed. Otherwise run the 5 quality checks, update strategy_workflow status='data_validated', emit dataset.ready, mark processed.
```

```
schedule: */30 * * * *
target:   agent:qr_algo:main
message:  Drain v_qr_algo_work. Run backtest, populate strategy_backtest_trades, write metrics to strategy_workflow, emit backtest.completed. Trade count in metrics MUST match COUNT(*) of trades inserted — anti-hallucination guard.
```

```
schedule: */30 * * * *
target:   agent:qr_risk:main
message:  Drain v_qr_risk_work. Load thresholds from risk_config (name NOT LIKE 'qa_%'). Run 6 checks, compute risk_score = flags/6, set risk_approved = (score == 0). ALWAYS emit risk.evaluated — even on rejection.
```

```
schedule: */30 * * * *
target:   agent:qr_debate:main
message:  Drain v_qr_debate_work, max 5 per cycle. If risk_approved=false, fast-fail with conviction=0 and skip the bull/bear write-up. Otherwise produce 3 bullets bull, 3 bullets bear, conviction ∈ [0,1]. Emit debate.completed. (Telemetry only — qr_qa does not wait.)
```

```
schedule: */30 * * * *
target:   agent:qr_qa:main
message:  Drain v_qr_qa_work. Run 5 gates in order, stop at first fail. ON PASS — INSERT strategy_lineage AND emit qa.validated in ONE transaction. ON FAIL — emit qa.validated(passed=false) with the failed gate number. Mark processed.
```

```
schedule: */30 * * * *
target:   agent:qr_exp_manager:main
message:  Two phases. (a) Reactive — drain v_exp_manager_work, generate variants per the failed_gate→mutation table, dedup by canonical param_set. (b) Self-gated — if 16:00-16:30 UTC and no 'nightly_cycle_complete' workflow_event today, run nightly seeding from top performers; if Sunday and no 'weekly_summary_complete' this week, write the weekly digest.
```

```
schedule: */30 * * * *
target:   agent:qr_idea_intake:main
message:  Notification cycle. Find the next un-relayed event of interest from {qa.validated, workflow.stuck, etl.partial, etl.failed, etl.operator_alert}. Format per AGENTS.md, deliver to operator over Telegram, mark processed. One event per cycle — do not loop.
```

```
schedule: */30 * * * *
target:   agent:qr_etl_manager:main
message:  Self-gated. If a 'daily_cycle_complete' workflow_event exists for today (UTC) → HEARTBEAT_OK. Otherwise — only between 14:00-14:30 UTC — UPDATE gold_layer_state SET state='locked', run bronze sources, run daily_refresh.sh, UPDATE gold_layer_state with final state ∈ {ready,partial,stale}, emit etl.completed | etl.partial | etl.failed, write 'daily_cycle_complete' workflow_event.
```

```
schedule: */30 * * * *
target:   agent:qr_researcher:main
message:  Self-gated 6h. If MAX(workflow_events.created_at WHERE event_type='researcher_cycle_complete') > NOW() - 6h → HEARTBEAT_OK. Otherwise pick 1-2 underexplored cells from skills/strategy_registry.md (mode rotates by hour: news, data, cross-asset, failure-driven), draft hypotheses, emit experiment.started, dedupe within 30 days.
```

```
schedule: */30 * * * *
target:   agent:qr_macro_sentinel:main
message:  Self-gated 2h. If MAX(workflow_events.created_at WHERE event_type='macro_scan_complete') > NOW() - 2h → HEARTBEAT_OK. Otherwise rotate one query from the watchlist, log significant findings to .learnings/MACRO_EVENTS.md, emit experiment.started ONLY when confidence=high AND historical precedent exists in MEMORY.md.
```

```
schedule: */30 * * * *
target:   agent:qr_architect:main
message:  Self-gated 4h. If MAX(workflow_events.created_at WHERE event_type='architect_cycle_complete') > NOW() - 4h → HEARTBEAT_OK. Otherwise pick the rotation slot for this 4h window — research / performance review / skill evolution / design validation — and write findings to .learnings/. Promote to MEMORY.md only after the same observation 3 cycles in a row. Never auto-merge code or schema changes.
```

---

## How the self-gate works

Each time-bound agent writes a marker after completing its cycle:

```sql
INSERT INTO openclaw_researcher.workflow_events (event_type, agent, data)
VALUES ('<id>_cycle_complete', '<id>', jsonb_build_object('cycle','<window>'));
```

At the start of every wake, it checks:

```sql
SELECT MAX(created_at) FROM openclaw_researcher.workflow_events
WHERE agent = '<id>' AND event_type = '<id>_cycle_complete';
```

If the result is within the agent's window (6h, 2h, 4h, today, this week, …),
log `HEARTBEAT_OK` and exit. Otherwise run the work and write a fresh marker.

This pattern means:
- Missed wakeups self-recover on the next 30-min cycle.
- A single agent reliably runs at most once per window even if the harness fires twice.
- The operator can force a re-run by deleting the marker row.

## Operator overrides

Pause any agent by disabling its dispatch rule:

```sql
UPDATE openclaw_researcher.routing_rules
SET enabled = FALSE
WHERE target_agent = '<id>';
```

Force a self-gated re-run:

```sql
DELETE FROM openclaw_researcher.workflow_events
WHERE agent = '<id>' AND event_type = '<id>_cycle_complete'
  AND created_at::date = CURRENT_DATE;
```

The next 30-min wake will rerun the gated work.
