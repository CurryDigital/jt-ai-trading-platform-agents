# TOOLS.md — qr_researcher

## Database

- **Schema:** `openclaw_researcher` (writable) + `gold` (read-only).
- **Auth:** static password from `/home/ubuntu/.openclaw/.env::DB_PASSWORD`.

## Tables / views I read

- `gold.stock_metrics_history` — for data-driven and cross-asset modes
- `gold.ipo_data` — for event-driven and equity research
- `events` (event_type='experiment.started', last 30d) — dedup
- `strategy_lineage` (passed=false) — failure-driven mode
- `macro_events` — cross-asset correlations with regime context
- `workflow_events` (event_type='researcher_cycle_complete') — self-gate

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `strategy_workflow` | INSERT (status='pending') | per generated hypothesis |
| `events`            | INSERT (`experiment.started`, source='qr_researcher') | per generated hypothesis |
| `workflow_events`   | INSERT (`researcher_cycle_complete`) | end of every cycle that did real work |

## External tools

| Tool | Use |
|------|-----|
| Brave Search API | mode=news web research |
| Web fetch (read-only) | source verification when web returns relevant URLs |

## Constants

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_RESEARCHER as AGENT_ID,
    FLOOD_CONTROL_LIMIT,            # 50
    EXP_DUPLICATE_LOOKBACK_DAYS,    # 30
)
```

## Denied

- No `sessions_send` (hub-only).
- No write to `strategy_lineage` (qr_qa only).
- No write to `risk_config` or `routing_rules`.
- Operator chat is the only override that bypasses the 6h self-gate.
