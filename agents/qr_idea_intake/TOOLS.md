# TOOLS.md — qr_idea_intake

## Database

- Schema: `openclaw_researcher`
- Auth: static password from `/home/ubuntu/.openclaw/.env::DB_PASSWORD` (see `hub/router.py`)
- Region: `ap-southeast-1`

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `strategy_workflow` | `INSERT` | new operator idea |
| `events`            | `INSERT` (`experiment.started`) | new operator idea |
| `event_processing`  | `INSERT` | after relaying any inbound event |

## Tables I read

`v_pending_events`, `events`, `event_processing`, `strategy_workflow`, `strategy_lineage` (for status reports).

## SQL patterns

- Pending notifications — see `HEARTBEAT.md`
- Flood control — `AGENTS.md::Workflow::Trading idea step 3`
- Dedup canonical hash — `AGENTS.md::Workflow::Trading idea step 4`

## External tools (only this agent has these)

| Tool | Use |
|------|-----|
| Telegram bot API | only operator-facing channel; bot token in `/home/ubuntu/.openclaw/.env::TELEGRAM_BOT_TOKEN` |

## Constants imported

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_IDEA_INTAKE as AGENT_ID,
    MAX_INTAKE_IN_PROGRESS as MAX_IN_PROGRESS,   # 10
    EXP_DUPLICATE_LOOKBACK_DAYS,                  # 30
    PARAM_LOOKBACK_MIN, PARAM_LOOKBACK_MAX,
    PARAM_ENTRY_MIN, PARAM_ENTRY_MAX,
    PARAM_EXIT_MIN, PARAM_EXIT_MAX,
)
```

## Denied

- No web access (operator never expects me to research).
- No write to `strategy_lineage` (qr_qa owns that table).
- No call to `sessions_send` (only qr_hub may dispatch).
