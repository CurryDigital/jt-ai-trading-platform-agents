# TOOLS.md — qr_architect

## Database

- **Schema:** `openclaw_researcher`
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables / views I read

- `events`, `event_processing`, `routing_rules`, `risk_config`, `gold_layer_state`
- `strategy_workflow`, `strategy_lineage`, `strategy_backtest_trades`
- `workflow_events` — for promotion-counting and self-gate
- All views (`v_pending_events`, `v_monitor_overview`, `v_strategy_lineage_full`, etc.) — for performance audits

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `workflow_events` | INSERT (`architect_cycle_complete`) | end of every cycle |

That's the only table this agent writes. Everything else is operator-applied.

## Filesystem

- `.learnings/FEATURE_REQUESTS.md` — mode 1 output
- `.learnings/PERFORMANCE_REVIEW.md` — mode 2 output
- `.learnings/SKILL_DRAFTS/<skill_name>.md` — mode 3 output (proposed diffs)
- `.learnings/ARCHITECTURE_DRIFT.md` — mode 4 output
- `MEMORY.md` — append-only, post 3-cycle confirmation
- `skills/` — read-only audit of stale capabilities

## External tools

| Tool | Use |
|------|-----|
| Brave Search API | mode 1 web research |
| Web fetch (read-only) | source verification |
| `git log skills/<file>.md` | mode 3 staleness check |
| `grep -c "Pattern-ID: <id>" .learnings/*.md` | promotion-counting |

## Constants

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN, PLATFORM_DOMAIN,
    AGENT_ARCHITECT as AGENT_ID,
)
```

## Denied

- No write to `routing_rules`, `risk_config`, `gold_layer_state`, or any agent's source code.
- No write to other agents' AGENTS.md / SOUL.md / HEARTBEAT.md / TOOLS.md.
- No `sessions_send`.
- No emission of pipeline events (`experiment.started`, `qa.validated`, etc.) — those belong to operator-facing agents.
- No promotion to `MEMORY.md` without 3 confirmed observations.
