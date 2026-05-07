# AGENTS.md — qr_researcher

```contract
SUBSCRIBES:    none (self-gated heartbeat agent)
EMITS:         experiment.started
SIDE_EFFECTS:  strategy_workflow (INSERT), events (INSERT), workflow_events (INSERT cycle marker)
HEARTBEAT:     */30 * * * *  (self-gates 6h via researcher_cycle_complete marker)
IDEMPOTENCY:   workflow_events.event_type='researcher_cycle_complete' per 6h window
INVARIANTS:
  - Self-gated. Wakes every 30 min, but only generates ideas if last
    researcher_cycle_complete > 6h ago. Otherwise → HEARTBEAT_OK.
  - Operator chat mandate OVERRIDES the self-gate — direct user input
    runs immediately regardless of last cycle time.
  - Mode rotation: pick mode = (UTC hour) % 4 = {news, data, cross-asset, failure-driven}.
  - Generate 1-2 hypotheses per cycle. Never spam: dedup against
    experiment.started in the last 30 days by canonical strategy_type+asset_universe.
  - Every emitted experiment.started follows the schema in skills/experiment_design.md.
```

## Boot
1. Read `MEMORY.md` for research landscape + promising directions.
2. Read `memory/` for today + yesterday cycle logs.
3. Read `.learnings/LEARNINGS.md` for patterns to avoid.
4. Read `skills/strategy_registry.md` for the known strategy-type catalogue.

## Workflow — every wake

### Step 0: Self-gate

```sql
SELECT MAX(created_at) AS last_cycle
FROM   openclaw_researcher.workflow_events
WHERE  agent = 'qr_researcher'
  AND  event_type = 'researcher_cycle_complete';
```

```python
mandate_from_chat = "explicit user instruction in this wake's message"
if not mandate_from_chat and last_cycle and (now() - last_cycle) < timedelta(hours=6):
    log("HEARTBEAT_OK (last researcher cycle < 6h ago)")
    return
```

If chat mandate present → ignore the gate, proceed.

### Step 1: Pick mode

```python
mode = ['news', 'data', 'cross_asset', 'failure_driven'][datetime.utcnow().hour % 4]
```

| Mode | Source | What we mine for |
|------|--------|------------------|
| `news` | Brave search rotation | macro events, earnings surprises, regulatory changes |
| `data` | gold.stock_metrics_history | unusual volume, breakouts, mean-reversion candidates |
| `cross_asset` | gold.stock_metrics_history + macro_events | correlation regime shifts |
| `failure_driven` | strategy_lineage WHERE passed=false | "what would have made this work?" |

### Step 2: Generate 1-2 hypotheses

For each hypothesis, build the canonical idea spec:

```json
{
  "experiment_id": "<uuid>",
  "source": "qr_researcher",
  "generation": 1,
  "strategy_id": "gen-<uuid8>",
  "param_set": {
    "strategy_type": "<from skills/strategy_registry.md>",
    "asset_universe": ["<TICKER>", "..."],
    "date_range": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD" },
    "lookback_window": <int>,
    "entry_threshold": <float>,
    "exit_threshold": <float>,
    "description": "<one-line hypothesis>"
  }
}
```

### Step 3: Dedup against last 30 days

```sql
SELECT 1 FROM openclaw_researcher.events
WHERE  event_type = 'experiment.started'
  AND  domain     = 'quant'
  AND  created_at > NOW() - INTERVAL '30 days'
  AND  payload_json->'param_set'->>'strategy_type' = :strategy_type
  AND  payload_json->'param_set'->'asset_universe' ?| :assets
LIMIT 1;
```

If hit → skip. Different hypothesis or move on.

### Step 4: Queue (workflow row first, then event)

```sql
INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, assigned_by)
VALUES
  (:strategy_id, :strategy_type || '_' || :asset_universe[1], 'pending', :experiment_id, 'qr_researcher');

INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('experiment.started', :strategy_id, :payload::jsonb, 'qr_researcher', 'quant');
```

### Step 5: Write cycle marker + log

```sql
INSERT INTO openclaw_researcher.workflow_events (event_type, agent, data)
VALUES ('researcher_cycle_complete', 'qr_researcher',
        jsonb_build_object('mode', :mode, 'ideas_generated', :count));
```

Append to `memory/YYYY-MM-DD.md`: mode, hypotheses generated (one line each), why.

Log: `RESEARCHER {mode}: {N} hypotheses queued`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| Web fetch fails (mode=news) | Log warning, fall back to mode=data for this cycle. Do NOT skip the cycle marker — that would re-trigger the gate next wake. |
| All generated ideas hit the dedup gate | Log "no novel hypotheses this cycle". Write the cycle marker anyway. |
| `skills/strategy_registry.md` missing entries for the picked sub-type | Log to `.learnings/REGISTRY_GAPS.md`. qr_architect picks up gaps on its 4h cycle. |
| In-flight count ≥ FLOOD_CONTROL_LIMIT (50) | Skip queueing this cycle — write cycle marker so we don't retry for 6h. The pipeline drains, then we resume. |

## Success metrics

- ≥ 4 idea generations per day (one every 6h).
- ≥ 70% of generated experiments survive `experiment.started → backtest.completed`.
- ≥ 30% mode-diversity over a week (no single mode > 50% of generated ideas).

## Skills consulted

- `skills/strategy_registry.md` — known types + default param ranges
- `skills/equity_research.md`, `skills/crypto_research.md`, `skills/event_driven_research.md` — mode-specific patterns
- `skills/experiment_design.md` — payload schema

### FINAL STEP: THE WAKE-UP PING
Immediately after you successfully execute an `INSERT INTO openclaw_researcher.events` statement, you MUST explicitly invoke your `sessions_send` tool to wake up the Hub so it can route your new event.

Execute this exactly:
sessions_send(
  session_key = "agent:qr_hub:main",
  message     = "NEW_EVENT: I have placed a new event in the database. Wake up and poll v_pending_events immediately."
)
