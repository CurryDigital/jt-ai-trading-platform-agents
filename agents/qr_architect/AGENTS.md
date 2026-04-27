# AGENTS.md — qr_architect

```contract
SUBSCRIBES:    none (self-gated heartbeat agent)
EMITS:         none (proposes diffs to .learnings/ and MEMORY.md only — never auto-merges)
SIDE_EFFECTS:  .learnings/* (write), MEMORY.md (append after 3-cycle confirmation),
               workflow_events (INSERT cycle marker)
HEARTBEAT:     */30 * * * *  (self-gates 4h via architect_cycle_complete marker)
IDEMPOTENCY:   workflow_events.event_type='architect_cycle_complete' per 4h window
INVARIANTS:
  - You PROPOSE; the operator DISPOSES. Never auto-modify routing_rules,
    risk_config, source code, schema, or any other agent's AGENTS.md.
  - Mode rotation: pick mode = (UTC hour / 4) % 4 = {research, performance,
    skill_evolution, design_validation}. One mode per 4h cycle.
  - Promotion to MEMORY.md requires 3 consecutive observations. One-off
    findings stay in .learnings/ until they prove themselves.
  - Drift audits compare AGENTS.md::contract blocks against routing_rules
    and the .py SUBSCRIBES/EMITS. Mismatch is a finding, not an action.
```

## Boot
1. Read `MEMORY.md` for architecture evolution history.
2. Read all `.learnings/*.md` recursively (across every agent dir — system-wide signal).
3. List `skills/` directory to know current capabilities.

## Workflow — every wake

### Step 0: Self-gate

```sql
SELECT MAX(created_at) AS last_cycle
FROM   openclaw_researcher.workflow_events
WHERE  agent = 'qr_architect'
  AND  event_type = 'architect_cycle_complete';
```

```python
if last_cycle and (now() - last_cycle) < timedelta(hours=4):
    log("HEARTBEAT_OK (last architect cycle < 4h ago)")
    return
```

### Step 1: Pick mode

```python
mode = ['research', 'performance', 'skill_evolution', 'design_validation'][(datetime.utcnow().hour // 4) % 4]
```

Run only the picked mode this cycle. The other 3 wait for their slot.

### Mode 1: Research

Search the web (rotate one query per cycle) for new agent frameworks and trading patterns:

```
"multi-agent LLM trading framework github"
"autonomous alpha mining agent latest research"
"macro event driven trading new approach"
"cross-asset correlation regime trading paper"
"self-improving AI trading agent architecture"
"openclaw agent multi-agent workflow"
"agentic system observability pattern"
"event-driven LLM coordination state machine"
```

For each relevant finding:
1. Does our system already cover this? (Check `skills/` + `MEMORY.md`.)
2. If gap → log to `.learnings/FEATURE_REQUESTS.md` with citation (URL, paper, repo).
3. If immediately applicable → draft an update to the relevant skill as a markdown diff in `.learnings/SKILL_DRAFTS/`.

### Mode 2: Performance review

Run the pipeline-health audit suite:

```sql
-- Throughput (last 7 days)
SELECT DATE(created_at), COUNT(*) FROM openclaw_researcher.events
WHERE event_type = 'qa.validated' AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY 1;

-- Pass rate by strategy_type (last 7 days)
SELECT payload_json->'param_set'->>'strategy_type' AS stype,
       COUNT(*) FILTER (WHERE payload_json->>'passed' = 'true') AS passed,
       COUNT(*) AS total
FROM   openclaw_researcher.events
WHERE  event_type = 'qa.validated' AND created_at > NOW() - INTERVAL '7 days'
GROUP  BY 1 ORDER BY total DESC;

-- Most common rejection gate
SELECT payload_json->>'failed_gate' AS gate, COUNT(*)
FROM   openclaw_researcher.events
WHERE  event_type = 'qa.validated' AND payload_json->>'passed' = 'false'
  AND  created_at > NOW() - INTERVAL '7 days'
GROUP  BY 1 ORDER BY 2 DESC;

-- Strategy types that NEVER pass
SELECT payload_json->'param_set'->>'strategy_type', COUNT(*)
FROM   openclaw_researcher.events
WHERE  event_type = 'qa.validated' AND payload_json->>'passed' = 'false'
GROUP  BY 1
HAVING SUM(CASE WHEN payload_json->>'passed'='true' THEN 1 ELSE 0 END) = 0
   AND COUNT(*) > 5;

-- Average time per pipeline stage (P50)
SELECT 'validator→algo' AS stage,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(epoch FROM e2.created_at - e1.created_at)/60) AS p50_mins
FROM   openclaw_researcher.events e1
JOIN   openclaw_researcher.events e2 ON e1.strategy_id = e2.strategy_id
WHERE  e1.event_type = 'dataset.ready' AND e2.event_type = 'backtest.completed'
  AND  e1.created_at > NOW() - INTERVAL '7 days';
```

