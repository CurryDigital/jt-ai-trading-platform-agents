# Skill: Self-Healing

## Purpose
Defines how the Monitor detects, classifies, and recovers from
pipeline failures without human intervention. Also defines the
escalation path when autonomous recovery is exhausted.

Load this skill: Monitor agent only.

---

## Detection: what Monitor scans

Every 30 minutes (via HEARTBEAT) and on-demand, Monitor queries:

```sql
SELECT event_id, agent_name, event_type, experiment_id,
       workflow_id, elapsed_minutes
FROM v_monitor_overview
WHERE elapsed_minutes > 0
ORDER BY elapsed_minutes DESC
```

For each row: compare elapsed_minutes against timeout thresholds.

---

## Timeout thresholds (from event_contracts.md)

| Stage | Timeout |
|-------|---------|
| experiment.started (waiting for DE) | 15 min |
| dataset.ready (waiting for Algo) | 10 min |
| backtest.completed (waiting for Risk) | 30 min |
| risk.evaluated (waiting for QA) | 5 min |
| qa.validated (waiting for Exp. Manager) | 5 min |

---

## Recovery decision tree

```
elapsed > threshold?
    │
    ├── NO  → log "No breaches detected." and exit
    │
    └── YES → check workflow.stuck count for this workflow_id
                  │
                  ├── stuck_count == 0 → RE-QUEUE once
                  │     - Remove event_processing row (clears in_progress lock)
                  │     - Log: "workflow_id X stuck at {stage} for {N} min. Re-queuing once."
                  │     - Emit workflow.stuck (requeued=true)
                  │     - Hub routes workflow.stuck to Monitor + Idea Intake
                  │
                  └── stuck_count >= 1 → ESCALATE to failed
                        - Insert workflow_failed into workflow_events
                        - Log: "workflow_id X ESCALATED to failed after 2 stuck events."
                        - Emit workflow.stuck (requeued=false) for operator alert
                        - Do NOT re-queue again
```

---

## Re-queue mechanism

Re-queueing works by deleting the event_processing row for the stuck event.
This clears the `in_progress` lock and makes the event appear pending again.
Hub will re-dispatch it to the correct agent on next scan.

```sql
DELETE FROM event_processing
WHERE event_id = %s AND agent_name = %s
```

After deleting: log the re-queue, emit workflow.stuck with requeued=true.

---

## Common failure patterns and root causes

| Pattern | Likely cause | Recovery action |
|---------|-------------|-----------------|
| DE stuck >15 min | RDS connection timeout or ETL source unreachable | Re-queue once; check RDS connectivity |
| Algo stuck >30 min | Backtest computation hung (large universe or long date range) | Re-queue once; consider reducing asset_universe |
| Risk stuck >5 min | risk_config table empty or locked | Re-queue once; verify risk_config has rows |
| QA stuck >5 min | strategy_workflow row missing (FK issue) | ESCALATE — do not re-queue, data integrity risk |
| Multiple workflows stuck simultaneously | RDS overload or network partition | ESCALATE all; alert operator immediately |

---

## Escalation (after recovery exhausted)

When escalating to failed:
1. Write `workflow_failed` event to workflow_events
2. Set strategy_workflow.status = 'failed' for the affected strategy_id (if known)
3. Emit workflow.stuck with requeued=false — Hub routes to Idea Intake for operator alert
4. Log: "workflow_id X ESCALATED to failed. Requires manual intervention."

The operator will see:
> "⚠ Experiment {id} failed at {stage} after 2 recovery attempts. Manual check needed."

---

## What Monitor does NOT do

- Never modify experiment data or strategy metrics
- Never re-queue more than once per workflow per breach
- Never alert on minor delays (< threshold)
- Never restart agent sessions directly — only re-queue events
- Never wake agents directly — only via the event system (workflow.stuck → Hub routes)
