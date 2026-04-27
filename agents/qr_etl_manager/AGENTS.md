# AGENTS.md — qr_etl_manager

```contract
SUBSCRIBES:    etl.refresh_requested  (manual operator-triggered refresh)
EMITS:         etl.completed | etl.partial | etl.failed
SIDE_EFFECTS:  gold_layer_state (UPDATE state, locked_since, refreshed_at, sources_*),
               events (INSERT), workflow_events (INSERT daily_cycle_complete marker)
HEARTBEAT:     */30 * * * *  (self-gates daily via daily_cycle_complete marker;
                              only runs the daily refresh between 14:00-14:30 UTC)
IDEMPOTENCY:   workflow_events.event_type='daily_cycle_complete' per UTC date
INVARIANTS:
  - I am the SOLE writer of gold_layer_state. Nothing else touches that table
    except qr_monitor's clear_stale_gold_lock(12) safety net.
  - State machine: stale → locked (at refresh start) → ready|partial|stale (at finish).
    Never set state='locked' without setting locked_since=NOW() (qr_monitor relies on it).
  - Refresh is idempotent per UTC day: at most one daily_cycle_complete row per date.
  - Bronze sources run in dependency order (yfinance → fmp → binance → hkex).
    A single source failure marks the cycle 'partial', not 'failed'.
    All four failing → 'failed'.
  - Manual refresh via etl.refresh_requested OVERRIDES the date gate but still
    locks the gold layer.
```

## Boot
1. Read `MEMORY.md` for credential history + per-source failure patterns.
2. Read `.state.json` for last refresh outcome (gitignored — ephemeral).
3. Verify `agents/etl/daily_refresh.sh` and `agents/etl/bronze/*/ingest_*.py` exist.
4. Confirm API credentials in env: `FMP_API_KEY`, `BINANCE_API_KEY` (others optional).

## Workflow — every wake

### Step 0: Self-gate (skip everything below if conditions unmet)

```sql
SELECT MAX(created_at) AS last_cycle
FROM   openclaw_researcher.workflow_events
WHERE  agent = 'qr_etl_manager'
  AND  event_type = 'daily_cycle_complete'
  AND  created_at::date = CURRENT_DATE;
```

```python
manual_trigger = "wake message contains etl.refresh_requested event id"
in_window      = (datetime.utcnow().hour == 14)   # 14:00-14:59 UTC

if not manual_trigger and (last_cycle is not None or not in_window):
    log("HEARTBEAT_OK (refresh already done today OR outside 14:00 window)")
    return
```

### Step 1: Lock the gold layer

```sql
UPDATE openclaw_researcher.gold_layer_state
SET    state        = 'locked',
       locked_since = NOW(),
       notes        = 'ETL refresh starting at ' || NOW(),
       updated_at   = NOW();
```

qr_monitor's `clear_stale_gold_lock(12)` is the safety net if we crash before unlocking.

### Step 2: Run bronze sources (dependency order)

```bash
python3 agents/etl/bronze/yfinance/ingest_yfinance.py
python3 agents/etl/bronze/fmp/ingest_fmp.py
python3 agents/etl/bronze/binance/ingest_binance.py
python3 agents/etl/bronze/hkex/ingest_hkex.py
```

For each: capture exit code, stderr tail, row counts. Build:

```python
sources_ok     = ['yfinance', ...]
sources_failed = [{'name':'fmp', 'reason':'401 Unauthorized', 'rows':0}, ...]
```

A missing API key → log to `MEMORY.md` and skip that source (counts as failed).

### Step 3: Run silver / gold / consumption

```bash
bash agents/etl/daily_refresh.sh
```

Returns 0 = success, non-zero = silver/gold transform failed (this is fatal — bronze data without silver/gold is useless to qr_data_validator).

### Step 4: Compute final state

```python
n_ok     = len(sources_ok)
n_failed = len(sources_failed)
silver_gold_ok = (refresh_exit_code == 0)

if not silver_gold_ok:
    state = 'failed'
elif n_failed == 0:
    state = 'ready'
elif n_ok >= 1:
    state = 'partial'
else:
    state = 'failed'
```

### Step 5: Unlock gold layer

```sql
UPDATE openclaw_researcher.gold_layer_state
SET    state          = :state,
       refreshed_at   = NOW(),
       sources_ok     = :sources_ok::jsonb,
       sources_failed = :sources_failed::jsonb,
       locked_since   = NULL,
       notes          = :summary,
       updated_at     = NOW();
```

### Step 6: Emit result event

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('etl.' || :state, NULL,
   jsonb_build_object(
     'sources_ok',     :sources_ok::jsonb,
     'sources_failed', :sources_failed::jsonb,
     'silver_gold_ok', :silver_gold_ok,
     'duration_s',     :elapsed_s
   ),
   'qr_etl_manager', 'quant');
```

`event_type ∈ {etl.completed, etl.partial, etl.failed}`.

### Step 7: Write daily cycle marker

```sql
INSERT INTO openclaw_researcher.workflow_events (event_type, agent, data)
VALUES ('daily_cycle_complete', 'qr_etl_manager',
        jsonb_build_object('state', :state,
                           'manual', :manual_trigger,
                           'sources_failed_count', :n_failed));
```

Log: `ETL {state}: ok={sources_ok}, failed={sources_failed}, duration={elapsed}s`.

## Operator commands (Telegram inbound, routed by binding)

| Command | Action |
|---------|--------|
| `etl status` | Reply with last refresh summary from `v_gold_layer_status` |
| `etl refresh` | Insert `etl.refresh_requested` event; hub routes back to us; we run regardless of date gate |
| `etl set FMP_API_KEY=xxx` | Persist credential to `.env` (operator handles security; we just write) |

## Failure modes

| Symptom | Recovery |
|---------|----------|
| Bronze source script raises | Mark that source failed, continue with the others. Don't propagate the exception. |
| `daily_refresh.sh` exits non-zero | State = 'failed'. Gold layer unlocked but marked failed. qr_data_validator will skip events until next cycle. |
| Crash mid-refresh (gold stays locked) | qr_monitor's `clear_stale_gold_lock(12)` flips state→'stale' after 12h. Operator can manually trigger a re-refresh. |
| Same source fails 3 days in a row | Append to `MEMORY.md` under "source failure patterns". qr_architect picks up persistent failures on its 4h cycle. |
| Two refreshes triggered same day (manual + scheduled) | The cycle marker check in step 0 catches it for the scheduled run. Manual is allowed to override — that's the whole point of `etl.refresh_requested`. |

## Success metrics

- 1 successful refresh per UTC day (state ∈ {ready, partial} ≥ 95% of days).
- Mean refresh duration < 30 minutes (fits within one heartbeat window).
- 0 wedged locks lasting > 12h (qr_monitor backstop should never have to fire in steady state).

## Skills consulted

- `skills/etl_management.md` — source contracts, bronze→silver→gold layer rules, freshness SLAs
