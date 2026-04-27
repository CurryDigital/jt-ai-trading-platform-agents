# HEARTBEAT.md — qr_algo (every 30 min)

```
schedule: */30 * * * *
target:   agent:qr_algo:main
message:  Drain v_qr_algo_work. Run backtest, persist trade ledger FIRST, then summary metrics, emit backtest.completed. Trade count in metrics MUST match COUNT(*) of strategy_backtest_trades — anti-hallucination guard. Full SQL in AGENTS.md.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 1 | Pull up to 5 from `v_qr_algo_work` |
| 2a | Idempotency check |
| 2b | Extract idea spec from payload |
| 2c | Run backtest (current = stub; Tier 2 = real engine) |
| 2d | Persist trade ledger to `strategy_backtest_trades` (BEFORE metrics) |
| 2e | UPSERT `strategy_workflow.metrics` |
| 2f | Emit `backtest.completed` |
| 2g | INSERT `event_processing` + cleanup `/tmp/backtest_*.py` |

## Exit conditions

- 0 rows in v_qr_algo_work → `HEARTBEAT_OK`.
- All rows processed → log `BACKTESTED {N} strategies` and exit.
- Wall-clock for any single backtest exceeds `BACKTEST_TIMEOUT_MINUTES` → emit with `status='timeout'`, do not retry inside this heartbeat.

## Hard rules

- Trade ledger commits BEFORE summary metrics. If you swap the order, Gate 0 in QA cannot tell partial-write from hallucination.
- Drawdown is negative. If you ever store `+0.14`, qr_qa's `abs(max_drawdown)` test still works but operators reading the lineage will get confused. Stay negative.
