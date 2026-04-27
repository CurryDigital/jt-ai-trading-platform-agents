# TOOLS.md — qr_risk

## Database

- **Schema:** `openclaw_researcher`
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables / views I read

- `v_qr_risk_work` — primary work queue
- `risk_config` (name NOT LIKE 'qa_%') — 6 risk thresholds
- `strategy_backtest_trades` — concentration evidence (NOT metrics)

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `strategy_workflow` | UPDATE (risk_score, risk_flags, risk_approved, risk_notes, risk_evaluated_at) | every event |
| `events`            | INSERT (`risk.evaluated`) | every event — pass OR fail |
| `event_processing`  | INSERT (idempotency) | every event |
| `workflow_events`   | INSERT (audit) | start + end |

## Constants imported

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_RISK as AGENT_ID,
    RISK_APPROVAL_THRESHOLD,    # 0.34
    RISK_BORDERLINE_THRESHOLD,  # 0.50
    RISK_WEIGHT_MAX_DRAWDOWN, RISK_WEIGHT_SHARPE_OOS,
    RISK_WEIGHT_SHARPE_RATIO, RISK_WEIGHT_HIGH_TURNOVER,
    RISK_WEIGHT_LOW_TRADE_COUNT,
)
from agents.shared.threshold import check_threshold
```

## Denied

- No write to `risk_config` (operator + qr_architect own threshold tuning).
- No write to `strategy_lineage` (qr_qa only).
- No `sessions_send` (hub-only).
- No reading of QA thresholds (`name LIKE 'qa_%'`) — separating concerns.
- No web access.
