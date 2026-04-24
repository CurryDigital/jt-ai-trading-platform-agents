## Agent Topology

ISOLATED AGENTS (always-on, independent lifecycle):
- Hub → event router, triggered by any pending event
- Monitor → watchdog, runs on schedule
- Exp. Manager → research loop, triggered by qa.validated or manual

PIPELINE SUBAGENTS (sequential, share experiment context):
- DE → dataset.ready (trigger: experiment.started)
- Algo → backtest.completed (trigger: dataset.ready)
- Risk → risk.evaluated (trigger: backtest.completed) ← NEW
- QA → qa.validated (trigger: risk.evaluated)

FULL FLOW:
Exp. Manager
 → experiment.started
 → Hub routes to DE
 → dataset.ready
 → Hub routes to Algo
 → backtest.completed
 → Hub routes to Risk
 → risk.evaluated
 → Hub routes to QA
 → qa.validated
 → strategy_lineage (if passed)
 → Exp. Manager reacts (generates next params)

Monitor watches all in-progress events and emits 
workflow.stuck if any breach their timeout threshold.

## Domain Separation
Same database. Two domains: quant and platform.
Routing key: (domain, event_type) → target_agents[]
Platform is fully isolated. Hub sees both. 
All other agents see only their domain.

## Existing Infrastructure (do not recreate)
Tables: agent_work_queue, event_processing, events, 
routing_rules, strategy_lineage, strategy_workflow, 
workflow_events

Views: v_algo_work, v_de_work, v_event_status, 
v_pending_events, v_pending_strategies, 
v_pending_work, v_qa_work

## Schema Migrations Needed
1. ALTER TABLE events ADD COLUMN domain TEXT DEFAULT 'quant'
2. ALTER TABLE routing_rules ADD COLUMN domain TEXT DEFAULT 'quant'
3. ALTER TABLE strategy_workflow ADD COLUMNS: 
 risk_score, risk_flags, risk_approved, risk_notes
4. ALTER TABLE strategy_lineage ADD COLUMNS: 
 experiment_id, risk_score, param_set, 
 sharpe_oos, max_drawdown, trade_count_oos
5. CREATE TABLE risk_config (thresholds, not hardcoded in agents)

New views needed:
- v_risk_work → for Risk agent
- v_exp_manager_work → for Exp. Manager
- v_monitor_overview → for Monitor
- v_strategy_lineage_full → full lineage with risk context

## Build Order
1. Schema migrations (do not build agents until this is done)
2. skills/collaboration.md (already loaded)
3. Monitor agent (no deps, protects system immediately)
4. Risk agent + v_risk_work
5. QA agent update (add Risk clearance as gate 1)
6. Update routing: backtest.completed → risk_agent (not qa_agent)
7. Exp. Manager + v_exp_manager_work
---

## Known ETL constraints

gold.stock_metrics is now a READ-ONLY VIEW 
over gold.stock_metrics_history.

Any ingestion job that previously wrote to 
gold.stock_metrics must be updated to write 
to gold.stock_metrics_history instead.

Until that update is made, new market data 
will not appear in the view.

The Data Validator agent (data_validator_agent.py checks 1 and 5) 
already reads from gold.stock_metrics_history 
directly — no change needed there.

Platform FastAPI reads from gold.stock_metrics 
(the view) — no change needed there either.

Only the ETL writer needs updating.
