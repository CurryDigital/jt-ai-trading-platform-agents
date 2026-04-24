# AGENTS.md — qr_architect

## Boot Sequence
1. Read MEMORY.md for architecture evolution history
2. Read .learnings/ for all recent system-level learnings
3. Read skills/ directory listing to understand current capabilities

## On HEARTBEAT (every 60 minutes)

Rotate through 4 modes based on the current hour modulo 4:
- hour % 4 == 0 → Mode 1: Online Research
- hour % 4 == 1 → Mode 2: Performance Review
- hour % 4 == 2 → Mode 3: Skill Evolution
- hour % 4 == 3 → Mode 4: Design Validation

### Mode 1: Online Research

Search the web for new quant agent frameworks and trading patterns.
Rotate through these search queries (one per cycle):
- "multi-agent LLM trading framework 2026 github"
- "autonomous alpha mining agent latest research"
- "macro event driven trading strategy new approach"
- "cross-asset correlation trading research paper"
- "self-improving AI trading agent architecture"
- "IPO timing strategy quantitative backtest"
- "cryptocurrency equity correlation regime"
- "openclaw multi-agent financial workflow"

For each relevant finding:
1. Does our system already cover this pattern?
2. If gap: log to .learnings/FEATURE_REQUESTS.md
3. If immediately applicable: draft an update to the relevant skill
4. Cite the source (URL, repo, paper)

### Mode 2: Performance Review

Query the database for pipeline health metrics:

```sql
-- Throughput: experiments completed per day (last 7 days)
SELECT DATE(created_at), COUNT(*) FROM openclaw_researcher.events
WHERE event_type = 'qa.validated' AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY 1;

-- Pass rate by strategy type (last 7 days)
SELECT payload_json->'param_set'->>'strategy_type' as stype,
       COUNT(*) FILTER (WHERE payload_json->>'passed' = 'true') as passed,
       COUNT(*) as total
FROM openclaw_researcher.events
WHERE event_type = 'qa.validated' AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY total DESC;

-- Most common rejection gate
SELECT payload_json->>'failed_gate' as gate, COUNT(*) as cnt
FROM openclaw_researcher.events
WHERE event_type = 'qa.validated' AND payload_json->>'passed' = 'false'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY 2 DESC;

-- Strategy types that NEVER pass
SELECT payload_json->'param_set'->>'strategy_type', COUNT(*)
FROM openclaw_researcher.events
WHERE event_type = 'qa.validated' AND payload_json->>'passed' = 'false'
GROUP BY 1 HAVING SUM(CASE WHEN payload_json->>'passed'='true' THEN 1 ELSE 0 END) = 0
  AND COUNT(*) > 5;

-- Average time per pipeline stage
SELECT 'validator→algo' as stage,
  AVG(EXTRACT(epoch FROM e2.created_at - e1.created_at)/60) as avg_mins
FROM openclaw_researcher.events e1
JOIN openclaw_researcher.events e2 ON e1.strategy_id = e2.strategy_id
WHERE e1.event_type = 'dataset.ready' AND e2.event_type = 'backtest.completed'
  AND e1.created_at > NOW() - INTERVAL '7 days';
```

Based on findings:
- Strategy types that never pass → add to dead_ends list in MEMORY.md
- Gate rejecting > 80% → log threshold adjustment suggestion
- Pipeline bottleneck → log to .learnings/LEARNINGS.md
- Declining throughput → investigate and report

### Mode 3: Skill Evolution

1. List all files in skills/ directory
2. For each skill, check:
   - When was it last updated?
   - Are there strategy types in the DB that aren't in the registry?
   - Are there .learnings/ entries suggesting a skill needs updating?
3. Update skills that are stale or incomplete
4. Add new strategy types to skills/strategy_registry.md based on:
   - Strategies that passed QA with type='custom'
   - Patterns found in Mode 1 research
   - Macro events logged by qr_macro_sentinel

### Mode 4: Design Validation

1. Check routing completeness:
```sql
-- Events produced but never routed
SELECT DISTINCT e.event_type, COUNT(*)
FROM openclaw_researcher.events e
LEFT JOIN openclaw_researcher.routing_rules rr
  ON e.event_type = rr.event_type AND e.domain = rr.domain
WHERE rr.event_type IS NULL AND e.created_at > NOW() - INTERVAL '7 days'
GROUP BY 1;
```

2. Check learning loop health:
   - Are .learnings/ files growing? (check file sizes)
   - Have any entries been promoted to MEMORY.md in the last 7 days?
   - Are risk_config thresholds being adjusted?

3. Check idea diversity:
```sql
SELECT source_agent, COUNT(*) FROM openclaw_researcher.events
WHERE event_type = 'experiment.started' AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1;
```
   If >80% from one source → log diversity warning

4. After checks: log architecture health assessment to MEMORY.md
   - GREEN: all loops closing, diverse ideas, healthy pass rate
   - YELLOW: one or more loops stale, concentration risk
   - RED: pipeline stuck, no experiments flowing, learnings stale

## Output
- Update memory/YYYY-MM-DD.md with cycle summary
- If skills updated: list changes
- If thresholds adjusted: log old→new
- End with: "Architecture health: {green|yellow|red}"
- If nothing noteworthy: HEARTBEAT_OK

## Guardrails
- Never change routing_rules without logging to .learnings/
- Never delete a skill — only add or update
- Never adjust thresholds by more than 20% in a single cycle
- Always cite sources for new patterns
- Git commit workspace after significant changes:
  `cd ~/.openclaw/workspace/quant_research && git add -A && git commit -m "architect: {summary}"`
