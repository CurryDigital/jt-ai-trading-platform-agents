# AGENTS.md — qr_exp_manager

```contract
SUBSCRIBES:    qa.validated  (both passed=true and passed=false trigger us)
EMITS:         experiment.started (variants)
SIDE_EFFECTS:  strategy_workflow (INSERT), events (INSERT),
               workflow_events (INSERT cycle markers: nightly_cycle_complete, weekly_summary_complete)
HEARTBEAT:     */30 * * * *  (reactive on qa.validated; self-gates nightly + weekly)
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_exp_manager') for reactive,
               workflow_events markers for time-bound work
INVARIANTS:
  - Reactive: drain v_exp_manager_work, generate variants, no time gate.
  - Time-bound: nightly seeding gated by 'nightly_cycle_complete' marker per UTC date,
    weekly summary gated by 'weekly_summary_complete' per ISO week.
  - Flood control: if in-flight strategies ≥ FLOOD_CONTROL_LIMIT (50) → exit
    WITHOUT marking processed. The reactive event re-fires on the next 30-min
    cycle once the pipeline drains.
  - Directed mutation: failed strategies generate 1-2 variants per the failed_gate
    table. Passed strategies generate 3 variants (or 5 if family pass-rate > 30%).
  - Family pruning: if a family (strategy_type + asset_universe) has ≥ 20
    experiments and pass-rate < 5% → PRUNE (no variants, log to MEMORY.md dead-ends).
  - Dedup: skip variants whose canonical param_set has run in the last 30 days.
```

## Boot
1. Read `MEMORY.md` for dead-end families + research landscape.
2. Read `.learnings/STRATEGY_PATTERNS.md` for what works/doesn't.
3. Read `skills/experiment_design.md` for the directed-mutation table + variant rules.

## Workflow — every wake

### Phase A: Reactive — drain v_exp_manager_work

```sql
SELECT event_id, strategy_id, payload_json
FROM   openclaw_researcher.v_exp_manager_work
ORDER  BY created_at ASC
LIMIT  1;
```

If 0 rows → skip Phase A, jump to Phase B (time-bound work).

For the row:

#### A1. Idempotency

```sql
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = :event_id AND agent_name = 'qr_exp_manager';
```

#### A2. Flood control

```sql
SELECT COUNT(*) FROM openclaw_researcher.strategy_workflow
WHERE  status NOT IN ('completed', 'failed', 'golden', 'rejected');
```

If `≥ FLOOD_CONTROL_LIMIT` (50) → log `Flood control: {N}/50 in-flight, exiting`. Do NOT mark processed. The next 30-min wake retries.

#### A3. Family-health check (decides pruning before generating)

```sql
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE payload_json->>'passed' = 'true') AS passed
FROM   openclaw_researcher.events
WHERE  event_type = 'qa.validated'
  AND  payload_json->'param_set'->>'strategy_type' = :strategy_type
  AND  created_at > NOW() - INTERVAL '30 days';
```

| Condition | Action |
|-----------|--------|
| `total >= 20` AND `passed/total < 0.05` | PRUNE — append family to MEMORY.md `dead_ends`, mark processed, exit. |
| `passed/total > 0.30` over the last 10 | EXPAND — generate 5 variants (instead of 3) on a pass. |
| otherwise | Standard — 3 variants on pass, 1-2 on fail. |

#### A4. Directed variant generation

Read `passed`, `failed_gate`, `rejection_reason` from the qa.validated payload.

**On pass** — generate `EXP_PHASE1_VARIANTS_PASS` (3) or `EXP_PHASE2_VARIANTS` (5 if expanding):

For each variant, mutate ONE parameter by ±10-25% (lookback_window, entry_threshold, exit_threshold, …). Stay within `PARAM_*_MIN/MAX` bounds.

**On fail** — generate `EXP_PHASE1_VARIANTS_FAIL` (1-2) per the directed-mutation table:

| Failed gate | Mutation |
|-------------|----------|
| Gate 1 (risk rejected) | reduce position concept; add stop-loss param |
| Gate 2 (low Sharpe OOS) | increase entry_threshold by +25% |
| Gate 3 (high drawdown) | add stop-loss; reduce holding period |
| Gate 4 (low trade count) | extend date_range by 1 year; lower entry_threshold |
| Gate 5 (overfitting / IS-OOS divergence) | reduce lookback_window; remove one parameter |
| Gate 0 (anti-hallucination) | DO NOT generate variants — this is a qr_algo bug, log to .learnings |

#### A5. Dedup each variant

```sql
SELECT 1 FROM openclaw_researcher.events
WHERE  event_type = 'experiment.started'
  AND  domain = 'quant'
  AND  created_at > NOW() - INTERVAL '30 days'
  AND  md5(payload_json->'param_set'::text) = md5(:canonical_param_set::text)
LIMIT 1;
```

Skip silently on hit.

