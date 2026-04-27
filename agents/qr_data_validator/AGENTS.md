# AGENTS.md — qr_data_validator

```contract
SUBSCRIBES:    experiment.started
EMITS:         dataset.ready, workflow.stuck (only when gold layer is locked/stale or 5 quality checks fail twice)
SIDE_EFFECTS:  strategy_workflow (UPDATE status='data_validated', dataset_id), events (INSERT)
HEARTBEAT:     */30 * * * *
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_data_validator')
INVARIANTS:
  - The gold layer is the SOURCE OF TRUTH. If state ∈ {locked, stale}, do NOT
    mark events processed — they re-fire on the next 30-min cycle once ETL completes
    OR qr_monitor auto-clears the lock (12h timeout).
  - Quality checks NEVER hard-fail the pipeline at this stage. They emit warnings
    in the dataset.ready payload; downstream gates (qr_risk, qr_qa) decide go/no-go.
  - Retry counter is per-experiment_id, not per-event. After MAX_RETRY_COUNT (2)
    failures, emit workflow.stuck and stop trying.
```

## Boot
1. Read `MEMORY.md` for known data quality gaps per ticker / time range.
2. Read `.learnings/ERRORS.md` for recent data failures.
3. Read `agents/shared/constants.py::DE_*` for tolerances (`DE_MISSING_BAR_TOLERANCE=0.10`, `DE_PRICE_SPIKE_STDDEV=5.0`, `DE_MIN_HISTORY_MULTIPLIER=2.0`, `MAX_RETRY_COUNT=2`).

## Workflow — every wake (heartbeat or hub-dispatched event)

### Step 1: Pull pending work

```sql
SELECT event_id, event_type, strategy_id, payload_json, created_at,
       gold_layer_state, gold_refreshed_at, gold_sources_failed
FROM   openclaw_researcher.v_data_validator_work
ORDER  BY created_at ASC
LIMIT  5;
```

- 0 rows → `HEARTBEAT_OK` and exit.
- ≥1 row → process each in order, sequentially (no parallelism — gold layer state can change mid-batch).

### Step 2: For each row

#### 2a. Idempotency

```sql
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = :event_id AND agent_name = 'qr_data_validator';
```

If exists → skip silently to next row.

#### 2b. Gold layer gate

The view already joins `gold_layer_state`. Branch on the `gold_layer_state` column:

| state | Action |
|-------|--------|
| `ready` | proceed to 2c |
| `partial` | proceed to 2c — append warning `gold_partial: {sources_failed}` to dataset.ready payload |
| `locked` | skip WITHOUT marking processed. Log `Gold locked, re-queueing {strategy_id}`. qr_monitor auto-unlocks after 12h. |
| `stale` | skip WITHOUT marking processed. Log `Gold stale ({hours}h), waiting for next ETL`. |
| anything else | emit `workflow.stuck(reason='unknown_gold_state:{state}')` and mark processed (loop guard) |

#### 2c. Extract idea spec from payload

```python
asset_universe   = payload['param_set']['asset_universe']
date_range_start = payload['param_set']['date_range']['start']
date_range_end   = payload['param_set']['date_range']['end']
strategy_type    = payload['param_set']['strategy_type']
lookback_window  = payload['param_set'].get('lookback_window', 20)
frequency        = payload.get('frequency', 'daily')
experiment_id    = payload['experiment_id']
```

#### 2d. Run 5 quality checks (collect warnings, never block)

```python
flags = []
```

**Check 1 — Coverage** (REAL):

```sql
SELECT COUNT(DISTINCT date) AS available_days
FROM   gold.stock_metrics_history
WHERE  ticker = ANY(:asset_universe)
  AND  date BETWEEN :start AND :end;
```

Expected trading days ≈ `(end - start).days * 252/365`. If `available_days < 0.90 * expected` → `flags.append('missing_bars')`.

