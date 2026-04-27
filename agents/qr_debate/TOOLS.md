# TOOLS.md — qr_debate

## Database

- **Schema:** `openclaw_researcher`
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables / views I read

- `v_qr_debate_work` — primary work queue
- `strategy_workflow` — metrics + risk decision context
- `events` — to find the originating `experiment.started` payload (hypothesis)

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `strategy_workflow` | UPDATE (conviction_score, debate_summary) | every event |
| `events`            | INSERT (`debate.completed`) | every event |
| `event_processing`  | INSERT (idempotency) | every event |

## Constants imported

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_DEBATE as AGENT_ID,
)
```

## Denied

- No `sessions_send` calls.
- No write to `strategy_lineage` (qr_qa only).
- No use of sub-agents — sequential processing only.
- No web access — debate is informed by what risk and algo already produced.
