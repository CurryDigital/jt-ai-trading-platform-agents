# AGENTS.md — qr_idea_intake

```contract
SUBSCRIBES:    qa.validated, workflow.stuck, etl.partial, etl.failed, etl.operator_alert
EMITS:         experiment.started
SIDE_EFFECTS:  strategy_workflow (INSERT), events (INSERT)
HEARTBEAT:     */30 * * * *
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_idea_intake')
INVARIANTS:
  - The Telegram channel is the only operator-facing surface — no other agent posts.
  - Flood control is never bypassed. Batched submissions are queued one-at-a-time
    and rejected once MAX_INTAKE_IN_PROGRESS in-flight is reached.
  - Every queued idea has a unique strategy_id (uuid4) and a strategy_workflow row
    inserted BEFORE the experiment.started event is emitted.
```

## Boot
1. Read `MEMORY.md` for operator preferences and shorthand vocabulary.
2. Read `skills/idea_parsing.md` for the parse order.
3. Read `agents/shared/constants.py::MAX_INTAKE_IN_PROGRESS` (current: 10).

## Trigger sources

| Trigger | Action |
|---------|--------|
| Telegram inbound | route by message-type (alert / status / idea) |
| Hub wake on `qa.validated` | format result, notify operator, mark processed |
| Hub wake on `workflow.stuck` / `etl.failed` / `etl.partial` | format alert, notify operator |

## Workflow — Telegram inbound

### Classify the message

- Contains an event payload (qa.validated, workflow.stuck, etl.*) → **alert relay**
- Matches `/status`, "what's running", "how many" → **status report**
- Anything else → **trading idea**

### Alert relay format (one line each)

| Event | Format |
|-------|--------|
| qa.validated (passed) | `✓ {sid} promoted. SharpeOOS {sharpe} · DD {dd} · trades {n}.` |
| qa.validated (failed) | `✗ {sid} rejected gate {N}: {reason}.` |
| workflow.stuck        | `⚠ {sid} stuck at {stage} for {min} min ({requeued? "requeued":"escalated"}).` |
| etl.partial / failed  | `⚠ ETL {state}: {sources_failed}` |

### Status report

Single SQL, single line back:

```sql
SELECT
  COUNT(*) FILTER (WHERE status NOT IN ('completed','failed','golden','rejected')) AS in_flight,
  COUNT(*) FILTER (WHERE status='golden' AND completed_at::date = CURRENT_DATE) AS golden_today,
  (SELECT MAX(sharpe_oos) FROM strategy_lineage) AS top_sharpe_alltime
FROM strategy_workflow;
```

Reply: `In-flight {in_flight}/10 · Golden today {golden_today} · Top SharpeOOS all-time {top_sharpe}`.

### Trading idea — parse → flood → dedup → queue

1. **Parse** per `skills/idea_parsing.md` (strategy_type required, asset_universe required, dates default to 3y, numeric params default by type).
2. **Missing fields** — ask ONE question covering up to two missing required fields. Never ask about optionals.
3. **Flood control** (no bypass, ever):

   ```sql
   SELECT COUNT(*) FROM openclaw_researcher.strategy_workflow
   WHERE status NOT IN ('completed','failed','golden','rejected');
   ```

   If `>= MAX_INTAKE_IN_PROGRESS`: reply `Pipeline busy: {N}/{limit} in flight. Try later.` and stop.

4. **Dedup** — canonicalise the param_set to sorted-key JSON, hash, and check:

   ```sql
   SELECT 1 FROM openclaw_researcher.events
   WHERE event_type = 'experiment.started' AND domain = 'quant'
     AND created_at > NOW() - INTERVAL '30 days'
     AND md5(payload_json::text) = md5(:canonical_param_set::text)
   LIMIT 1;
   ```

   If found: reply `Run {N}d ago — change a parameter to make it distinct.` and stop.

5. **Queue** — workflow row first, then event, both in one transaction:

   ```sql
   BEGIN;
   INSERT INTO openclaw_researcher.strategy_workflow
     (strategy_id, name, status, experiment_id, assigned_by)
   VALUES (:sid, :name, 'pending', :exp_id, 'qr_idea_intake');

   INSERT INTO openclaw_researcher.events
     (event_type, strategy_id, payload_json, source_agent, domain)
   VALUES ('experiment.started', :sid, :payload_json, 'qr_idea_intake', 'quant');
   COMMIT;
   ```

   `payload_json` schema:

   ```json
   {
     "experiment_id":   "<uuid>",
     "strategy_id":     "<uuid>",
     "param_set":       { ... canonicalised ... },
     "generation":      1,
     "parent_experiment_id": null,
     "source":          "idea_intake"
   }
   ```

6. **Reply** — one line: `Queued: {type} on [{assets}], {start}→{end}. Lookback {N}d, entry {x}, exit {y}. id={sid}`.

7. The hub picks it up on its next 5-min cycle.

### Batched submissions (numbered list of N strategies)

Process one at a time, each subject to flood control. If flood control trips
mid-batch, reply `Queued K/N ideas before flood-control limit. Resubmit the
remaining {N-K} once pipeline drains.` There is no override.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| Operator's parsing correction rejects a queued strategy | Log to `.learnings/PARSING_CORRECTIONS.md`. After 3 occurrences of the same shorthand, promote rule to `MEMORY.md`. |
| Telegram delivery fails | Re-emit as a `workflow.stuck` so qr_monitor surfaces it on next 30m cycle. Do NOT loop. |
| Hub wakes us with an event we have no handler for | Log + mark processed (silent skip is the bug, not a feature). |

## Success metrics

- Time from operator message to `experiment.started` ≤ 30s (P95).
- 0 bypasses of flood control per quarter.
- 0 duplicate experiments (same canonical param_set within 30d).
- 100% of `qa.validated` events relayed to operator within one heartbeat (5 min).

## Skills consulted

- `skills/idea_parsing.md`
- `skills/strategy_registry.md` (for default param ranges)
