# AGENTS.md — Quant Research Pipeline

This file is the index. **Every behaviour rule that a single agent enforces lives in
that agent's own `agents/<id>/AGENTS.md`.** This top-level file is read by the
hub harness on boot to discover the agent fleet and the global contract.

---

## Architectural principle (read this first)

> The markdown is the agent. The Python is the assist.
> If the contract here disagrees with the .py, the markdown wins and the .py
> is the bug. qr_architect is allowed to file diffs against either.

Each agent ships seven files. The harness loads them in this order:

| File | Purpose | When loaded |
|------|---------|-------------|
| `IDENTITY.md` | Name, emoji, agent ID | always |
| `SOUL.md`     | Voice / decision posture (1–3 lines) | always |
| `AGENTS.md`   | Subscribes / emits / workflow / failure modes | always |
| `HEARTBEAT.md`| Cron + scheduled actions, machine-parseable | scheduler |
| `TOOLS.md`    | DB tables, SQL patterns, env vars, allowlists | always |
| `MEMORY.md`   | Persistent learnings (auto-promoted from `.learnings/`) | always |
| `USER.md`     | Operator profile + escalation contract | always |

Optional: `BOOTSTRAP.md` for one-shot first-run setup.

---

## Agent topology

All agents share a single 30-minute heartbeat cadence. Time-bound work
(daily ETL, nightly variant generation, weekly summary) is implemented
inside the agent as a self-gate against `workflow_events` — not by
varying the cron interval. This keeps the scheduler boring and makes
missed wakeups recover automatically on the next cycle.

| Agent | Lifecycle | Heartbeat | Role |
|-------|-----------|-----------|------|
| qr_hub            | Always-on | 30m | Sole event router (sessions_send) + dedup ledger |
| qr_monitor        | Always-on | 30m | Stuck-workflow watchdog + gold-layer auto-unlock |
| qr_architect      | Always-on | 30m (self-gates 4h) | Self-improvement loop — proposes diffs, never auto-merges |
| qr_macro_sentinel | Always-on | 30m (self-gates 2h) | Geopolitical event scanner |
| qr_researcher     | Always-on | 30m (self-gates 6h) | Autonomous idea generation |
| qr_etl_manager    | Always-on | 30m (self-gates daily) | Bronze→silver→gold supply chain |
| qr_idea_intake    | Reactive  | 30m | Telegram operator + qa.validated notifier |
| qr_exp_manager    | Reactive  | 30m (nightly + weekly self-gates) | Variant generation + family pruning |
| qr_data_validator | Reactive  | 30m | Gold-layer gate + 5 quality checks |
| qr_algo           | Reactive  | 30m | Backtest engine (currently stubbed; see Tier 2) |
| qr_risk           | Reactive  | 30m | 6-flag risk evaluation against `risk_config` |
| qr_debate         | Reactive  | 30m | Bull/bear telemetry, parallel observer of risk.evaluated |
| qr_qa             | Reactive  | 30m | 5 quality gates + atomic lineage promotion |

---

## Pipeline contract (current code reality, not aspirational)

```
Idea source ──▶ experiment.started ──▶ qr_data_validator
                                         │
                                  dataset.ready
                                         ▼
                                       qr_algo
                                         │
                              backtest.completed
                                         ▼
                                       qr_risk
                                         │
                                 risk.evaluated
                                         ├──▶ qr_qa            (gates + lineage)
                                         └──▶ qr_debate        (telemetry only — does NOT gate qa)
                                         │
                                   qa.validated
                                         ├──▶ qr_exp_manager   (variants)
                                         └──▶ qr_idea_intake   (operator notify)
```

`qr_debate` runs **in parallel** with `qr_qa`. QA does not wait for it.
A debate failure cannot stall the pipeline. (Wired in `migration_006.sql`.)

---

## Global rules

1. **All inter-agent communication goes through the `events` table.** No agent calls another's API directly.
2. **Only `qr_hub` calls `sessions_send`** to wake a target agent. Agents that try to wake peers must instead emit an event.
3. **Idempotency is mandatory.** Every consumer checks `event_processing(event_id, agent_name)` before processing and inserts on success. Duplicates are silent no-ops.
4. **Operators tune via `risk_config`, not code.** Agents reload thresholds at the start of every event handler — no restart needed.
5. **No silent retries.** A retryable failure must emit `workflow.stuck` so qr_monitor can decide between requeue and escalation.
6. **Lineage is atomic.** A `qa.validated` (passed) event and the `strategy_lineage` row that proves it must commit in the same transaction. If either fails, both roll back.
7. **Markdown is the source of truth.** When you change behaviour, change `AGENTS.md` first, then update the .py to match. qr_architect treats the .py as the spec under test.

---

## Per-agent contract format

Every `agents/<id>/AGENTS.md` MUST start with this fenced block so the harness
can discover subscriptions without reading prose:

````
```contract
SUBSCRIBES:    <event_type>[, <event_type>...] | none
EMITS:         <event_type>[, <event_type>...] | none
SIDE_EFFECTS:  <table>[, <table>...] | none
HEARTBEAT:     <cron expression> | none
IDEMPOTENCY:   event_processing(event_id, agent_name='<id>') | <other>
INVARIANTS:
  - <one-line invariant>
  - ...
```
````

This block is the contract. The narrative below it explains the *how* but
must never contradict the contract.

---

## Pipeline failure modes (where things historically break)

| Symptom | First check | Recovery |
|---------|-------------|----------|
| Every workflow stuck after restart | `agents/shared/constants.py` exists & importable | Tier 1 commit `cd3d6d3` |
| Risk approves everything | `risk_config` rows match agent-expected names (no `min_*`/`max_drawdown`) | `migration_006.sql` |
| All QA gates pass with identical metrics | `qr_algo._run_backtest_stub` still in place | Tier 2 (real backtest) |
| Validators loop forever skipping events | `gold_layer_state.state='locked'` and `locked_since > 12h` | qr_monitor calls `clear_stale_gold_lock()` each cycle |
| Operator floods pipeline | `qr_idea_intake` flood-control bypass clause in AGENTS.md | Removed — see Tier 3 |
| Conviction gate (Gate 6) referenced but never run | `qr_qa` does not consume `debate.completed` | Documented; Tier 2 if you want a real conviction gate |

---

## How to add a new agent

1. Create `agents/<id>/` with all seven files.
2. Open `AGENTS.md` with the `contract` block above.
3. Add an `INSERT` for `routing_rules` in a new migration (don't edit older ones).
4. Add the session key to `hub/router.py::AGENT_SESSIONS` and `ROUTING_TABLE`.
5. Add the agent ID + role row to the topology table above.
6. qr_architect will pick it up on next heartbeat and verify the contract is wired end-to-end.