#### A6. Insert variants

For each unique variant, use the canonical pattern:

```sql
BEGIN;

INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, assigned_by)
VALUES (:uuid, :name, 'pending', :exp_id, 'qr_exp_manager');

INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('experiment.started', :strategy_id,
   jsonb_build_object(
     'experiment_id',         :exp_id,
     'strategy_id',           :strategy_id,
     'param_set',             :param_set::jsonb,
     'generation',            :parent_generation + 1,
     'parent_experiment_id',  :parent_exp_id,
     'parent_failed_gate',    :parent_failed_gate,
     'mutation_rationale',    :mutation_rationale,
     'source',                'qr_exp_manager'
   ),
   'qr_exp_manager', 'quant');

COMMIT;
```

#### A7. Mark processed + log

```sql
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES (:event_id, 'qr_exp_manager') ON CONFLICT DO NOTHING;
```

Append to `memory/YYYY-MM-DD.md`: parent strategy_id, parent result, gate feedback, variants generated.

Log: `EXP_MANAGER reactive: parent={parent_id} passed={passed} variants={N}`.

### Phase B: Self-gated nightly cycle (16:00-16:30 UTC)

```sql
SELECT 1 FROM openclaw_researcher.workflow_events
WHERE  agent = 'qr_exp_manager'
  AND  event_type = 'nightly_cycle_complete'
  AND  created_at::date = CURRENT_DATE;
```

If exists OR not in 16:00 UTC window → skip Phase B, jump to Phase C.

Otherwise:

```sql
SELECT strategy_id, sharpe_oos, max_drawdown, param_set
FROM   openclaw_researcher.strategy_lineage
WHERE  promoted_at > NOW() - INTERVAL '7 days'
  AND  sharpe_oos > 0.5
ORDER  BY sharpe_oos DESC LIMIT 5;
```

- ≥ 1 row → for each top performer, generate `EXP_PHASE2_VARIANTS` (5) variants around the param_set (steps A4–A6 reused).
- 0 rows → seed `EXP_NIGHTLY_FALLBACK_COUNT` (3) random experiments across underexplored types from `skills/strategy_registry.md`.

```sql
INSERT INTO openclaw_researcher.workflow_events (event_type, agent, data)
VALUES ('nightly_cycle_complete', 'qr_exp_manager',
        jsonb_build_object('top_performers', :n_top, 'variants', :n_variants, 'fallback', :did_fallback));
```

Log: `EXP_MANAGER nightly: top={N}, variants={M}, fallback={bool}`.

### Phase C: Self-gated weekly summary (Sunday 00:00-00:30 UTC)

```sql
SELECT 1 FROM openclaw_researcher.workflow_events
WHERE  agent = 'qr_exp_manager'
  AND  event_type = 'weekly_summary_complete'
  AND  created_at > date_trunc('week', NOW());
```

If exists OR not Sunday 00:00 UTC → exit.

Otherwise compose a one-line summary and emit it as an `etl.operator_alert` event so qr_idea_intake relays it (qr_exp_manager doesn't talk to Telegram directly):

```sql
INSERT INTO openclaw_researcher.events
  (event_type, payload_json, source_agent, domain)
VALUES
  ('etl.operator_alert', jsonb_build_object(
     'channel', 'weekly_summary',
     'message', 'Week summary: {total} experiments, {passed} passed QA, top Sharpe OOS {top}, most-rejected gate {gate}, suggested next direction: {direction}'
   ),
   'qr_exp_manager', 'quant');

INSERT INTO openclaw_researcher.workflow_events (event_type, agent, data)
VALUES ('weekly_summary_complete', 'qr_exp_manager', :summary::jsonb);
```

## Failure modes

| Symptom | Recovery |
|---------|----------|
| Flood control hit | Skip without marking processed. Pipeline drains over the next 1-2h, then this event re-fires. |
| Dedup catches all variants | Log "no novel variants this generation". Mark processed (the parent has been considered). |
| Family pruned | Log family + reason to `MEMORY.md::dead_ends`. Future reactive events for this family skip variant generation. |
| `strategy_lineage` empty during nightly cycle | Fall back to seed mode. Don't skip the cycle marker — that re-triggers the gate next wake. |

## Success metrics

- Reactive: ≥ 95% of `qa.validated` events produce at least one variant within 30 min (unless flood control or dedup).
- Nightly: 1 cycle per UTC day (single `nightly_cycle_complete` row per date).
- Weekly: 1 summary per ISO week, delivered Sunday morning Singapore time.
- Family pruning: dead-end families never generate variants twice (verify in MEMORY.md).

## Skills consulted

- `skills/experiment_design.md` — variant generation rules + directed-mutation table
- `skills/strategy_registry.md` — for fallback random seeding + canonical strategy_type names
- `skills/lineage_and_promotion.md` — to understand which lineage rows are eligible for nightly seeding
