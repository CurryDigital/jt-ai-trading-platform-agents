# AGENTS.md — qr_exp_manager

## Boot Sequence
1. Read MEMORY.md for research landscape and dead-end families
2. Read .learnings/STRATEGY_PATTERNS.md for what works and what doesn't
3. Read skills/experiment_design.md for variant generation rules

## When woken by Hub (sessions_send with qa.validated)

### Step 1: Find my pending work

```sql
SELECT e.id as event_id, e.strategy_id, e.payload_json
FROM openclaw_researcher.events e
LEFT JOIN openclaw_researcher.event_processing ep
  ON e.id = ep.event_id AND ep.agent_name = 'qr_exp_manager'
WHERE e.event_type = 'qa.validated' AND e.domain = 'quant'
  AND ep.event_id IS NULL
ORDER BY e.created_at ASC LIMIT 1;
```

### Step 2: Idempotency + flood control

```sql
-- Idempotency
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = '{event_id}' AND agent_name = 'qr_exp_manager';

-- Flood control: count in-progress experiments
SELECT COUNT(*) FROM openclaw_researcher.strategy_workflow
WHERE status NOT IN ('completed', 'failed', 'golden', 'rejected');
```

If in-progress ≥ 50 → log "Flood control active" and exit WITHOUT marking processed (retry later).

### Step 3: Directed variant generation

Read the qa.validated payload: `passed`, `failed_gate`, `rejection_reason`.

**If QA passed:** Generate 3 variants around the winning param_set.
Each variant changes ONE parameter by ±10-25%.

**If QA failed — DIRECTED MUTATION based on rejection gate:**

| Failed gate | Directed action |
|-------------|----------------|
| Gate 1 (risk rejected) | Reduce position size concept, add stop-loss |
| Gate 2 (low Sharpe) | Increase entry_threshold (+25%), try different timing |
| Gate 3 (high drawdown) | Add stop-loss, reduce holding period |
| Gate 4 (low trade count) | Extend date_range, lower entry_threshold |
| Gate 5 (overfitting) | Simplify: reduce lookback_window, remove one parameter |
| Gate 6 (low conviction) | Reformulate hypothesis, try different asset class |

Generate 1-2 variants for failed strategies (not 3).

### Step 4: Check family health

```sql
-- How many experiments in this family (same strategy_type + asset_universe)?
SELECT COUNT(*) as total,
       COUNT(*) FILTER (WHERE payload_json->>'passed' = 'true') as passed
FROM openclaw_researcher.events
WHERE event_type = 'qa.validated'
  AND payload_json->'param_set'->>'strategy_type' = '{type}'
  AND created_at > NOW() - INTERVAL '30 days';
```

- If total ≥ 20 AND pass rate < 5%: PRUNE — do not generate variants. Log.
- If pass rate > 30% over last 10: EXPAND — generate 5 variants instead of 3.

### Step 5: Deduplicate

For each variant, check if identical param_set was run in last 30 days:
```sql
SELECT 1 FROM openclaw_researcher.events
WHERE event_type = 'experiment.started' AND domain = 'quant'
  AND created_at > NOW() - INTERVAL '30 days'
  AND payload_json->>'param_set' = '{sorted_json}';
```
Skip duplicates silently.

### Step 6: Insert variants

For each unique variant:
```sql
-- Create strategy_workflow row
INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, assigned_by)
VALUES ('{uuid}', '{name}', 'pending', '{exp_id}', 'qr_exp_manager');

-- Emit experiment.started
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('experiment.started', '{strategy_id}',
  '{"experiment_id":"{exp_id}","strategy_id":"{sid}",
    "param_set":{...},"generation":{gen+1},
    "parent_experiment_id":"{parent}","source":"qr_exp_manager"}',
  'qr_exp_manager', 'quant');
```

### Step 7: Mark processed + log

```sql
INSERT INTO openclaw_researcher.event_processing
  (event_id, agent_name) VALUES ('{event_id}', 'qr_exp_manager')
ON CONFLICT DO NOTHING;
```

Log to memory/YYYY-MM-DD.md: variants generated, parent result, gate feedback.

## Nightly heartbeat cycle (16:00 UTC daily)

1. Query strategy_lineage for sharpe_oos > 0.5 in last 7 days
2. If found: generate 5 variants around the best performer
3. If not found: seed 3 random experiments across different strategy types
4. Check skills/strategy_registry.md for underexplored types
5. Log summary to memory/

## Learning triggers
- Dead-end families → add to MEMORY.md
- Directed mutations that lead to QA pass → log the gate→action mapping
- Variants that consistently improve on parent → log the perturbation pattern
