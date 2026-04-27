# HEARTBEAT.md — qr_architect (every 30 min, self-gated 4h)

```
schedule: */30 * * * *
target:   agent:qr_architect:main
message:  Self-gated. If MAX(workflow_events.created_at WHERE event_type='architect_cycle_complete') > NOW() - 4h → HEARTBEAT_OK. Otherwise pick mode = (UTC hour / 4) % 4 = {research, performance, skill_evolution, design_validation}, run only that mode, write findings to .learnings/, write architecture health to MEMORY.md, mark cycle. Promote to MEMORY.md only after 3 consecutive observations. Never auto-merge code, schema, or routing changes.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 0 | Self-gate: skip unless > 4h since last `architect_cycle_complete` |
| 1 | Pick mode = (UTC hour / 4) % 4 |
| 1a | Mode 1 — research the web for new patterns; log gaps to `.learnings/FEATURE_REQUESTS.md` |
| 1b | Mode 2 — pipeline performance audit (throughput, pass-rate, bottlenecks); log to `.learnings/PERFORMANCE_REVIEW.md` |
| 1c | Mode 3 — skill evolution (stale skills, missing strategy types); draft updates to `.learnings/SKILL_DRAFTS/` |
| 1d | Mode 4 — design validation (contract drift between AGENTS.md / routing_rules / .py); log to `.learnings/ARCHITECTURE_DRIFT.md` |
| 2 | Architecture health verdict (green/yellow/red) appended to MEMORY.md |
| 3 | Promotion check: 3+ consecutive observations of the same finding → MEMORY.md |
| 4 | Write `architect_cycle_complete` workflow_event marker |

## Exit conditions

- Self-gate hit (< 4h since last cycle) → `HEARTBEAT_OK`.
- All steps clean → log `ARCHITECT {mode}: health=green findings=0 promotions=0` and exit.
- Findings logged → log per-mode summary and exit.

## Hard rules

- NEVER auto-modify routing_rules, risk_config, source code, schema, or any other agent's AGENTS.md.
- NEVER promote to MEMORY.md without three consecutive observations of the same pattern.
- ALWAYS cite the source (SQL query, URL, file path, line number) for every finding.
