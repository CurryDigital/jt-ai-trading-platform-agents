# Skill: Lineage and Promotion

## Purpose
Defines what it means for a strategy to be "promoted", what fields
must be written to strategy_lineage, and how the Exp. Manager should
read and interpret lineage to guide future experiments.

Load this skill: QA agent (writes), Exp. Manager (reads).

---

## Promotion criteria

A strategy is promoted to strategy_lineage if and only if:
1. risk_approved = true (Risk agent cleared it)
2. All 5 QA gates passed

Promotion is permanent. Never delete from strategy_lineage.
Never update result_metrics after insertion — it is a historical record.

---

## strategy_lineage schema (canonical columns)

| column | type | description |
|--------|------|-------------|
| strategy_id | text PK | Unique strategy identifier |
| experiment_id | text | Parent experiment that produced this strategy |
| dataset_version | text | Dataset version used (e.g. 'v1.0.0') |
| backtest_engine_version | text | Engine version used |
| strategy_parameters | jsonb | Full param_set (copy, not reference) |
| result_metrics | jsonb | Full metrics dict from backtest.completed |
| source_event_id | text | The qa.validated event UUID |
| sharpe_oos | real | Denormalised for fast sorting |
| max_drawdown | real | Denormalised for fast sorting |
| trade_count_oos | integer | Denormalised for fast sorting |
| risk_score | real | Risk score at time of promotion |
| param_set | jsonb | Duplicate of strategy_parameters for backward compat |
| promoted_at | timestamp | When QA promoted this strategy |

Always write strategy_parameters AND param_set — both columns are
queried by different parts of the system.

---

## Atomicity requirement

The INSERT into strategy_lineage and the INSERT of the qa.validated
event must happen in the same database transaction (single connection,
single commit). See qa_agent.py `_write_lineage_and_emit()`.

If the transaction fails, neither write commits. The event stays
pending and QA will retry. This prevents the crash window where
a strategy is promoted but no downstream event exists.

---

## How Exp. Manager reads lineage

### Finding top performers for Phase 2 exploitation
```sql
SELECT strategy_id, param_set, sharpe_oos, max_drawdown, experiment_id
FROM strategy_lineage
WHERE promoted_at >= NOW() - INTERVAL '30 days'
ORDER BY sharpe_oos DESC
LIMIT 10
```

### Nightly cycle — last 7 days
```sql
SELECT strategy_id, param_set, sharpe_oos
FROM strategy_lineage
WHERE promoted_at >= NOW() - INTERVAL '7 days'
  AND sharpe_oos > 0.5
ORDER BY sharpe_oos DESC
LIMIT 1
```

### Family pass rate (for pruning/expanding families)
```sql
-- Total experiments in family
SELECT COUNT(*) FROM events
WHERE event_type = 'experiment.started'
  AND payload_json->>'strategy_type' = %s
  AND payload_json->>'asset_universe' = %s

-- Passes in family
SELECT COUNT(*) FROM strategy_lineage sl
JOIN events e ON e.payload_json->>'experiment_id' = sl.experiment_id
WHERE e.payload_json->>'strategy_type' = %s
  AND e.payload_json->>'asset_universe' = %s

pass_rate = passes / total  (if total >= 20, else do not prune)
```

---

## Lineage summary for operator reporting

Weekly summary format:
```
Week of {date}:
  Experiments run: {N}
  QA pass rate: {X}% ({M} promoted)
  Top strategy: {id} — Sharpe OOS {x:.2f}, Drawdown {y:.2f}
  Most common rejection: Gate {N} ({reason_short})
  Recommendation: {one sentence on where to search next}
```

Top strategy recommendation basis:
- If top Sharpe OOS > 1.5: "Continue exploiting {strategy_type} on {asset_universe}"
- If pass rate < 10%: "Broaden search — current params may be over-constrained"
- If gate 5 (IS/OOS ratio) is most common fail: "Reduce lookback_window to address overfitting"
- If gate 4 (trade count) is most common fail: "Extend date_range or reduce thresholds"
