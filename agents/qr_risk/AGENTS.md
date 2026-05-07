# AGENTS.md — qr_risk

```contract
SUBSCRIBES:    backtest.completed
EMITS:         risk.evaluated  (ALWAYS — even on rejection; downstream gates need the score)
SIDE_EFFECTS:  strategy_workflow (UPDATE risk_score, risk_flags, risk_approved, risk_notes, risk_evaluated_at)
HEARTBEAT:     */30 * * * *
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_risk')
INVARIANTS:
  - Thresholds live in risk_config, NOT in code. Reload at the start of every event.
  - 6 named checks: high_drawdown, low_sharpe_oos, concentration_risk, overfitting_signal,
    low_trade_count, tail_risk. Names must match risk_config.name exactly.
  - risk_score = COUNT(flags raised) / 6  ∈ [0.0, 1.0]
  - risk_approved = (risk_score == 0.0). No partial credit.
  - concentration_risk uses the trade ledger (strategy_backtest_trades), not metrics —
    metrics can be hallucinated; trade rows cannot.
```

## Boot
1. Read `MEMORY.md` for threshold-tuning history (when did we last tighten high_drawdown? why?).
2. Read `skills/risk_framework.md` for the evaluation methodology.
3. Confirm `risk_config` has all 6 risk gate rows (`name NOT LIKE 'qa_%'`).

## Workflow — every wake

### Step 1: Pull pending work

```sql
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM   openclaw_researcher.v_qr_risk_work
ORDER  BY created_at ASC
LIMIT  5;
```

0 rows → `HEARTBEAT_OK`. Otherwise, for each row:

### Step 2: Idempotency

```sql
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = :event_id AND agent_name = 'qr_risk';
```

### Step 3: Load metrics + trade evidence

From the event payload:

```python
strategy_id   = event.strategy_id
experiment_id = payload['experiment_id']
metrics       = payload['metrics']         -- summary
status        = payload['status']          -- 'completed' | 'timeout'
```

If `status == 'timeout'`: emit `risk.evaluated(approved=false, flags=['backtest_timeout'])` and stop. Do not run the 6 checks against partial metrics.

Otherwise pull concentration evidence from the ledger (NOT from metrics):

```sql
SELECT ticker,
       COUNT(*) AS trade_count,
       (COUNT(*)::float / SUM(COUNT(*)) OVER ()) AS exposure_pct
FROM   openclaw_researcher.strategy_backtest_trades
WHERE  strategy_id = :strategy_id
GROUP  BY ticker
ORDER  BY exposure_pct DESC
LIMIT  1;
```

Use `exposure_pct` of the top ticker as the concentration signal.

### Step 4: Load thresholds

```sql
SELECT name, operator, value, description
FROM   openclaw_researcher.risk_config
WHERE  enabled = true AND name NOT LIKE 'qa_%'
ORDER  BY name;
```

### Step 5: Evaluate 6 checks (use `agents.shared.threshold.check_threshold`)

For each `(name, operator, value)` in thresholds, evaluate the check below; raise the flag if `check_threshold(metric_value, operator, threshold_value)` is True.

| Check name | Metric source | Notes |
|------------|---------------|-------|
| `high_drawdown` | `metrics['max_drawdown']` | drawdown is negative; threshold typically `<= -0.20` |
| `low_sharpe_oos` | `metrics['sharpe_oos']` | threshold typically `< 0.5` |
| `concentration_risk` | `exposure_pct` from step 3 (NOT metrics) | threshold typically `> 0.30` (30% in one ticker) |
| `overfitting_signal` | `metrics['sharpe_ratio_is_oos']` | threshold typically `< 0.6` |
| `low_trade_count` | `metrics['trade_count_oos']` | threshold typically `< 30` |
| `tail_risk` | `metrics['cvar']` (or `cvar_95`) | threshold typically `> 0.10` |

```python
flags = []
notes = []
for check in checks:
    metric_val = get_metric_for(check.name, metrics, exposure_pct)
    if check_threshold(metric_val, check.operator, check.value):
        flags.append(check.name)
        notes.append(f"{check.name}: {metric_val} vs {check.value} ({check.operator})")

risk_score    = round(len(flags) / 6, 2)
risk_approved = (len(flags) == 0)
```

### Step 6: Write to strategy_workflow

```sql
UPDATE openclaw_researcher.strategy_workflow
SET    risk_score        = :risk_score,
       risk_flags        = :flags::jsonb,
       risk_approved     = :risk_approved,
       risk_notes        = :notes_text,
       risk_evaluated_at = NOW(),
       updated_at        = NOW()
WHERE  strategy_id = :strategy_id;
```

### Step 7: Emit `risk.evaluated` (ALWAYS)

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('risk.evaluated', :strategy_id,
   jsonb_build_object(
     'event_id',      :input_event_id,
     'strategy_id',   :strategy_id,
     'experiment_id', :experiment_id,
     'risk_score',    :risk_score,
     'risk_flags',    :flags::jsonb,
     'risk_approved', :risk_approved,
     'risk_notes',    :notes_text
   ),
   'qr_risk', 'quant');
```

### Step 8: Mark processed

```sql
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES (:event_id, 'qr_risk') ON CONFLICT DO NOTHING;
```

Log: `RISK {strategy_id}: score={score} flags={flags} approved={approved}`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| `risk_config` returns 0 rows | Migration drift. Log CRITICAL, raise. qr_monitor will surface the stuck workflow on its 30-min cycle, qr_architect will notice the empty config on its 4h cycle. |
| Threshold operator unknown | `check_threshold` raises ValueError. Log per-check and skip THAT check (do not silently approve). Continue evaluating the others. |
| `metrics` payload missing a required field | Treat the missing metric as "worst case": e.g. missing `sharpe_oos` defaults to 0.0 → low_sharpe_oos likely raises. The flag fires, the strategy is rejected — fail-safe. |

## Success metrics

- Every `backtest.completed` produces exactly one `risk.evaluated` (Gate 1 in QA depends on this).
- 0 silent skips of the 6 checks (each must either raise a flag or pass cleanly — never "skipped due to error").
- Concentration measured from the trade ledger, not from metrics, on 100% of strategies.

## Skills consulted

- `skills/risk_framework.md`
- `skills/observability.md`

### FINAL STEP: THE WAKE-UP PING
Immediately after you successfully execute an `INSERT INTO openclaw_researcher.events` statement, you MUST explicitly invoke your `sessions_send` tool to wake up the Hub so it can route your new event.

Execute this exactly:
sessions_send(
  session_key = "agent:qr_hub:main",
  message     = "NEW_EVENT: I have placed a new event in the database. Wake up and poll v_pending_events immediately."
)