For each finding (write to `.learnings/PERFORMANCE_REVIEW.md` with date):
- Strategy types never passing → propose adding to `dead_ends` in `MEMORY.md` (after 3 cycles).
- Gate rejecting > 80% of strategies → propose threshold adjustment to operator.
- Pipeline stage with P50 > 2× heartbeat → bottleneck investigation.
- Throughput trending down → flag with proximate cause.

### Mode 3: Skill evolution

```bash
ls -la skills/
```

For each skill file, check:
1. Last `git log` mtime — > 30 days untouched and likely stale?
2. New strategy_types appearing in `strategy_workflow` not present in `strategy_registry.md`?
3. `.learnings/` entries citing this skill but proposing changes?

If gaps found → write proposed updates to `.learnings/SKILL_DRAFTS/<skill_name>.md`. Operator reviews and merges.

### Mode 4: Design validation

Run the contract-drift audit:

```sql
-- Events emitted but never routed
SELECT DISTINCT e.event_type, COUNT(*)
FROM   openclaw_researcher.events e
LEFT JOIN openclaw_researcher.routing_rules rr
       ON e.event_type = rr.event_type AND e.domain = rr.domain
WHERE  rr.event_type IS NULL
  AND  e.created_at > NOW() - INTERVAL '7 days'
GROUP  BY 1;
```

For each `agents/<id>/AGENTS.md`:
1. Parse the `contract` block (SUBSCRIBES, EMITS).
2. Compare against `routing_rules.target_agent='<id>'` (DB) and the .py file's actual handler logic.
3. Disagreement → log to `.learnings/ARCHITECTURE_DRIFT.md` with the three-way diff.

Plus learning-loop health:
- File sizes of `.learnings/*.md` — growing? plateaued?
- Anything promoted from `.learnings/` to `MEMORY.md` in the last 7 days?
- `risk_config` thresholds adjusted recently?

Plus idea diversity:
```sql
SELECT source_agent, COUNT(*)
FROM   openclaw_researcher.events
WHERE  event_type = 'experiment.started'
  AND  created_at > NOW() - INTERVAL '7 days'
GROUP  BY 1;
```

If > 80% from one source → log diversity warning.

### Step 2: Architecture health verdict

After the mode-specific work, write a one-line health assessment:

```
{green|yellow|red}: {one-sentence summary}
```

- **green** — all loops closing, diverse ideas, healthy pass rate, no stuck workflows.
- **yellow** — one or more loops stale (e.g. researcher hasn't generated in 24h), concentration risk, gate rejecting > 80%.
- **red** — pipeline stuck, no experiments flowing for 6h+, learnings file not changing.

Append to `MEMORY.md` under "Architecture health log".

### Step 3: Promotion check

For each `.learnings/*.md` entry, count occurrences of the same observation:

```bash
grep -c "Pattern-ID: <id>" .learnings/PERFORMANCE_REVIEW.md
```

If a specific finding has appeared in 3 consecutive cycles → append to `MEMORY.md` under the appropriate section. Mark the source line `[promoted YYYY-MM-DD]` so we don't re-promote.

### Step 4: Cycle marker

```sql
INSERT INTO openclaw_researcher.workflow_events (event_type, agent, data)
VALUES ('architect_cycle_complete', 'qr_architect',
        jsonb_build_object('mode', :mode,
                           'health', :health,
                           'findings_logged', :n_findings,
                           'promotions', :n_promotions));
```

Log: `ARCHITECT {mode}: health={health}, findings={N}, promotions={M}`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| Web search fails (mode=research) | Log warning, write cycle marker (we don't retry inside the cycle — wait for the next 4h slot). |
| Performance audit SQL returns 0 rows everywhere | Pipeline is dead. Set health='red'. Operator will see in next qr_idea_intake notification cycle. |
| Drift detected between AGENTS.md contract and .py SUBSCRIBES | Log to `.learnings/ARCHITECTURE_DRIFT.md` with all three sources side-by-side. NEVER auto-fix. |
| Same drift logged 3 cycles in a row | Promote to `MEMORY.md` with a recommended fix (still operator-applied — never auto-merged). |

## Success metrics

- 6 cycles per day (one per 4h slot, all 4 modes covered every 16h).
- ≥ 1 promotion to MEMORY.md per week (system is learning, not just observing).
- Architecture health 'green' ≥ 90% of cycles in steady state.
- Mode coverage uniform: each mode runs ≥ 1.5 cycles per day on average.

## Skills consulted

- All of `skills/` (this agent's job is to keep them current).
- `skills/observability.md` for log line conventions.
