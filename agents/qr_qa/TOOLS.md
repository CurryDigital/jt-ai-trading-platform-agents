# TOOLS.md — qr_qa

## Database

- **Schema:** `openclaw_researcher`
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables / views I read

- `v_qr_qa_work` — primary work queue
- `strategy_workflow` — metrics, conviction_score, debate_summary
- `strategy_backtest_trades` — Gate 0 anti-hallucination evidence
- `risk_config` (name LIKE 'qa_%') — 4 QA thresholds

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `strategy_lineage`  | INSERT | ON PASS only — atomic with qa.validated |
| `events`            | INSERT (`qa.validated` passed=true) | ON PASS — same transaction as lineage |
| `events`            | INSERT (`qa.validated` passed=false) | ON FAIL |
| `event_processing`  | INSERT (idempotency) | every event |
| `workflow_events`   | INSERT (audit) | start + end |

## Constants imported

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_QA as AGENT_ID,
)
from agents.shared.threshold import check_threshold
```

## Denied

- No write to `risk_config` (operator + qr_architect).
- No `sessions_send` (hub-only).
- No reads of risk gates (`name NOT LIKE 'qa_%'`) — that's qr_risk's surface.
- No web access.
- No partial promotions: never INSERT into `strategy_lineage` without committing the matching `qa.validated` event in the same transaction.
