# AGENTS.md — qr_algo

```contract
SUBSCRIBES:    dataset.ready
EMITS:         backtest.completed
SIDE_EFFECTS:  strategy_workflow (UPDATE status='backtested', metrics),
               strategy_backtest_trades (bulk INSERT — one row per trade)
HEARTBEAT:     */30 * * * *
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_algo')
INVARIANTS:
  - The trade ledger is the source of truth. metrics.trade_count_is +
    metrics.trade_count_oos MUST equal COUNT(*) of strategy_backtest_trades
    rows for this strategy_id. qr_qa Gate 0 (anti-hallucination) verifies this
    and rejects on mismatch.
  - Drawdown is stored as a NEGATIVE decimal (-0.0383, never 0.0383).
  - 70/30 IS/OOS split by trading days (BACKTEST_IS_OOS_SPLIT=0.70).
  - Transaction cost: TRANSACTION_COST_PCT (0.0005 = 5 bps round-trip) applied per side.
  - Sharpe = (mean_daily_return / std_daily_return) * sqrt(252).
  - CURRENT STATUS: _run_backtest_stub returns hard-coded metrics. Tier 2 replaces
    this with a real backtest reading gold.stock_metrics_history. Until then,
    every strategy scores Sharpe OOS 0.9 / DD -14% — do NOT promote any of these.
```

## Boot
1. Read `MEMORY.md` for known backtest pitfalls + timeout patterns.
2. Read `skills/backtest_engine.md` for metric formulas.
3. Confirm `openclaw_researcher.strategy_backtest_trades` exists and is writable.
4. Load `BACKTEST_TIMEOUT_MINUTES, BACKTEST_IS_OOS_SPLIT, TRANSACTION_COST_PCT, RISK_FREE_RATE, ANNUALISATION_FACTOR` from `agents.shared.constants`.

## Workflow — every wake

### Step 1: Pull pending work

```sql
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM   openclaw_researcher.v_qr_algo_work
ORDER  BY created_at ASC
LIMIT  5;
```

0 rows → `HEARTBEAT_OK`. ≥1 row → process each sequentially (in-process backtests are CPU-bound and we do not parallelise).

### Step 2: For each row

#### 2a. Idempotency

```sql
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = :event_id AND agent_name = 'qr_algo';
```

#### 2b. Extract idea spec

```python
strategy_id   = event.strategy_id or payload['strategy_id']
experiment_id = payload['experiment_id']
dataset_id    = payload['dataset_id']
param_set     = payload['param_set']
frequency     = payload.get('frequency', 'daily')
```

Required `param_set` fields: `strategy_type`, `asset_universe`, `date_range.start`, `date_range.end`, plus type-specific params (lookback_window, entry_threshold, exit_threshold, …).

#### 2c. Run the backtest (current code path = stub; Tier 2 = real)

**Real implementation contract** (replaces `_run_backtest_stub`):

1. Load price data:

   ```sql
   SELECT ticker, date, close, volume
   FROM   gold.stock_metrics_history
   WHERE  ticker = ANY(:asset_universe)
     AND  date BETWEEN :start_padded AND :end;
   -- start_padded = :start - lookback_window * 2 trading days
   ```

2. Implement entry/exit rules from `param_set` per `skills/backtest_engine.md`.
3. Split by trading-day count: first 70% = IS, remaining 30% = OOS (`BACKTEST_IS_OOS_SPLIT`).
4. For each trade, capture: `ticker, period_type ∈ {IS,OOS}, entry_date, exit_date, entry_price, exit_price, pnl_pct, holding_days, exit_reason`.
5. Apply `TRANSACTION_COST_PCT` per side (entry + exit).
6. Compute metrics on **net** returns:

   | Metric | Formula |
   |--------|---------|
   | sharpe_is, sharpe_oos | `(mean(daily_net_returns) - RISK_FREE_RATE/252) / std(daily_net_returns) * sqrt(252)` |
   | sharpe_ratio_is_oos | `sharpe_oos / sharpe_is` (1.0 = no degradation, < 0.5 = severe overfit) |
   | returns_annualised_* | `mean(daily_net_returns) * 252` |
   | max_drawdown | `min(cumulative_pnl_path - cumulative_pnl_max_so_far)` (NEGATIVE) |
   | win_rate | `count(pnl_pct > 0) / total_trades` |
   | trade_count_is, trade_count_oos | row counts in the ledger |
   | avg_holding_days | `mean(holding_days)` |
   | turnover_rate | `total_traded_notional / mean_notional / 252` |
   | cvar (95%) | `mean(worst 5% daily returns)` (NEGATIVE) |
   | max_single_asset_exposure | `max(per_ticker_notional / total_notional)` |

