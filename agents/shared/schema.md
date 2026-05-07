# Schema Reference — Authoritative Column Names

DO NOT deviate from these column names. They are locked.
If a query fails with "column does not exist", check here first.

---

## TABLE: events (schema: openclaw_researcher)

| column | type | notes |
|--------|------|-------|
| id | uuid PK | NOT "event_id" |
| event_type | text | NOT "type" |
| domain | text | 'quant' or 'platform' |
| strategy_id | text nullable | DIRECT column — NOT inside payload_json |
| payload_json | jsonb | contains: experiment_id, dataset_id, param_set, metrics |
| source_agent | text | agent that emitted this event |
| status | text | 'pending', 'processing', 'completed', 'failed' |
| created_at | timestamptz | |

payload_json nested keys (NOT direct columns):
- experiment_id
- dataset_id
- param_set (jsonb object)
- metrics (jsonb object)
- generation
- parent_experiment_id
- source ('idea_intake' or 'exp_manager')

Access: payload_json->>'experiment_id'  (text)
        payload_json->'param_set'        (jsonb)

---

## TABLE: event_processing

| column | type | notes |
|--------|------|-------|
| event_id | uuid FK → events.id | |
| agent_name | text | NOT "agent_id" |
| processed_at | timestamptz nullable | null = in_progress |

Idempotency check:
```sql
SELECT 1 FROM event_processing
WHERE event_id = %s AND agent_name = %s
```

---

## TABLE: strategy_workflow

| column | type | notes |
|--------|------|-------|
| strategy_id | text PK | |
| name | text NOT NULL | |
| status | text NOT NULL | |
| experiment_id | text | |
| dataset_id | text | |
| metrics | jsonb | full backtest metrics dict |
| risk_score | real | written by Risk agent |
| risk_flags | text | comma-separated flag names |
| risk_approved | boolean | written by Risk agent |
| risk_notes | text | written by Risk agent |
| risk_evaluated_at | timestamp | written by Risk agent |
| created_at | timestamptz | |
| updated_at | timestamptz | |

---

## TABLE: workflow_events

| column | type | notes |
|--------|------|-------|
| id | integer PK | auto |
| strategy_id | text nullable FK → strategy_workflow | |
| event_type | text | e.g. 'qa_evaluation_started' |
| from_status | text | NOT "status" |
| to_status | text | NOT "status" |
| agent | text | NOT "agent_id" |
| data | jsonb | NOT "metadata" |
| created_at | timestamptz | |

---

## TABLE: routing_rules

| column | type | notes |
|--------|------|-------|
| event_type | text PK | |
| domain | text | |
| target_agent | text | singular text, NOT a JSON array |

No priority column. PK: event_type only.

---

## TABLE: risk_config

| column | type | notes |
|--------|------|-------|
| id | integer PK | |
| name OR threshold_name | text | check actual column name (migration_002 handles both) |
| operator | text | 'gt', 'lt', 'gte', 'lte' |
| value | numeric | threshold value |
| description | text | |
| is_active | boolean | filter: WHERE is_active = true |

Risk agent rows: name starts with 'max_', 'min_', 'high_', 'low_', 'tail_'
QA agent rows: name starts with 'qa_'

---

## TABLE: strategy_lineage

| column | type | notes |
|--------|------|-------|
| strategy_id | text PK | |
| experiment_id | text | |
| dataset_version | text | |
| backtest_engine_version | text | |
| strategy_parameters | jsonb | full param_set copy |
| result_metrics | jsonb | full metrics dict |
| source_event_id | text | qa.validated event UUID |
| sharpe_oos | real | denormalised for sorting |
| max_drawdown | real | denormalised for sorting |
| trade_count_oos | integer | denormalised for sorting |
| risk_score | real | |
| param_set | jsonb | duplicate of strategy_parameters |
| promoted_at | timestamp | |

---

## STATUS FLOW (workflow_events from_status → to_status)

| transition | event_type |
|-----------|-----------|
| pending → in_progress | {agent}_started |
| in_progress → completed | {agent}_completed |
| in_progress → failed | {agent}_failed |
| in_progress → stuck | workflow.stuck |
| in_progress → requeued | monitor_requeue |
| stuck → failed | workflow_failed |

---

## VIEWS

| view | used by | purpose |
|------|---------|---------|
| v_pending_events | Hub | all pending events to route |
| v_de_work | DE | experiment.started events for DE |
| v_algo_work | Algo | dataset.ready events for Algo |
| v_risk_work | Risk | backtest.completed events for Risk |
| v_qa_work | QA | risk.evaluated events for QA |
| v_exp_manager_work | Exp. Manager | qa.validated events to process |
| v_monitor_overview | Monitor | in-progress work with elapsed_minutes |
| v_event_status | Monitor, Exp. Manager | full event status across pipeline |
| v_pending_strategies | Idea Intake, QA | strategies not yet in lineage |
