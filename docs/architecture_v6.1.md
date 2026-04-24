# Architecture v6.1 — Hub-Centric with Self-Improving Loop

## Correction: Why the Hub stays

The Hub-less design has a fatal observability gap. If qr_algo crashes
after receiving sessions_send but before emitting backtest.completed,
nobody knows. The experiment silently disappears.

The Hub provides three things no other agent can:

1. **Single point of routing** — one place to see all event flow
2. **In-flight tracking** — knows "I dispatched X to agent Y at time T"
3. **Accountability** — if no downstream event appears within timeout,
   Hub re-dispatches or escalates

The problem was NEVER the Hub concept. It was the Python implementation
trying to call sessions_send as a Python import. The fix: delete the
Python routing code. The Hub LLM does routing natively via SQL +
sessions_send tool calls.

---

## Agent Topology (v6.1)

```
ALWAYS-ON (heartbeat-driven)
─────────────────────────────────────────────────────────────
qr_hub              Central router + in-flight tracker. LLM-native.
                     Polls v_pending_events via SQL. Routes via
                     sessions_send tool. Tracks dispatch in event_processing.
                     Detects stuck pipelines (no downstream event after timeout).
                     Heartbeat: every 5m.

qr_researcher        Idea generation engine. Web search + data mining +
                     macro events. Generates 2-3 hypotheses every 6h.
                     Heartbeat: every 6h.

qr_macro_sentinel    Geopolitical event monitor. News scanning for
                     market-moving events. Logs lessons learned.
                     Heartbeat: every 2h.

qr_architect         NEW. Self-improving architecture agent. Every hour,
                     researches online for new quant frameworks, validates
                     current design against best practices, proposes
                     improvements. Rewrites skills/, updates strategy
                     registry, evolves the system continuously.
                     Heartbeat: every 60m.

qr_monitor           Watchdog. Scans for stuck workflows, orphaned events.
                     Weekly: memory maintenance, threshold review, git commit.
                     Heartbeat: every 30m (light context).

qr_idea_intake       Telegram listener. Parses human trading ideas.
                     No heartbeat — event-reactive only.

qr_etl_manager       Data supply chain. Daily refresh at 02:00 UTC.
                     Heartbeat: daily.

EVENT-REACTIVE (woken by Hub via sessions_send)
─────────────────────────────────────────────────────────────
qr_data_validator    Validates data quality. Woken by Hub on experiment.started.
qr_algo              Writes + runs bespoke backtest. Woken by Hub on dataset.ready.
qr_risk              Risk evaluation. Woken by Hub on backtest.completed.
qr_debate            Bull/Bear adversarial. Woken by Hub on risk.evaluated.
qr_qa                5-gate + conviction. Woken by Hub on debate.completed.
qr_exp_manager       Variant generation. Woken by Hub on qa.validated.
                     Also: nightly autonomous cycle (daily heartbeat).
```

---

## Hub Design (LLM-native, no Python)

### What the Hub does on every heartbeat (every 5 min)

```
1. Query: SELECT * FROM v_pending_events LIMIT 50
2. For each event:
   a. Look up routing: SELECT target_agent FROM routing_rules
      WHERE event_type = X AND domain = Y AND enabled = true
   b. For each target_agent:
      - sessions_send(sessionKey="agent:{target}:main", message="...")
      - INSERT INTO event_processing (event_id, agent_name='qr_hub')
   c. Log: "ROUTED {event_type} → {target_agent}"
3. Check for stuck dispatches:
   SELECT * FROM event_processing ep
   JOIN events e ON ep.event_id = e.id
   WHERE ep.agent_name = 'qr_hub'
     AND ep.processed_at < NOW() - INTERVAL '15 minutes'
     AND NOT EXISTS (next downstream event for this strategy_id)
   → If found: re-dispatch or escalate to qr_monitor
4. If nothing pending and nothing stuck: reply HEARTBEAT_OK
```

### What the Hub does NOT do

- Run any Python script
- Modify any event payload
- Make decisions about strategy quality
- Emit domain events (only routes them)
- Inspect payload content for routing decisions

### Hub HEARTBEAT.md (actual file)

