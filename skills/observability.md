# Skill: Observability

## Purpose
Defines what every agent must log, how to write workflow_events,
when to alert the operator, and what a complete audit trail looks like.
Without consistent observability, the pipeline is a black box.

Load this skill: All agents.

---

## Three tiers of output

### Tier 1 — stdout (agent log)
Every agent writes to stdout in this format:
```
[2024-01-15 14:32:01 UTC] AGENT_ID: message
```
Examples:
```
[2024-01-15 14:32:01 UTC] QA: Evaluating strategy abc-123
[2024-01-15 14:32:02 UTC] QA: Failed gate 3 — max_drawdown 0.31 exceeds 0.25
[2024-01-15 14:32:02 UTC] QA: strategy abc-123 rejected
```
OpenClaw captures stdout — this is what appears in the session log.
Be terse. One line per decision. No multiline dumps.

### Tier 2 — workflow_events table (structured audit)
Write a row to workflow_events for every significant state change:

```sql
INSERT INTO workflow_events (event_type, agent, from_status, to_status, strategy_id, data)
VALUES (%s, %s, %s, %s, %s, %s)
```

Required rows per agent per run:

| When | event_type | from_status | to_status |
|------|-----------|-------------|-----------|
| Work starts | `{agent}_started` | pending | in_progress |
| Work completes | `{agent}_completed` | in_progress | completed |
| Work fails | `{agent}_failed` | in_progress | failed |

The `data` jsonb column must include:
- `event_id`: the triggering event UUID
- `experiment_id`: always
- Key decision values (e.g. `{"sharpe_oos": 0.87, "gate_passed": 3}`)

Do NOT write verbose dumps. Write only the values that explain the decision.

### Tier 3 — operator alerts (via Idea Intake → messaging channel)
The Idea Intake agent is the only agent that messages the operator.
Other agents do NOT directly message the operator.
To surface something to the operator:
1. Emit a `workflow.stuck` event (Monitor will escalate)
2. Hub routes workflow.stuck to Idea Intake
3. Idea Intake formats and sends the message

The operator sees:
- ⚠ Stuck alerts (from Monitor via Idea Intake)
- ✓ QA pass notifications (from Idea Intake on qa.validated)
- ✗ QA rejection summaries (from Idea Intake on qa.validated)
- 📊 Nightly / weekly summaries (from Exp. Manager via HEARTBEAT)

---

## Mandatory log lines per agent

### DE agent
```
DE: Preparing dataset for experiment {experiment_id}
DE: Check 1 (missing bars): PASS — {N} trading days, all {M} tickers
DE: Check 5 (history depth): PASS — all tickers ≥ {2×lookback} pre-start rows
DE: dataset.ready emitted — dataset_id={id}, row_count={N}
```
On fail:
```
DE: Check 1 FAIL — AAPL: 187 days available, expected ~198 (threshold: 95%)
DE: Quality checks failed. Flags: [missing_bars]. Retry {N}/2.
```

### Algo agent
```
ALGO: Backtesting experiment {experiment_id}, strategy {strategy_id}
ALGO: IS period {start}→{mid}: Sharpe {x}, return {y}%
ALGO: OOS period {mid}→{end}: Sharpe {x}, return {y}%
ALGO: backtest.completed — sharpe_oos={x}, max_drawdown={y}, trades_oos={N}
```

### Risk agent
```
RISK: Evaluating strategy {strategy_id}
RISK: Thresholds loaded: {N} active rules
RISK: score={x}, approved={bool}, flags=[...]
RISK: {notes one-liner}
RISK: risk.evaluated emitted
```

### QA agent
```
QA: Evaluating strategy {strategy_id}
QA: Gate 1 (risk clearance): PASS / FAIL — {reason}
QA: Gates 2–5: PASS (all) / FAIL at gate {N} — {reason}
QA: strategy {id}: promoted / rejected
```

### Exp. Manager
```
EXP: Processing QA result for experiment {id}: passed={bool}
EXP: Phase {1|2}, experiment count: {N}
EXP: Generating {N} variants from param_set {...}
EXP: Variant {i}/{N} queued: experiment_id={id}
```
On flood control:
```
EXP: Flood control active ({N} in progress). Skipping generation.
```

### Monitor
```
MONITOR: Health check — {N} in-progress workflows
MONITOR: workflow_id {id} stuck at {stage} for {N} min. Re-queuing once.
MONITOR: workflow_id {id} ESCALATED to failed after 2 stuck events.
MONITOR: No breaches detected.
```

---

## What NOT to log

- Raw SQL queries
- Full payload JSON dumps (log key fields only)
- Passwords, tokens, or connection strings
- Intermediate computation steps (only inputs and decisions)
- Repetitive "checking..." lines — log the result, not the intent
