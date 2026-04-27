# TOOLS.md — qr_macro_sentinel

## Database

- **Schema:** `openclaw_researcher` (writable) + `gold` (read-only)
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables / views I read

- `macro_events` — precedent lookup + audit backfill
- `workflow_events` — self-gate marker
- `gold.stock_metrics_history` — actual_impact computation in audit cycle

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `macro_events`      | INSERT | every assessed event (regardless of confidence) |
| `macro_events`      | UPDATE (actual_impact) | audit cycle (every 4th scan) |
| `strategy_workflow` | INSERT | high-confidence + precedent emissions ONLY |
| `events`            | INSERT (`experiment.started`) | high-confidence + precedent emissions ONLY |
| `workflow_events`   | INSERT (`macro_scan_complete`) | end of every cycle |

## External tools

| Tool | Use |
|------|-----|
| Brave Search API | one query per 2h scan; rotates through the watchlist in `AGENTS.md` |
| Web fetch (read-only) | source verification when search results are inconclusive |

## Constants

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_MACRO_SENTINEL as AGENT_ID,
)
```

## Denied

- No `sessions_send`.
- No write to `strategy_lineage`.
- No emission without confidence='high' AND ≥ 3 historical precedents — quality > volume.
- No more than one Brave query per scan.