```markdown
# HEARTBEAT.md — qr_hub

## On every heartbeat (every 5 minutes)

### Step 1: Route pending events

Run this SQL to find unrouted events:

  SELECT event_id, event_type, strategy_id, domain, source_agent
  FROM openclaw_researcher.v_pending_events
  ORDER BY created_at ASC LIMIT 50;

If no rows → skip to Step 2.

For each row, look up the target:

  SELECT target_agent FROM openclaw_researcher.routing_rules
  WHERE event_type = '{event_type}' AND domain = '{domain}' AND enabled = true;

For each target_agent:
  1. Use sessions_send tool:
     sessionKey = "agent:{target_agent}:main"
     message = "Pending {event_type} event for strategy {strategy_id}.
                Query openclaw_researcher.events for details and process it.
                When done, emit your output event to the events table."
     timeoutSeconds = 0
  2. After sessions_send succeeds, mark as routed:
     INSERT INTO openclaw_researcher.event_processing
       (event_id, agent_name) VALUES ('{event_id}', 'qr_hub')
     ON CONFLICT DO NOTHING;
  3. Log: "ROUTED {event_type} → {target_agent} (strategy: {strategy_id})"
  4. Reply REPLY_SKIP to prevent ping-pong conversation.

### Step 2: Check for stuck dispatches

Run this SQL to find events Hub routed but no downstream event appeared:

  SELECT ep.event_id, e.event_type, e.strategy_id,
         EXTRACT(epoch FROM now() - ep.processed_at)/60 AS minutes_since_dispatch
  FROM openclaw_researcher.event_processing ep
  JOIN openclaw_researcher.events e ON ep.event_id = e.id
  WHERE ep.agent_name = 'qr_hub'
    AND ep.processed_at > NOW() - INTERVAL '2 hours'
    AND ep.processed_at < NOW() - INTERVAL '15 minutes'
    AND e.domain = 'quant'
    AND e.event_type IN ('experiment.started','dataset.ready',
        'backtest.completed','risk.evaluated','debate.completed')
  ORDER BY ep.processed_at ASC;

For each, check if downstream event exists:

  SELECT 1 FROM openclaw_researcher.events
  WHERE strategy_id = '{strategy_id}'
    AND created_at > '{dispatch_time}'
    AND event_type = '{expected_next_event}';

Expected next events:
  experiment.started → dataset.ready
  dataset.ready → backtest.completed
  backtest.completed → risk.evaluated
  risk.evaluated → debate.completed
  debate.completed → qa.validated

If downstream missing AND minutes > threshold:
  - Re-dispatch once via sessions_send to the target agent
  - Log: "RE-DISPATCH {event_type} to {target_agent} after {minutes}m"
  - If already re-dispatched once: emit workflow.stuck event

### Step 3: Summary

If events routed > 0: log the count.
If stuck detected > 0: log the count.
If nothing happened: reply HEARTBEAT_OK.

Do NOT run any Python scripts.
Do NOT modify any event payloads.
Route by (domain, event_type) only.
```

---

## Event Flow (with Hub)

```
qr_idea_intake / qr_researcher / qr_macro_sentinel
  ↓ INSERT experiment.started into events table
  
qr_hub (heartbeat picks it up within 5 minutes)
  ↓ sessions_send → qr_data_validator
  ↓ marks event_processing
  
qr_data_validator (validates data, emits dataset.ready)
  ↓ INSERT dataset.ready into events table
  
qr_hub (next heartbeat picks it up)
  ↓ sessions_send → qr_algo
  
qr_algo (writes + runs backtest, emits backtest.completed)
  ↓ INSERT backtest.completed into events table
  
qr_hub → sessions_send → qr_risk → risk.evaluated
qr_hub → sessions_send → qr_debate → debate.completed  
qr_hub → sessions_send → qr_qa → qa.validated
qr_hub → sessions_send → qr_exp_manager (generates variants)
qr_hub → sessions_send → qr_idea_intake (notifies operator)

Total pipeline time: ~30 minutes (6 hops × 5 min heartbeat)
```

---

## Self-Improving Architecture Agent (qr_architect)

This is the meta-agent that continuously evolves the entire system.

### Purpose

Every hour, the architect:
1. Researches online for new quant agent frameworks and patterns
2. Reviews the system's performance (pass rates, failures, stuck pipelines)
3. Validates the current design against what it finds
4. Proposes and implements improvements to skills, thresholds, and agents

### AGENTS.md — qr_architect

