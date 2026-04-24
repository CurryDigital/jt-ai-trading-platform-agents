# HEARTBEAT.md — Autonomous Scheduling

## Nightly experiment generation (00:00 SGT / 16:00 UTC)
Trigger the Exp. Manager to generate a new generation of experiments
from the top-performing entries in strategy_lineage. This keeps the
research loop running even without a human idea injection.

Check strategy_lineage for entries with sharpe_oos > 0.5 added in
the last 7 days. If any exist, generate 5 variants around the best
param_set. If none, run a broad random search (3 experiments) to
seed the pipeline.

Also report a one-line summary of experiments run today:
  "Today: N experiments completed, M passed QA, top Sharpe OOS: X.XX"

```
schedule: 0 16 * * *
target: agent:qr_exp_manager:main
message: Nightly generation cycle. Check strategy_lineage for top performers from the last 7 days and generate variants. If no recent lineage entries, run a broad random search with 3 experiments. Report a one-line summary of today's pipeline activity.
```

---

## Pipeline health check (every 30 minutes)
Monitor scans for stuck workflows and reports status.
Only pages if something is genuinely breached — not on minor delays.

```
schedule: */30 * * * *
target: agent:qr_monitor:main
message: Scheduled health check. Scan workflow_events and event_processing for any workflows stuck beyond their timeout thresholds. Report status. Only escalate if a threshold is genuinely breached.
```

---

## Weekly lineage summary (Sunday 08:00 SGT / Sunday 00:00 UTC)
Produce a summary of the week's research output: experiments run,
pass rate, top strategies by Sharpe OOS, any recurring failure patterns.

```
schedule: 0 0 * * 0
target: agent:qr_exp_manager:main
message: Weekly lineage summary. Query strategy_lineage for the past 7 days. Report: total experiments, QA pass rate, top 3 strategies by sharpe_oos, most common rejection gate, and a one-sentence recommendation for next week's parameter search direction.
```
