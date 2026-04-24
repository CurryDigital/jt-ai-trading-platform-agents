# AGENTS.md — qr_etl_manager

## Boot Sequence
1. Read MEMORY.md for credential history and source failure patterns.
2. Read .state.json for last refresh status.

## URGENT OVERRIDE: INITIATE REFRESH
Whenever you receive a command to refresh, you MUST follow these exact steps sequentially:

### Step 2: Run bronze sources

For each source, execute the ingestion script:
```bash
python3 agents/etl/bronze/yfinance/ingest_yfinance.py
python3 agents/etl/bronze/fmp/ingest_fmp.py       # requires FMP_API_KEY
python3 agents/etl/bronze/binance/ingest_binance.py # requires BINANCE_API_KEY
python3 agents/etl/bronze/hkex/ingest_hkex.py
```

Track which sources succeed and which fail.

### Step 3: Run silver/gold/consumption

```bash
bash agents/etl/daily_refresh.sh
```

### Step 4: Unlock gold layer

```sql
UPDATE openclaw_researcher.gold_layer_state
SET state = '{ready|partial|stale}',
    sources_ok = '{ok_list}', sources_failed = '{fail_list}',
    locked_since = NULL, refreshed_at = NOW(),
    notes = '{summary}', updated_at = NOW();
```

### Step 5: Emit result event

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('{etl.completed|etl.partial|etl.failed}', NULL,
  '{"sources_ok":[...],"sources_failed":[...]}',
  'qr_etl_manager', 'quant');
```

## Operator commands (via Telegram, routed by binding)

- "status" → report last refresh summary
- "refresh" → trigger manual refresh
- "KEY=value" → set API credential in environment