```markdown
## Boot Sequence
1. Read MEMORY.md for architecture evolution history
2. Read .learnings/ for all recent system-level learnings
3. Read skills/ directory to understand current capabilities
4. Read docs/architecture_v6.md for current design spec

## On HEARTBEAT (every 60 minutes)

Rotate through these improvement modes:

### Mode 1: Online Research (every 4th heartbeat)
Use web search to find:
- New quant trading agent frameworks on GitHub
- Recent papers on arxiv about LLM + finance
- New strategies or alpha factors being discussed
- OpenClaw community patterns and best practices

For each relevant finding:
- Assess: does our system already handle this?
- If gap found: log to .learnings/FEATURE_REQUESTS.md
- If immediately actionable: update the relevant skill file

Search queries to rotate through:
- "multi-agent LLM trading framework 2026"
- "autonomous alpha mining latest papers"
- "macro event driven trading strategies"
- "cross-asset correlation trading new research"
- "openclaw multi-agent orchestration patterns"
- "quantitative finance self-improving agent"
- "IPO trading strategy backtesting"
- "crypto equity correlation regime detection"
- "geopolitical event market impact quantitative"

### Mode 2: Performance Review (every 2nd heartbeat)
Query the database for system health:

```sql
-- Pipeline throughput last 24h
SELECT event_type, COUNT(*) as count, 
       AVG(EXTRACT(epoch FROM e2.created_at - e1.created_at)/60) as avg_minutes
FROM openclaw_researcher.events e1
JOIN openclaw_researcher.events e2 
  ON e1.strategy_id = e2.strategy_id 
  AND e2.created_at > e1.created_at
WHERE e1.created_at > NOW() - INTERVAL '24 hours'
GROUP BY event_type;

-- QA pass rate by strategy type
SELECT payload_json->>'strategy_type' as stype,
       COUNT(*) FILTER (WHERE payload_json->>'passed' = 'true') as passed,
       COUNT(*) as total
FROM openclaw_researcher.events
WHERE event_type = 'qa.validated'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1;

-- Most common rejection gates
SELECT payload_json->>'failed_gate' as gate,
       COUNT(*) as rejections
FROM openclaw_researcher.events
WHERE event_type = 'qa.validated'
  AND payload_json->>'passed' = 'false'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY 2 DESC;

-- Strategy types that never pass
SELECT payload_json->>'strategy_type' as stype, COUNT(*)
FROM openclaw_researcher.events
WHERE event_type = 'qa.validated'
  AND payload_json->>'passed' = 'false'
GROUP BY 1
HAVING COUNT(*) > 10
   AND SUM(CASE WHEN payload_json->>'passed' = 'true' THEN 1 ELSE 0 END) = 0;
```

Based on findings:
- If a strategy type NEVER passes: add to dead_ends in MEMORY.md
- If a gate rejects > 80%: suggest threshold adjustment
- If pipeline throughput is declining: investigate bottleneck
- Log observations to .learnings/LEARNINGS.md

### Mode 3: Skill Evolution (every 3rd heartbeat)
Review and improve existing skills:

1. Read each skill in skills/ directory
2. Compare against latest online research findings
3. If skill is outdated or missing coverage:
   - Update the skill file with new patterns
   - Add new strategy types to strategy_registry.md
   - Log changes to .learnings/LEARNINGS.md

Specific improvements to look for:
- New asset classes not covered (options, futures, etc.)
- New frequencies not supported (intraday when data becomes available)
- New macro themes emerging (AI bubble, de-dollarisation, etc.)
- New cross-asset correlations discovered in research
- Better backtest methodologies from recent papers

4. After updating any skill file:
   - Log: "Updated skills/{name}.md: {what changed}"
   - Write to MEMORY.md: "Architecture evolution {date}: {change}"

### Mode 4: Design Validation (every 4th heartbeat)
Revalidate the overall architecture:

1. Check: is every event type in routing_rules being produced?
   ```sql
   SELECT DISTINCT rr.event_type, rr.target_agent,
          (SELECT COUNT(*) FROM openclaw_researcher.events e 
           WHERE e.event_type = rr.event_type 
             AND e.created_at > NOW() - INTERVAL '7 days') as recent_count
   FROM openclaw_researcher.routing_rules rr
   WHERE rr.enabled = true
   ORDER BY recent_count ASC;
   ```
   If recent_count = 0 for any route: investigate why

2. Check: are any events being produced that have no route?
   ```sql
   SELECT DISTINCT e.event_type, COUNT(*) 
   FROM openclaw_researcher.events e
   LEFT JOIN openclaw_researcher.routing_rules rr 
     ON e.event_type = rr.event_type AND e.domain = rr.domain
   WHERE rr.event_type IS NULL
     AND e.created_at > NOW() - INTERVAL '7 days'
   GROUP BY 1;
   ```
   If found: either add a route or log as "intentionally unrouted"

3. Check: is the learning loop closing?
   - Are .learnings/ entries being created regularly?
   - Are patterns being promoted to MEMORY.md?
   - Are risk_config thresholds being adjusted?
   If any of these are stale (>7 days): log a warning

4. Check: is idea diversity sufficient?
   ```sql
   SELECT payload_json->'param_set'->>'strategy_type' as stype,
          COUNT(*) as experiments_7d
   FROM openclaw_researcher.events
   WHERE event_type = 'experiment.started'
     AND created_at > NOW() - INTERVAL '7 days'
   GROUP BY 1 ORDER BY 2 DESC;
   ```
   If >70% of experiments are one strategy type: 
   log "Diversity warning — system converging on {type}"
   Update qr_researcher MEMORY.md to explore other types

## Output
After each cycle:
- Update memory/YYYY-MM-DD.md with session summary
- If any skills were updated: list what changed
- If any thresholds were adjusted: list old→new
- If any architectural improvements proposed: describe them
- Always end with: "Architecture health: {green|yellow|red}"
```

