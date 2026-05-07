# Agent Registry

Single source of truth for all agents in the quant research pipeline.
Hub's ROUTING_TABLE and AGENT_SESSIONS must match entries here.

---

## All agents

| Agent | AGENT_ID | Session key | Lifecycle | Entrypoint |
|-------|----------|-------------|-----------|-----------|
| Hub | qr_hub | agent:qr_hub:main | Isolated (always-on) | agents/isolated/hub_agent.py |
| Monitor | qr_monitor | agent:qr_monitor:main | Isolated (always-on) | agents/isolated/monitor_agent.py |
| Idea Intake | qr_idea_intake | agent:qr_idea_intake:main | Isolated (channel listener) | agents/isolated/idea_intake_agent.py |
| ETL Manager | qr_etl_manager | agent:qr_etl_manager:main | Isolated (always-on) | agents/isolated/etl_manager_agent.py |
| Exp. Manager | qr_exp_manager | agent:qr_exp_manager:main | Event-reactive | agents/isolated/exp_manager_agent.py |
| Data Validator | qr_data_validator | agent:qr_data_validator:main | Pipeline subagent | agents/pipeline/data_validator_agent.py |
| Algo | qr_algo | agent:qr_algo:main | Pipeline subagent | agents/pipeline/algo_agent.py |
| Risk | qr_risk | agent:qr_risk:main | Pipeline subagent | agents/pipeline/risk_agent.py |
| QA | qr_qa | agent:qr_qa:main | Pipeline subagent | agents/pipeline/qa_agent.py |

---

## Lifecycle types

**Isolated (always-on)**: persistent while-True loop or persistent channel listener.
Never exits. Start these first. Hub must be up before any events flow.

**Event-reactive**: woken by sessions_send from Hub. Drains
pending events, exits. Independent of pipeline order.

**Pipeline subagent**: woken by sessions_send. Processes one
event, exits. Sequenced by routing rules.

---

## Event ownership

| Agent | Consumes | Emits |
|-------|----------|-------|
| Hub | (all events, routes only) | (nothing — routing only) |
| Monitor | workflow.stuck (self-loop), HEARTBEAT, etl.completed, etl.partial, etl.failed | workflow.stuck |
| Idea Intake | operator message, qa.validated, workflow.stuck, etl.operator_alert | experiment.started |
| ETL Manager | HEARTBEAT, operator message, etl.refresh_requested | etl.completed, etl.partial, etl.failed, etl.operator_alert |
| Exp. Manager | qa.validated, HEARTBEAT | experiment.started (N variants) |
| Data Validator | experiment.started | dataset.ready |
| Algo | dataset.ready | backtest.completed |
| Risk | backtest.completed | risk.evaluated |
| QA | risk.evaluated | qa.validated |

---

## DB access pattern

| Agent | Reads | Writes |
|-------|-------|--------|
| Hub | v_pending_events, routing_rules | event_processing (routing record) |
| Monitor | v_monitor_overview, workflow_events | workflow_events, event_processing (delete for re-queue) |
| Idea Intake | agent_work_queue, v_pending_strategies, strategy_lineage | events |
| ETL Manager | gold_layer_state | events (etl.*), gold_layer_state (writes lock/ready/stale/partial) |
| Exp. Manager | strategy_lineage, events, v_exp_manager_work | events |
| Data Validator | gold.stock_metrics_history, v_data_validator_work, gold_layer_state | event_processing, workflow_events |
| Algo | gold.stock_metrics_history, v_algo_work | strategy_workflow, event_processing, workflow_events |
| Risk | strategy_workflow, risk_config, v_risk_work | strategy_workflow (risk cols), event_processing, workflow_events, events |
| QA | strategy_workflow, risk_config, v_qa_work | strategy_lineage, events (atomic), event_processing, workflow_events |

---

## Spawn order for first deployment

```
1. hub_agent.py           — must be up first; all events flow through it
2. monitor_agent.py       — start in parallel with hub
3. idea_intake_agent.py   — bind to Telegram/WhatsApp channel
4. etl_manager_agent.py   — bind to Telegram (credentials + manual loads)
5. (remaining agents)     — DE, Algo, Risk, QA, Exp. Manager
                            dormant until woken by sessions_send
                            no need to pre-start; OpenClaw spawns on demand
```

---

## Skills per agent

| Agent | Skills |
|-------|--------|
| Hub | collaboration |
| Monitor | collaboration, self_healing, observability |
| Idea Intake | collaboration, idea_parsing, observability |
| ETL Manager | collaboration, etl_management, observability |
| Exp. Manager | collaboration, experiment_design, lineage_and_promotion, observability |
| Data Validator | collaboration, data_quality, etl_contracts, observability |
| Algo | collaboration, backtest_engine, observability |
| Risk | collaboration, risk_framework, observability |
| QA | collaboration, risk_framework, lineage_and_promotion, observability |
