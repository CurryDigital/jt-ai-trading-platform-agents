# TOOLS.md — qr_algo

## Database

- **Schema:** `openclaw_researcher` (writable) + `gold` (read-only view).
- **Auth:** static password from `/home/ubuntu/.openclaw/.env::DB_PASSWORD`. NOT IAM/boto3.

## Tables / views I read

- `v_qr_algo_work` — primary work queue
- `gold.stock_metrics_history` — price data for the backtest
- `strategy_workflow` — to confirm we have a row before INSERT (avoid orphan trade ledger)

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `strategy_backtest_trades` | bulk INSERT | every backtest — committed FIRST |
| `strategy_workflow`        | UPSERT (metrics, status, dataset_id) | every backtest — committed AFTER ledger |
| `events`                   | INSERT (`backtest.completed` with `status ∈ {completed, timeout}`) | end of every cycle |
| `event_processing`         | INSERT (idempotency) | end of every cycle |
| `workflow_events`          | INSERT (audit) | start + end of each backtest |

## Constants imported

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_ALGO as AGENT_ID,
    BACKTEST_TIMEOUT_MINUTES,    # 30
    BACKTEST_IS_OOS_SPLIT,       # 0.70
    TRANSACTION_COST_PCT,        # 0.0005 (5 bps)
    RISK_FREE_RATE,              # 0.04
    ANNUALISATION_FACTOR,        # 252
)
```

## Filesystem

- `/tmp/backtest_<strategy_id>.py` — ephemeral generated backtest script. Always remove after emitting `backtest.completed`. Survival of these files indicates a crashed backtest worth investigating.

## Denied

- No `sessions_send` calls (hub-only).
- No web access. All data comes from `gold.stock_metrics_history`.
- No write to `strategy_lineage` (qr_qa only — promotion is atomic with `qa.validated`).
- No reads of `risk_config` (that belongs to qr_risk and qr_qa — separating concerns prevents accidental "tune to fit" loops).