### SOUL.md — qr_architect

```markdown
You are the Architect — the meta-intelligence that evolves the
entire quant research system.

You are not a trader. You are not a researcher. You are the
system designer who ensures the research pipeline is optimal,
comprehensive, and continuously improving.

Your values:
- Diversity over convergence: the system should explore broadly
- Evidence over opinion: only change things backed by data
- Incrementalism over revolution: small frequent improvements
- Reversibility: every change should be rollback-able via git

You are cautious about:
- Adding complexity without clear benefit
- Following trends without validation
- Removing capabilities that might be needed later
- Making changes during high-activity periods

You always:
- Log every change to .learnings/ with rationale
- Test changes against historical pipeline performance
- Cite sources (GitHub repos, papers, articles) for ideas
- Git commit workspace after significant updates
```

### HEARTBEAT.md — qr_architect

```markdown
# HEARTBEAT.md — qr_architect

## Every heartbeat (60 minutes)

Determine which mode to run based on the hour:
- Hours 0,4,8,12,16,20 → Mode 1: Online Research
- Hours 1,5,9,13,17,21 → Mode 2: Performance Review
- Hours 2,6,10,14,18,22 → Mode 3: Skill Evolution
- Hours 3,7,11,15,19,23 → Mode 4: Design Validation

Follow the procedures in AGENTS.md for the selected mode.
Keep it under 5 minutes. Log findings. Move on.

If nothing noteworthy: reply HEARTBEAT_OK.
If changes made: summarise in one line.
```

---

## Pipeline Agents — What they emit to DB

Every pipeline agent follows this pattern in AGENTS.md:

```markdown
## When woken by Hub (sessions_send with pending event notification)

1. Query DB for my pending events:
   SELECT * FROM openclaw_researcher.v_{my_agent}_work LIMIT 1;
   (or query events table directly)

2. Check idempotency:
   SELECT 1 FROM openclaw_researcher.event_processing
   WHERE event_id = '{id}' AND agent_name = '{my_name}';
   If exists → reply "Already processed, skipping." and exit.

3. Do my work (validate / backtest / evaluate / etc.)

4. Write results to strategy_workflow (UPDATE)

5. Emit output event:
   INSERT INTO openclaw_researcher.events
     (event_type, strategy_id, payload_json, source_agent, domain)
   VALUES ('{my_output_type}', '{strategy_id}', '{payload}', '{my_name}', 'quant');

6. Mark input event as processed:
   INSERT INTO openclaw_researcher.event_processing
     (event_id, agent_name) VALUES ('{input_event_id}', '{my_name}')
   ON CONFLICT DO NOTHING;

7. Log any learnings to .learnings/ if applicable.

8. Hub will pick up the new output event on its next heartbeat
   and route it to the next agent. I do NOT call sessions_send myself.
```

This keeps the pipeline tightly controlled — only the Hub dispatches.

---

## Routing Table (routing_rules)

```sql
-- Full routing table for v6.1
INSERT INTO openclaw_researcher.routing_rules 
  (event_type, domain, target_agent, enabled) VALUES
  -- Pipeline chain
  ('experiment.started',   'quant', 'qr_data_validator', true),
  ('dataset.ready',        'quant', 'qr_algo',           true),
  ('backtest.completed',   'quant', 'qr_risk',           true),
  ('risk.evaluated',       'quant', 'qr_debate',         true),
  ('debate.completed',     'quant', 'qr_qa',             true),
  ('qa.validated',         'quant', 'qr_exp_manager',    true),
  ('qa.validated',         'quant', 'qr_idea_intake',    true),
  -- Infrastructure
  ('workflow.stuck',       'quant', 'qr_monitor',        true),
  ('workflow.stuck',       'quant', 'qr_idea_intake',    true),
  ('etl.completed',        'quant', 'qr_monitor',        true),
  ('etl.partial',          'quant', 'qr_monitor',        true),
  ('etl.partial',          'quant', 'qr_idea_intake',    true),
  ('etl.failed',           'quant', 'qr_monitor',        true),
  ('etl.failed',           'quant', 'qr_idea_intake',    true),
  ('etl.operator_alert',   'quant', 'qr_idea_intake',    true),
  ('etl.refresh_requested','quant', 'qr_etl_manager',    true)
ON CONFLICT (event_type, domain, target_agent) DO UPDATE
  SET enabled = EXCLUDED.enabled, updated_at = NOW();
```

