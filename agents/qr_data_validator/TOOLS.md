# TOOLS.md — qr_data_validator

## Database

- **Schema:** `openclaw_researcher` (writable) + `gold` (read-only view)
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables / views I read

- `v_data_validator_work` — primary work queue (joins gold_layer_state)
- `gold.stock_metrics_history` — coverage, history, earliest-date checks
- `gold_layer_state` — already joined in the view, but readable for diagnostics
- `workflow_events` — retry-count lookup

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `events`            | INSERT (`dataset.ready`) | every successful validation |
| `events`            | INSERT (`workflow.stuck`) | retry count exceeded OR unknown gold state |
| `strategy_workflow` | UPDATE (status, dataset_id, updated_at) | every successful validation |
| `event_processing`  | INSERT (idempotency) | only after the dataset.ready event commits |
| `workflow_events`   | INSERT (audit log) | each gate, retry, skip |

## Constants imported

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_DATA_VALIDATOR as AGENT_ID,
    DE_MISSING_BAR_TOLERANCE,    # 0.10  (10% missing bars max)
    DE_PRICE_SPIKE_STDDEV,       # 5.0
    DE_MIN_HISTORY_MULTIPLIER,   # 2.0
    MAX_RETRY_COUNT,             # 2
)
```

## Denied

- No `sessions_send` (only qr_hub may dispatch).
- No write to `risk_config`, `routing_rules`, or `gold_layer_state` (ETL Manager + Architect own those).
- No web access — all data comes from gold layer.