7. If wall-clock elapsed > `BACKTEST_TIMEOUT_MINUTES` (30) → status = `'timeout'`, abort gracefully, emit with whatever metrics are available.

#### 2d. Persist trade ledger FIRST (evidence gate)

```sql
INSERT INTO openclaw_researcher.strategy_backtest_trades
  (strategy_id, ticker, period_type, entry_date, exit_date,
   entry_price, exit_price, pnl_pct, holding_days, exit_reason)
VALUES (:bulk_rows);
```

This MUST commit before step 2e. qr_qa Gate 0 verifies the metrics summary against this ledger — writing metrics without a ledger is hallucination.

#### 2e. Persist summary metrics

```sql
INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, dataset_id, metrics, created_at)
VALUES
  (:strategy_id, :name, 'backtested', :experiment_id, :dataset_id, :metrics::jsonb, NOW())
ON CONFLICT (strategy_id) DO UPDATE SET
  metrics       = EXCLUDED.metrics,
  status        = 'backtested',
  experiment_id = EXCLUDED.experiment_id,
  dataset_id    = EXCLUDED.dataset_id,
  updated_at    = NOW();
```

#### 2f. Emit `backtest.completed`

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('backtest.completed', :strategy_id,
   jsonb_build_object(
     'experiment_id', :experiment_id,
     'strategy_id',   :strategy_id,
     'dataset_id',    :dataset_id,
     'metrics',       :metrics::jsonb,
     'status',        :status              -- 'completed' | 'timeout'
   ),
   'qr_algo', 'quant');
```

#### 2g. Mark processed + cleanup

```sql
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES (:event_id, 'qr_algo')
ON CONFLICT DO NOTHING;
```

Remove any temp scripts written under `/tmp/backtest_{strategy_id}.py` if used.

Log: `BACKTESTED {strategy_id}: sharpe_oos={sharpe_oos:.2f} dd={max_drawdown:.2%} trades={trade_count_oos}`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| `gold.stock_metrics_history` returns empty for asset_universe | Validator should have caught this. Defensive: emit `workflow.stuck(reason='empty_dataset')` and stop. |
| Backtest exceeds `BACKTEST_TIMEOUT_MINUTES` | Emit `backtest.completed(status='timeout')` with partial metrics. Risk + QA decide what to do. |
| Trade ledger commit succeeds but `metrics` write fails | The next 30-min wake retries. Gate 0 in QA will catch any partial-write hallucination later. |
| Generated /tmp/backtest_*.py raises | Log error + traceback to `.learnings/BACKTEST_ERRORS.md`, emit `workflow.stuck(reason='backtest_exception')`. |

## Success metrics

- Time from `dataset.ready` to `backtest.completed` ≤ 30 min P95 (matches `BACKTEST_TIMEOUT_MINUTES`).
- `metrics.trade_count_is + metrics.trade_count_oos == COUNT(strategy_backtest_trades)` for 100% of strategies.
- 0 promotions (`qa.validated.passed=true`) while the stub is still in place — until Tier 2 ships, treat all "golden" strategies as non-promotable.

## Skills consulted

- `skills/backtest_engine.md`
- `skills/strategy_registry.md`
- `skills/observability.md`