---

## Monitoring: Who decides if work is done?

### The Hub tracks all dispatches

```
Hub dispatches experiment.started → qr_data_validator at 10:00
Hub expects dataset.ready within 15 minutes
  10:05 heartbeat: no dataset.ready yet — normal, within threshold
  10:10 heartbeat: no dataset.ready yet — normal
  10:15 heartbeat: no dataset.ready after 15 minutes!
    → Re-dispatch once: sessions_send to qr_data_validator again
    → Log: "RE-DISPATCH experiment.started to qr_data_validator"
  10:20 heartbeat: still no dataset.ready after 20 minutes
    → Emit workflow.stuck event
    → Hub routes workflow.stuck to qr_monitor + qr_idea_intake
    → Monitor investigates, Idea Intake alerts operator
```

### The Monitor provides secondary oversight

The Monitor runs independently every 30 minutes and catches things
the Hub might miss:
- Events the Hub dispatched but forgot to track
- Gold layer state issues
- Orphaned experiments with no events for > 2 hours
- Memory/disk/connection health

### Accountability chain

```
Who created the experiment?  → events table (source_agent)
Who routed it?               → event_processing (agent_name='qr_hub')
Who processed it?            → event_processing (agent_name=target)
What was the result?         → strategy_workflow + next event
How long did each step take? → event timestamps in events table
Why did it fail?             → workflow_events audit log
What did we learn?           → .learnings/ and MEMORY.md
```

---

## Implementation Order

### Phase 1: Hub LLM-native (Day 1, 2 hours)
Files to create/update:
- agents/qr_hub/AGENTS.md (routing procedures, NO Python)
- agents/qr_hub/HEARTBEAT.md (5-min poll + stuck detection)
- agents/qr_hub/SOUL.md (silent router personality)
- agents/qr_hub/TOOLS.md (DB schema reference)
- DELETE: hub_agent.py, hub/router.py, hub/sdk.py, hub/service.py
  (keep as docs/legacy/ for reference)

### Phase 2: Pipeline agents (Day 1, 3 hours)
For each pipeline agent (data_validator, algo, risk, qa, exp_manager):
- Rewrite AGENTS.md with LLM-native procedures (SQL + computation)
- Keep Python scripts ONLY for heavy computation (backtest math)
- Remove SDK imports and Python routing code
- Add boot sequence (read MEMORY.md, .learnings/)
- Add sessions_send REPLY_SKIP after being woken
- Delete SESSION.md from all agents

### Phase 3: Self-improvement infra (Day 1, 1 hour)
- Install self-improving-agent from ClawHub
- Create .learnings/ directory with templates
- Add learning triggers to each AGENTS.md
- Git init the workspace

### Phase 4: Researcher + Macro Sentinel (Day 2, 4 hours)
- Create qr_researcher agent (config, workspace files, skills)
- Create qr_macro_sentinel agent (config, workspace files)
- Create domain skills (equity, crypto, macro, events, strategy_registry)
- Install agent-browser for web scraping

### Phase 5: Architect agent (Day 2, 2 hours)
- Create qr_architect agent (config, workspace files)
- Write the 4-mode improvement loop
- Set heartbeat to 60m
- Test each mode individually

### Phase 6: Debate agent (Day 3, 2 hours)
- Create qr_debate agent (config, workspace files)
- Write debate_framework.md skill
- Add conviction_score to strategy_workflow
- Update routing_rules for risk.evaluated → qr_debate → qr_qa

### Phase 7: Real backtests + multi-frequency (Day 3-4, 6 hours)
- Rewrite qr_algo to generate bespoke Python per idea
- Add frequency field to idea spec
- Create frequency-aware risk_config thresholds
- Test diverse strategy types

### Phase 8: Enable 24/7 operation (Day 4+)
- Enable all heartbeats in openclaw.json
- Monitor for 48 hours
- Review .learnings/ and architect output
- Tune and stabilise
```
