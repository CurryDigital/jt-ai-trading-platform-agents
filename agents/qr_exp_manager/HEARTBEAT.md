# HEARTBEAT.md — qr_exp_manager (every 30 min, reactive + self-gated nightly + weekly)

```
schedule: */30 * * * *
target:   agent:qr_exp_manager:main
message:  Two phases. (a) Reactive — drain v_exp_manager_work, generate variants per the failed_gate→mutation table, dedup by canonical param_set. (b) Self-gated — if 16:00-16:30 UTC and no 'nightly_cycle_complete' workflow_event today, run nightly seeding from top performers; if Sunday 00:00-00:30 UTC and no 'weekly_summary_complete' this week, write the weekly digest.
```

## Cycle outline (full SQL in AGENTS.md)

| Phase | Step | Purpose |
|-------|------|---------|
| A reactive | A1 | Idempotency on `qa.validated` event |
| A reactive | A2 | Flood control (skip if in-flight ≥ 50) |
| A reactive | A3 | Family health (PRUNE / EXPAND / standard) |
| A reactive | A4 | Directed variant generation (1-5 variants depending on path) |
| A reactive | A5 | Dedup variants against last 30 days |
| A reactive | A6 | INSERT strategy_workflow + experiment.started per variant |
| A reactive | A7 | Mark `event_processing` |
| B nightly  | gate | Skip unless 16:00-16:30 UTC AND no `nightly_cycle_complete` today |
| B nightly  | work | Top-performer seeding (5 variants per) OR random fallback (3 seeds) |
| B nightly  | mark | INSERT `nightly_cycle_complete` workflow_event |
| C weekly   | gate | Skip unless Sunday 00:00-00:30 UTC AND no `weekly_summary_complete` this week |
| C weekly   | work | Compose summary, emit `etl.operator_alert` for qr_idea_intake to relay |
| C weekly   | mark | INSERT `weekly_summary_complete` workflow_event |

## Exit conditions

- Phase A only fired (no nightly/weekly window) → log `EXP_MANAGER reactive: parent={id} variants={N}` and exit.
- Phase B fired → log `EXP_MANAGER nightly: top={N} variants={M} fallback={bool}` and exit.
- Phase C fired → log `EXP_MANAGER weekly: total={N} passed={M}` and exit.
- All gates skip + no reactive work → `HEARTBEAT_OK`.

## Override

Force a re-run of nightly:

```sql
DELETE FROM openclaw_researcher.workflow_events
WHERE  agent = 'qr_exp_manager'
  AND  event_type = 'nightly_cycle_complete'
  AND  created_at::date = CURRENT_DATE;
```

Force a re-run of weekly:

```sql
DELETE FROM openclaw_researcher.workflow_events
WHERE  agent = 'qr_exp_manager'
  AND  event_type = 'weekly_summary_complete'
  AND  created_at > date_trunc('week', NOW());
```
