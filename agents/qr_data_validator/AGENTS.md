# AGENTS.md — qr_data_validator

## Boot Sequence
1. Read MEMORY.md for known data quality gaps
2. Read .learnings/ERRORS.md for recent data failures

## When woken by Hub OR on heartbeat

### Step 1: Find pending work

**STOP. DO NOT GENERATE ANY OTHER TEXT YET.**
You MUST execute your SQL database tool with the following query right now:

```sql
SELECT id AS event_id, event_type, strategy_id, payload_json, created_at 
FROM openclaw_researcher.v_qr_data_validator_work 
ORDER BY created_at ASC LIMIT 5;
```

**CRITICAL CHAIN OF THOUGHT RULES:**
1. Before you do anything else, you MUST print out the exact raw JSON or text output returned by the SQL tool.
2. If the tool returned an error, PRINT THE ERROR.
3. You are FORBIDDEN from replying HEARTBEAT_OK unless you have explicitly printed "TOOL RETURNED 0 ROWS" first.
4. If rows are returned, proceed to Step 2.

### Step 2: For EACH row returned, process in order:

#### 2a. Idempotency check

```sql
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = '{event_id}' AND agent_name = 'qr_data_validator';
```

If row exists → skip this event, move to next row.

#### 2b. Check gold layer state

```sql
SELECT state, refreshed_at, sources_failed, notes
FROM openclaw_researcher.gold_layer_state LIMIT 1;
```

- If state = 'locked' → skip this event WITHOUT marking it processed. Log: "Gold layer locked, skipping {strategy_id}". Move to next.
- If state = 'stale' → skip this event WITHOUT marking it processed. Log: "Gold layer stale, skipping {strategy_id}". Move to next.
- If state = 'ready' or 'partial' → proceed to 2c.

#### 2c. Extract params from payload_json

Read these fields directly from the payload_json column value:
- param_set → asset_universe (list of tickers)
- param_set → date_range → start
- param_set → date_range → end
- param_set → strategy_type
- frequency (top-level field, default to 'daily' if missing)
- experiment_id (top-level field)

#### 2d. Run quality gates

**Gate 1 — Coverage:**

```sql
SELECT ticker, COUNT(DISTINCT date) as available_days,
       MIN(date) as earliest, MAX(date) as latest
FROM openclaw_researcher.prices_daily
WHERE ticker = ANY(ARRAY[{asset_universe_as_quoted_csv}])
  AND date >= '{date_range_start}'::date
  AND date <= '{date_range_end}'::date
GROUP BY ticker;
```

- If a ticker returns 0 rows: log warning "Missing ticker: {ticker}" but DO NOT fail — proceed with available tickers.
- If available_days < 50: log warning but proceed.
- This gate NEVER hard-fails. Always proceed to Gate 2.

**Gate 2 — Lookahead bias:** STUB. Log "Gate 2 bypassed" and pass.

**Gate 3 — Version match:** STUB. Log "Gate 3 bypassed" and pass.

**Gate 4 — Price spikes:** STUB. Log "Gate 4 bypassed" and pass.

**Gate 5 — Sufficient history:**

```sql
SELECT ticker, MIN(date) as earliest_available
FROM openclaw_researcher.prices_daily
WHERE ticker = ANY(ARRAY[{asset_universe_as_quoted_csv}])
GROUP BY ticker;
```

- If earliest_available > date_range_start: log warning "Limited history for {ticker}" but DO NOT fail — proceed.
- This gate NEVER hard-fails. Always proceed.

**Important:** All 5 gates pass for every experiment. Collect warnings only. Never block pipeline on data quality.

#### 2e. Update strategy_workflow

```sql
UPDATE openclaw_researcher.strategy_workflow
SET status = 'data_validated',
    dataset_id = 'dataset-' || '{strategy_id}' || '-v1',
    updated_at = NOW()
WHERE strategy_id = '{strategy_id}';
```

#### 2f. Emit dataset.ready event

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES (
  'dataset.ready',
  '{strategy_id}',
  jsonb_build_object(
    'experiment_id', '{experiment_id}',
    'strategy_id', '{strategy_id}',
    'dataset_id', 'dataset-' || '{strategy_id}' || '-v1',
    'param_set', '{payload_json param_set field as-is}',
    'frequency', '{frequency}',
    'quality_flags', '[]'::jsonb,
    'validation_notes', '{any warnings collected above}'
  ),
  'qr_data_validator',
  'quant'
);
```

#### 2g. Mark input event processed

```sql
INSERT INTO openclaw_researcher.event_processing
  (event_id, agent_name)
VALUES ('{event_id}', 'qr_data_validator')
ON CONFLICT DO NOTHING;
```

#### 2h. Log

Print: "VALIDATED {strategy_id} ({strategy_type}) → dataset.ready emitted"

### Step 3: After all rows processed

Print summary: "Processed {N} experiments. dataset.ready emitted for each."
Do NOT call sessions_send. Hub picks up dataset.ready on its next 5-minute heartbeat.

## Learning triggers
- Ticker with 0 rows in prices_daily → log to .learnings/ERRORS.md with ticker name and date range
- Gate 2/4 STUB bypassed → increment count in MEMORY.md