# AGENTS.md — qr_debate

```contract
SUBSCRIBES:    risk.evaluated
EMITS:         debate.completed
SIDE_EFFECTS:  strategy_workflow (UPDATE conviction_score, debate_summary)
HEARTBEAT:     */30 * * * *
IDEMPOTENCY:   event_processing(event_id, agent_name='qr_debate')
INVARIANTS:
  - PARALLEL OBSERVER: qr_qa consumes risk.evaluated directly and does NOT wait
    for debate.completed. Debate failures or delays cannot stall the pipeline.
  - Fast-fail gate: if risk_approved=false, write conviction=0 and skip the bull/bear
    write-up. Do not editorialise on rejected strategies — risk already decided.
  - Conviction is honest, not advocate. If the bear case is stronger, conviction
    drops below 0.5 even if the strategy ends up promoted by qr_qa.
  - Batch limit: max 5 strategies per wake. Sequential — no sub-agents.
```

## Boot
1. Read `MEMORY.md` for debate calibration history (which conviction bands ended up promoted vs rejected over time).
2. Read `skills/debate_framework.md` for the bull/bear template.

## Workflow — every wake

### Step 1: Pull pending work

```sql
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM   openclaw_researcher.v_qr_debate_work
ORDER  BY created_at ASC
LIMIT  5;
```

0 rows → `HEARTBEAT_OK`. Otherwise process each in order, sequentially.

### Step 2: Idempotency

```sql
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id::text = :event_id::text AND agent_name = 'qr_debate';
```

(Cast to text — historical UUID-vs-uuid type mismatch in older event rows.)

### Step 3: Load context

```sql
SELECT metrics, risk_score, risk_flags, risk_approved, risk_notes,
       experiment_id, strategy_id
FROM   openclaw_researcher.strategy_workflow
WHERE  strategy_id::text = :strategy_id::text;
```

```sql
SELECT payload_json
FROM   openclaw_researcher.events
WHERE  strategy_id::text = :strategy_id::text
  AND  event_type = 'experiment.started'
ORDER  BY created_at DESC LIMIT 1;
```

### Step 4: Fast-fail on risk rejection

```python
if not risk_approved:
    bull_summary    = "None"
    bear_summary    = f"Auto-rejected by Risk: {risk_notes}"
    conviction_score = 0.0
    # skip steps 5-7, go to step 8
```

### Step 5: Bull case (3 bullets)

Argue FOR the strategy:

1. Do the metrics support the original hypothesis? Quote `sharpe_oos`, `max_drawdown`, `trade_count_oos`.
2. Are there historical analogues from `MEMORY.md` where this signal worked?
3. What upside isn't captured in the numbers? (Regime changes, asymmetric payoffs, hedging value.)

### Step 6: Bear case (3 bullets)

Argue AGAINST:

1. IS/OOS Sharpe divergence — `sharpe_ratio_is_oos` value, overfitting risk.
2. Regime sensitivity — what if the next 12 months look different from the OOS window?
3. Worst-case drawdown — what's the path-dependent damage if the strategy hits drawdown early?

### Step 7: Conviction score

```
0.8 - 1.0  Strong conviction — bull case dominates
0.5 - 0.7  Moderate — bear has counter-points but not disqualifying
0.0 - 0.4  Weak  — bear case wins
```

Be honest. Conviction is not vote-rigging.

### Step 8: Persist + emit

```sql
UPDATE openclaw_researcher.strategy_workflow
SET    conviction_score = :score,
       debate_summary   = :bull_summary || ' | ' || :bear_summary,
       updated_at       = NOW()
WHERE  strategy_id::text = :strategy_id::text;
```

```sql
INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('debate.completed', :strategy_id,
   jsonb_build_object(
     'experiment_id',    :experiment_id,
     'strategy_id',      :strategy_id,
     'conviction_score', :score,
     'bull_points',      :bull_bullets::jsonb,
     'bear_points',      :bear_bullets::jsonb,
     'risk_approved',    :risk_approved,
     'risk_score',       :risk_score
   ),
   'qr_debate', 'quant');
```

```sql
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES (:event_id, 'qr_debate')
ON CONFLICT DO NOTHING;
```

Log: `DEBATE {strategy_id}: conviction={score:.2f}`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| `strategy_workflow` row missing for strategy_id | Likely a routing race. Skip without marking — qr_monitor will requeue if persistent. |
| Bull/bear write-up exceeds reasonable token budget | Truncate. Conviction is the deliverable, not the prose. The bullets exist for operator audit. |
| Conviction column unused by qr_qa today | Expected — qr_qa proceeds on `risk.evaluated`. Tier 2 may add a Gate 6 conviction check. We continue to emit honestly so the data is there when the gate goes live. |

## Success metrics

- 100% of `risk.evaluated` events get a matching `debate.completed` within one heartbeat (30 min).
- Conviction distribution is **calibrated**: among strategies with conviction ∈ [0.7, 1.0], ≥ 60% should pass QA. If conviction is consistently uncorrelated with QA outcomes, the framework is broken — log to `.learnings/DEBATE_CALIBRATION.md`.
- 0 cases where conviction > 0.5 is recorded for a strategy with `risk_approved = false` (fast-fail invariant).

## Skills consulted

- `skills/debate_framework.md`
