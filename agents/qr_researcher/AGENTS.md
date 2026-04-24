# AGENTS.md — research_agent

## Boot Sequence
1. Read MEMORY.md for research landscape and promising directions
2. Read memory/ for today + yesterday logs
3. Read .learnings/LEARNINGS.md for patterns to avoid
4. Read skills/strategy_registry.md for known strategy types

## On HEARTBEAT OR Direct Chat Mandate

If woken by a direct chat mandate, follow the user's instructions explicitly.
If woken autonomously, determine research mode based on the UTC hour:
- 00:00, 12:00 UTC → Mode 1: News-Driven
- 06:00, 18:00 UTC → Mode 2: Data-Driven
- 03:00, 15:00 UTC → Mode 3: Cross-Asset
- 09:00, 21:00 UTC → Mode 4: Failure-Driven

Generate 1-2 testable hypotheses per cycle.

### Output: For each hypothesis

1. Format as an idea spec (MUST exactly match this schema for the algo agent):
```json
{
  "experiment_id": "<generate uuid>",
  "source": "research_agent",
  "generation": 1,
  "strategy_id": "gen-<uuid-first-8-chars>",
  "param_set": {
    "strategy_type": "<e.g., momentum, mean_reversion, stat_arb>",
    "asset_universe": ["<TICKER1>", "<TICKER2>"],
    "date_range": {
      "start": "2022-01-01",
      "end": "2024-12-31"
    },
    "lookback_window": <integer>,
    "entry_threshold": <float>,
    "exit_threshold": <float>,
    "description": "<one-line hypothesis>"
  }
}
```

2. Check duplicate:
```sql
SELECT 1 FROM openclaw_researcher.events
WHERE event_type = 'experiment.started' AND domain = 'quant'
  AND created_at > NOW() - INTERVAL '30 days'
  AND payload_json->'param_set'->>'strategy_type' = '{type}';
```

3. Insert strategy_workflow:
```sql
INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, assigned_by)
VALUES ('{strategy_id}', '{type}', 'pending', '{exp_id}', 'research_agent');
```

4. Insert event:
```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('experiment.started', '{strategy_id}', '{payload}', 'research_agent', 'quant');
```

5. Log to memory/YYYY-MM-DD.md: what was generated and why.