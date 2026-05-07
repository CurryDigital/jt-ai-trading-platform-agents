# AGENTS.md — qr_qa

```contract
SUBSCRIBES:    risk.evaluated
EMITS:         qa.validated (passed=true)  — promoted to strategy_lineage in same transaction
               qa.validated (passed=false) — with failed_gate ∈ {0..5}
SIDE_EFFECTS:  strategy_lineage (INSERT, atomic with qa.validated event on PASS),
               strategy_workflow (UPDATE status)
HEARTBEAT:     */30 * * * *
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_qa')
INVARIANTS:
  - Lineage promotion is ATOMIC with the qa.validated event. Both INSERTs share
    one connection + one commit. If either fails, both roll back. No promotion
    without an event; no event without a lineage row.
  - Gate 0 (Anti-hallucination): metrics.trade_count_is + metrics.trade_count_oos
    MUST equal COUNT(*) of strategy_backtest_trades. On mismatch — REJECT, regardless
    of how good the metrics look. Hallucinated wins are worse than missed wins.
  - Gates run in strict order, stop at first fail. Reject reason names the gate.
  - QA does NOT consume debate.completed. qr_debate is a parallel observer; we
    proceed on risk.evaluated alone. (Tier 2 may add a Gate 6 conviction check;
    today the conviction column is informational only.)
```

## Boot
1. Read `MEMORY.md` for gate-failure patterns + threshold history.
2. Read `skills/lineage_and_promotion.md` for the atomic write pattern.
3. Confirm `risk_config` has the 4 QA threshold rows (`name LIKE 'qa_%'`):
   `qa_min_sharpe_oos`, `qa_max_drawdown`, `qa_min_trade_count_oos`, `qa_min_sharpe_ratio_is_oos`.
4. Confirm `strategy_lineage` is writable.

## Workflow — every wake

### Step 1: Pull pending work

```sql
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM   openclaw_researcher.v_qr_qa_work
ORDER  BY created_at ASC
LIMIT  5;
```

0 rows → `HEARTBEAT_OK`. Otherwise process each in order.

### Step 2: Idempotency

```sql
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = :event_id AND agent_name = 'qr_qa';
```

### Step 3: Load context + evidence

From the `risk.evaluated` payload:

```python
risk_score    = payload['risk_score']
risk_flags    = payload['risk_flags']
risk_approved = payload['risk_approved']
risk_notes    = payload.get('risk_notes', '')
experiment_id = payload['experiment_id']
```

From `strategy_workflow`:

```sql
SELECT metrics, conviction_score, debate_summary
FROM   openclaw_researcher.strategy_workflow
WHERE  strategy_id = :strategy_id;
```

From the trade ledger (Gate 0 evidence):

```sql
SELECT COUNT(*) AS actual_trade_count,
       SUM(pnl_pct) AS total_raw_pnl
FROM   openclaw_researcher.strategy_backtest_trades
WHERE  strategy_id = :strategy_id;
```

### Step 4: Load QA thresholds

```sql
SELECT name, operator, value
FROM   openclaw_researcher.risk_config
WHERE  enabled = true AND name LIKE 'qa_%';
```

### Step 5: Run 5 gates in strict order, stop at first fail

#### Gate 0 — Anti-hallucination

```python
metrics_count = (metrics['trade_count_is'] or 0) + (metrics['trade_count_oos'] or 0)
if metrics_count != actual_trade_count:
    fail(0, f"Hallucination: metrics report {metrics_count} trades, ledger has {actual_trade_count}")
```

#### Gate 1 — Risk clearance

```python
if not risk_approved:
    fail(1, f"Risk rejected. score={risk_score} flags={risk_flags}")
```

#### Gate 2 — Sharpe OOS

```python
t = thresholds['qa_min_sharpe_oos']
if check_threshold(metrics['sharpe_oos'], t.operator, t.value):
    fail(2, f"sharpe_oos {metrics['sharpe_oos']:.2f} {t.operator} {t.value} — recommend improving signal quality")
```

#### Gate 3 — Max drawdown

```python
t = thresholds['qa_max_drawdown']
abs_dd = abs(metrics['max_drawdown'])
if check_threshold(abs_dd, t.operator, t.value):
    fail(3, f"|max_drawdown| {abs_dd:.2f} {t.operator} {t.value} — recommend smaller position sizing")
```

#### Gate 4 — Trade count

