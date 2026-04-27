# TOOLS.md — qr_etl_manager

## Database

- **Schema:** `openclaw_researcher` (writable for `gold_layer_state`, `events`, `workflow_events`).
- **Bronze landing schemas:** managed by the per-source ingest scripts; this agent does not write bronze tables directly.
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `gold_layer_state` | UPDATE (state='locked', locked_since=NOW()) | step 1 of every refresh |
| `gold_layer_state` | UPDATE (state='ready'/'partial'/'failed', refreshed_at, sources_ok/failed, locked_since=NULL) | step 5 of every refresh |
| `events`           | INSERT (`etl.completed`/`etl.partial`/`etl.failed`) | step 6 of every refresh |
| `workflow_events`  | INSERT (`daily_cycle_complete`) | step 7 of every refresh |

## Tables / views I read

- `gold_layer_state` (`v_gold_layer_status`) — for `etl status` operator command
- `workflow_events` — self-gate check
- `events` — to identify `etl.refresh_requested` triggers in the inbound wake message

## Filesystem

- `agents/etl/bronze/yfinance/ingest_yfinance.py` — bronze
- `agents/etl/bronze/fmp/ingest_fmp.py` — bronze (requires `FMP_API_KEY`)
- `agents/etl/bronze/binance/ingest_binance.py` — bronze (requires `BINANCE_API_KEY`)
- `agents/etl/bronze/hkex/ingest_hkex.py` — bronze
- `agents/etl/daily_refresh.sh` — silver / gold / consumption transforms
- `agents/qr_etl_manager/.state.json` — gitignored runtime state (last refresh outcome cache)
- `agents/qr_etl_manager/.requests/` — gitignored inbound operator request queue

## External tools

| Tool | Use |
|------|-----|
| `python3` | bronze ingest scripts |
| `bash` | `daily_refresh.sh` |
| HTTPS to yfinance, FMP, Binance, HKEX | per-source ingest |

## Constants

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
)
AGENT_ID = 'qr_etl_manager'
```

## Denied

- No `sessions_send`.
- No write to `strategy_workflow`, `strategy_lineage`, or any other agent's surface.
- No `state='ready'` if silver/gold transforms failed — that lies to downstream agents.
- No deletion of historical bronze rows. ETL is append-only.
