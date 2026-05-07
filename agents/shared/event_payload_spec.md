# Event Payload Specification

Canonical payload structure for every event type in the pipeline.
Agents must emit exactly these fields. Downstream agents depend on
these keys being present and correctly typed.

---

## experiment.started
Producer: Idea Intake, Exp. Manager
Consumer: DE

```json
{
  "experiment_id": "uuid-string",
  "param_set": { ... },
  "generation": 1,
  "parent_experiment_id": "uuid-string or null",
  "source": "idea_intake | exp_manager"
}
```

---

## dataset.ready
Producer: DE
Consumer: Algo

```json
{
  "experiment_id": "uuid-string",
  "dataset_id": "uuid-string",
  "version": "v1.0.0",
  "asset_universe": ["AAPL", "MSFT"],
  "date_range": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD" },
  "row_count": 1240,
  "quality_flags": []
}
```

quality_flags: empty array = all gates passed.
Non-empty: list of flag names e.g. ["missing_bars"] — gate passed anyway (borderline).

---

## backtest.completed
Producer: Algo
Consumer: Risk

```json
{
  "experiment_id": "uuid-string",
  "strategy_id": "uuid-string",
  "dataset_id": "uuid-string",
  "status": "completed | timeout",
  "metrics": {
    "sharpe_is": 1.42,
    "sharpe_oos": 0.87,
    "sharpe_ratio_is_oos": 0.61,
    "returns_annualised_is": 0.18,
    "returns_annualised_oos": 0.11,
    "max_drawdown": -0.14,
    "win_rate": 0.54,
    "trade_count_is": 48,
    "trade_count_oos": 41,
    "avg_holding_days": 6.2,
    "turnover_rate": 0.85
  }
}
```

All metric keys are mandatory. Set to 0.0 if uncomputable.
max_drawdown is always a negative float (e.g. -0.14 not 0.14).

---

## risk.evaluated
Producer: Risk
Consumer: QA

```json
{
  "experiment_id": "uuid-string",
  "strategy_id": "uuid-string",
  "risk_score": 0.12,
  "approved": true,
  "flags": [],
  "thresholds_used": {
    "max_drawdown": -0.20,
    "min_sharpe_oos": 0.50,
    "min_sharpe_ratio": 0.60,
    "high_turnover": 2.00,
    "low_trade_count": 30
  },
  "notes": "All thresholds clear. Drawdown -0.14, Sharpe OOS 0.87, IS/OOS 0.61.",
  "param_set": { ... }
}
```

Always emitted — even on rejection (approved=false).
flags: any subset of [high_drawdown, low_sharpe_oos, overfitting_risk,
                       high_turnover, low_trade_count, zero_trades, negative_oos]

---

## qa.validated (pass)
Producer: QA
Consumer: Exp. Manager, Idea Intake

```json
{
  "event_id": "triggering-risk-evaluated-event-uuid",
  "strategy_id": "uuid-string",
  "experiment_id": "uuid-string",
  "passed": true,
  "failed_gate": null,
  "rejection_reason": null,
  "promoted_to_lineage": true,
  "metrics_summary": {
    "sharpe_oos": 0.87,
    "max_drawdown": -0.14,
    "trade_count_oos": 41
  }
}
```

## qa.validated (fail)
```json
{
  "event_id": "triggering-risk-evaluated-event-uuid",
  "strategy_id": "uuid-string",
  "experiment_id": "uuid-string",
  "passed": false,
  "failed_gate": 5,
  "rejection_reason": "Failed gate 5: IS/OOS Sharpe ratio 0.62 below threshold 0.75. Likely overfitting.",
  "promoted_to_lineage": false
}
```

---

## workflow.stuck
Producer: Monitor
Consumer: Monitor (self — for re-queue logic), Idea Intake (operator alert)

```json
{
  "experiment_id": "uuid-string",
  "workflow_id": "uuid-string",
  "stuck_at_event": "backtest.completed",
  "agent_id": "qr_algo",
  "elapsed_seconds": 1860,
  "requeued": true,
  "requeue_count": 1
}
```

requeued=true: Monitor deleted event_processing row and re-queued.
requeued=false: second breach — escalated to failed, requires manual intervention.
