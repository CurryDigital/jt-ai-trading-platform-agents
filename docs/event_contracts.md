## Event Catalogue

experiment.started
 Producer: Exp. Manager | Consumer: DE
 Payload: experiment_id, param_set (strategy_type, 
 lookback_window, entry_threshold, exit_threshold, 
 asset_universe, date_range), generation, 
 parent_experiment_id

dataset.ready
 Producer: DE | Consumer: Algo
 Payload: experiment_id, dataset_id, version, 
 asset_universe, date_range, row_count, quality_flags

backtest.completed
 Producer: Algo | Consumer: Risk
 Payload: experiment_id, strategy_id, dataset_id,
 metrics: { sharpe_is, sharpe_oos, sharpe_ratio_is_oos,
 returns_annualised_is, returns_annualised_oos,
 max_drawdown, win_rate, trade_count_is, 
 trade_count_oos, avg_holding_days, turnover_rate }
 status: completed | timeout

risk.evaluated
 Producer: Risk | Consumer: QA
 Payload: experiment_id, strategy_id, risk_score (0-1),
 approved (bool), flags[], thresholds_used, notes
 Always emitted — even on rejection.

qa.validated
 Producer: QA | Consumer: Exp. Manager + strategy_lineage
 Payload (pass): experiment_id, strategy_id, passed=true,
 gates_passed[], metrics_summary, promoted_to_lineage=true
 Payload (fail): experiment_id, strategy_id, passed=false,
 failed_gate (1-5), rejection_reason, promoted_to_lineage=false

workflow.stuck
 Producer: Monitor | Consumer: Hub
 Payload: experiment_id, workflow_id, stuck_at_event, 
 agent_id, elapsed_seconds, requeued, requeue_count

## Timeout Thresholds (Monitor enforces these)
dataset.ready: 10 minutes
backtest.completed: 30 minutes
risk.evaluated: 5 minutes
qa.validated: 5 minutes
experiment.started: 15 minutes
---