**Check 2 — Lookahead bias** (currently STUB, will tighten in Tier 2):

Verify no feature in `param_set` references a future timestamp. Today this is a structural check — if any param ends in `_lead` or contains a positive offset, flag `lookahead_signal`. Otherwise pass silently.

**Check 3 — Dataset version match** (currently STUB):

`v_data_validator_work` returns `gold_refreshed_at`. If `gold_refreshed_at < experiment.created_at - INTERVAL '24h'` → `flags.append('stale_dataset')`. We tighten this in Tier 2 with explicit dataset versioning.

**Check 4 — Price spikes** (currently STUB):

`flags.append('price_spike_check_skipped')` and proceed. Real implementation reads `gold.stock_metrics_history`, computes daily returns, flags any |z-score| > `DE_PRICE_SPIKE_STDDEV` (5σ).

**Check 5 — Sufficient history** (REAL):

```sql
SELECT MIN(date) AS earliest
FROM   gold.stock_metrics_history
WHERE  ticker = ANY(:asset_universe);
```

Required pre-history start = `:date_range_start - lookback_window * DE_MIN_HISTORY_MULTIPLIER` days. If `earliest > required_start` → `flags.append('insufficient_history')`.

#### 2e. Decide

- All 5 checks clean OR `flags ⊆ {gold_partial, *_skipped}` → proceed to 2f.
- Hard-blocking flag set (`missing_bars`, `insufficient_history`, `lookahead_signal`, `stale_dataset`):
  - Get retry count: `SELECT COUNT(*) FROM workflow_events WHERE event_type='dv_quality_check_failed' AND data->>'experiment_id'=:exp_id;`
  - If `retry_count >= MAX_RETRY_COUNT` → emit `workflow.stuck(reason=str(flags))`, mark processed.
  - Else → log retry, raise `RetryableError` (sdk does NOT mark processed; the next 30-min wake retries).

#### 2f. Update workflow + emit dataset.ready

```sql
UPDATE openclaw_researcher.strategy_workflow
SET    status     = 'data_validated',
       dataset_id = 'dataset-' || strategy_id || '-v1',
       updated_at = NOW()
WHERE  strategy_id = :strategy_id;
```

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('dataset.ready', :strategy_id,
   jsonb_build_object(
     'experiment_id',    :experiment_id,
     'strategy_id',      :strategy_id,
     'dataset_id',       'dataset-' || :strategy_id || '-v1',
     'param_set',        :param_set::jsonb,
     'frequency',        :frequency,
     'quality_flags',    :flags::jsonb,
     'gold_state',       :gold_state,
     'gold_refreshed_at', :gold_refreshed_at
   ),
   'qr_data_validator', 'quant');
```

#### 2g. Mark processed

```sql
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES (:event_id, 'qr_data_validator')
ON CONFLICT DO NOTHING;
```

Log: `VALIDATED {strategy_id} ({strategy_type}) flags={flags}`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| Gold layer stuck `locked` for hours | qr_monitor auto-clears after `GOLD_LAYER_LOCK_TIMEOUT_HOURS` (12h). We loop without marking — eventually unblocks. |
| Asset in `asset_universe` not in `gold.stock_metrics_history` | Single missing ticker is a warning, not a failure. Proceed with available tickers. |
| `MAX_RETRY_COUNT` exceeded | Emit `workflow.stuck`. qr_monitor + qr_idea_intake handle the operator-facing alert. |
| `gold.stock_metrics_history` view inaccessible (permissions drift) | Log error and skip without marking. qr_architect picks up the drift on its 4h cycle. |

## Success metrics

- 100% of `experiment.started` events resolved within one heartbeat (30 min) once gold is `ready`.
- 0 false `workflow.stuck` emissions when gold is `locked`/`stale`.
- ≥ 95% of strategies have `quality_flags = []` at the dataset.ready stage.

## Skills consulted

- `skills/data_quality.md`
- `skills/etl_management.md`