```python
t = thresholds['qa_min_trade_count_oos']
if check_threshold(metrics['trade_count_oos'], t.operator, t.value):
    fail(4, f"trade_count_oos {metrics['trade_count_oos']} {t.operator} {t.value} — recommend longer backtest period")
```

#### Gate 5 — IS/OOS ratio (overfitting)

```python
t = thresholds['qa_min_sharpe_ratio_is_oos']
if check_threshold(metrics['sharpe_ratio_is_oos'], t.operator, t.value):
    fail(5, f"sharpe_ratio_is_oos {metrics['sharpe_ratio_is_oos']:.2f} {t.operator} {t.value} — likely overfitting")
```

### Step 6: Handle result

#### ON PASS — atomic lineage + event

ONE connection, ONE commit:

```sql
BEGIN;

INSERT INTO openclaw_researcher.strategy_lineage
  (strategy_id, experiment_id, dataset_version, backtest_engine_version,
   strategy_parameters, result_metrics, source_event_id,
   sharpe_oos, max_drawdown, trade_count_oos, risk_score,
   param_set, promoted_at)
VALUES
  (:strategy_id, :experiment_id, 'v1.0.0', 'v1.0.0',
   :param_set::jsonb, :metrics::jsonb, :input_event_id,
   :sharpe_oos, :max_drawdown, :trade_count_oos, :risk_score,
   :param_set::jsonb, NOW());

INSERT INTO openclaw_researcher.events
  (id, event_type, domain, strategy_id, payload_json, source_agent, status)
VALUES
  (gen_random_uuid(), 'qa.validated', 'quant', :strategy_id,
   jsonb_build_object(
     'event_id',            :input_event_id,
     'strategy_id',         :strategy_id,
     'experiment_id',       :experiment_id,
     'passed',              true,
     'failed_gate',         null,
     'rejection_reason',    null,
     'promoted_to_lineage', true,
     'metrics_summary',     jsonb_build_object(
       'sharpe_oos',      :sharpe_oos,
       'max_drawdown',    :max_drawdown,
       'trade_count_oos', :trade_count_oos
     )
   ),
   'qr_qa', 'pending');

COMMIT;
```

If either INSERT raises → ROLLBACK, raise — the next 30-min wake retries.

#### ON FAIL — emit rejection

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('qa.validated', :strategy_id,
   jsonb_build_object(
     'event_id',            :input_event_id,
     'strategy_id',         :strategy_id,
     'experiment_id',       :experiment_id,
     'passed',              false,
     'failed_gate',         :failed_gate_int,
     'rejection_reason',    :rejection_reason_text,
     'promoted_to_lineage', false
   ),
   'qr_qa', 'quant');
```

No lineage row. qr_exp_manager will read `failed_gate` and run the directed mutation.

### Step 7: Mark processed

```sql
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES (:event_id, 'qr_qa') ON CONFLICT DO NOTHING;
```

Log: `QA {strategy_id}: passed={passed} gate={failed_gate or '-'} reason={rejection_reason or 'all gates passed'}`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| `strategy_backtest_trades` empty for the strategy | Gate 0 fails (`actual=0 vs metrics=N`). Reject as hallucination. The algo agent is the bug — flag it for qr_architect's next 4h cycle. |
| QA threshold rows missing in `risk_config` | Log CRITICAL. Do not default to "pass" — that promotes garbage. Fail open by raising. |
| Atomic INSERT fails midway (DB drops connection) | Both rolled back by Postgres. The next wake retries from scratch. No half-promoted lineage. |
| Conviction column referenced but `qr_debate` never ran | Today, conviction is informational. Until Tier 2 adds Gate 6, do not gate on it. |

## Success metrics

- 100% of `qa.validated.passed=true` events have a matching `strategy_lineage` row (Gate 0 + atomicity guarantee).
- 0 promotions on Gate 0 fails (anti-hallucination invariant — verify via random audits).
- Median time `risk.evaluated → qa.validated` ≤ 30 min (one heartbeat).

## Skills consulted

- `skills/lineage_and_promotion.md`
- `skills/risk_framework.md`

### FINAL STEP: THE WAKE-UP PING
Immediately after you successfully execute an `INSERT INTO openclaw_researcher.events` statement, you MUST explicitly invoke your `sessions_send` tool to wake up the Hub so it can route your new event.

Execute this exactly:
sessions_send(
  session_key = "agent:qr_hub:main",
  message     = "NEW_EVENT: I have placed a new event in the database. Wake up and poll v_pending_events immediately."
)