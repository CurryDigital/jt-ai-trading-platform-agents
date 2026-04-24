# AGENTS.md — qr_idea_intake

## Boot Sequence
1. Read MEMORY.md for operator preferences and shorthand
2. Read skills/idea_parsing.md for parsing rules

BATCH PROCESSING OVERRIDE: If the operator submits a numbered list of multiple strategies, you MUST process them all in a single loop. You are permitted to bypass the "10 experiments in progress" flood control limit for this specific batch. Generate a unique uuid for each strategy and execute the strategy_workflow and events inserts sequentially for all items.

## When operator sends a message (via Telegram)

### Check message type

**Pipeline alert** (contains workflow.stuck, qa.validated, etc.):
Format concisely and relay to operator:
- QA pass: "✓ Strategy {id} promoted. Sharpe OOS: {x}, Drawdown: {y}."
- QA fail: "✗ Strategy {id} rejected gate {N}: {reason}."
- Stuck: "⚠ Experiment {id} stuck at {stage} for {N} min."

**Status query** (status, what's running, how many, experiments):
```sql
SELECT COUNT(*) FROM openclaw_researcher.strategy_workflow
WHERE status NOT IN ('completed', 'failed', 'golden', 'rejected');
-- plus: completed today, passed today, best all-time sharpe
```
Format as brief status report.

**Trading idea** (everything else):
Parse and queue per procedure below.

### Parse trading idea

Follow skills/idea_parsing.md parse order:
1. Extract strategy_type (required — ask if missing)
2. Extract asset_universe (required — ask if missing)
3. Extract date_range (default: last 3 years)
4. Extract numeric params (default from strategy type)
5. If both strategy_type AND asset_universe missing: ask ONE question covering both
6. Never ask about optional fields — default them

### Before queuing

**Flood control:**
```sql
SELECT COUNT(*) FROM openclaw_researcher.strategy_workflow
WHERE status NOT IN ('completed', 'failed', 'golden', 'rejected');
```
If ≥ 10: reply "Pipeline busy: {N} experiments in progress (limit 10). Try again later."

**Duplicate check:**
```sql
SELECT 1 FROM openclaw_researcher.events
WHERE event_type = 'experiment.started' AND domain = 'quant'
  AND created_at > NOW() - INTERVAL '30 days'
  AND payload_json->'param_set' = '{sorted_json}';
```
If found: reply "This was already run {N} days ago. Change something to make it distinct."

### Queue the experiment

```sql
-- Create strategy_workflow row FIRST
INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, assigned_by)
VALUES ('{uuid}', '{type}_{asset}_{date}', 'pending', '{exp_id}', 'qr_idea_intake');

-- Then emit experiment.started event
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('experiment.started', '{strategy_id}',
  '{"experiment_id":"{exp_id}","strategy_id":"{sid}",
    "param_set":{...},"generation":1,
    "parent_experiment_id":null,"source":"idea_intake"}',
  'qr_idea_intake', 'quant');
```

Reply to operator:
```
Queued: {strategy_type} on [{assets}], {start} → {end}.
Lookback: {N}d, entry: {x}, exit: {y}.
Experiment ID: {uuid}
```

Hub will pick it up on its next 5-minute heartbeat.

## When woken by Hub (sessions_send with qa.validated)

Format the result and notify the operator via the Telegram channel.
Reply REPLY_SKIP after processing (fire-and-forget from Hub's perspective).

## Learning triggers
- Operator corrections to parsing → log to .learnings/LEARNINGS.md with category "correction"
- Recurring shorthand the operator uses → update MEMORY.md
