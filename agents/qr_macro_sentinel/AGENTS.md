# AGENTS.md — qr_macro_sentinel

```contract
SUBSCRIBES:    none (self-gated heartbeat agent)
EMITS:         experiment.started (high-confidence macro events only)
SIDE_EFFECTS:  macro_events (INSERT), strategy_workflow (INSERT), events (INSERT),
               workflow_events (INSERT cycle marker)
HEARTBEAT:     */30 * * * *  (self-gates 2h via macro_scan_complete marker)
IDEMPOTENCY:   workflow_events.event_type='macro_scan_complete' per 2h window
INVARIANTS:
  - Self-gated. Wakes every 30 min, but only scans if last
    macro_scan_complete > 2h ago. Otherwise → HEARTBEAT_OK.
  - Two-stage emission: (1) ALL findings logged to .learnings/MACRO_EVENTS.md +
    macro_events table; (2) experiment.started ONLY if confidence='high' AND
    historical precedent exists in MEMORY.md.
  - Promotion rule: same event pattern observed 3+ times with consistent impact
    → append to MEMORY.md as a "macro rule" (becomes precedent for future
    high-confidence emissions).
  - Every 4th cycle, audit past predictions: query gold layer for actual_impact,
    update macro_events row, log calibration drift.
```

## Boot
1. Read `MEMORY.md` for confirmed macro rules (precedent library).
2. Read `.learnings/MACRO_EVENTS.md` for event history.
3. Read `skills/macro_research.md` for the watchlist + assessment template.

## Workflow — every wake

### Step 0: Self-gate

```sql
SELECT MAX(created_at) AS last_scan,
       COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '8 hours') AS recent_scans
FROM   openclaw_researcher.workflow_events
WHERE  agent = 'qr_macro_sentinel'
  AND  event_type = 'macro_scan_complete';
```

```python
if last_scan and (now() - last_scan) < timedelta(hours=2):
    log("HEARTBEAT_OK (last macro scan < 2h ago)")
    return

audit_cycle = (recent_scans % 4 == 3)   # every 4th scan
```

### Step 1: Web scan (rotate watchlist queries)

Pick one query per cycle, rotating through:

```
"market moving news today"
"Trump trade policy tariff latest"
"Federal Reserve interest rate decision"
"OPEC oil production meeting"
"China economic data PMI"
"cryptocurrency regulation SEC"
"geopolitical tension conflict"
"corporate earnings surprise this week"
```

Use Brave Search API. Keep requests to 1 per scan — we are not a news firehose.

### Step 2: Assess each significant finding

For each event the search surfaces:

1. **Asset classes affected** — equities (which sector ETF?), crypto, FX pair, commodities.
2. **Direction** — bullish / bearish / neutral, with rationale.
3. **Historical precedent** — query `MEMORY.md` macro rules + `macro_events` table:

   ```sql
   SELECT event_date, description, actual_impact
   FROM   openclaw_researcher.macro_events
   WHERE  event_type ILIKE :similar_pattern
     AND  actual_impact IS NOT NULL
   ORDER  BY event_date DESC LIMIT 5;
   ```

4. **Confidence** ∈ {low, medium, high}:
   - `high`: similar event in `macro_events` ≥ 3 times with consistent direction
   - `medium`: 1-2 prior events, or theoretical chain is clear
   - `low`: novel, no precedent

### Step 3: Log to macro_events + .learnings

For every assessed event (not just high-confidence):

```sql
INSERT INTO openclaw_researcher.macro_events
  (event_date, event_type, description, affected_assets,
   expected_impact, confidence, source_url)
VALUES
  (:date, :event_type, :description, :affected::text[],
   :expected_impact, :confidence, :source_url);
```

Append the same to `.learnings/MACRO_EVENTS.md` in the structured format (status=`pending` until step 5 fills `actual_impact`).

### Step 4: Conditional emission — high confidence + precedent only

If and only if `confidence='high' AND len(historical_precedent) >= 3`:

```sql
INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, assigned_by)
VALUES
  (:uuid, 'macro_' || :event_type || '_' || :date, 'pending', :exp_id, 'qr_macro_sentinel');

INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES
  ('experiment.started', :strategy_id,
   jsonb_build_object(
     'experiment_id',  :exp_id,
     'strategy_id',    :strategy_id,
     'param_set',      jsonb_build_object(
       'strategy_type',  'geopolitical_event',
       'asset_universe', :affected_assets,
       'date_range',     jsonb_build_object('start', :hist_start, 'end', :now),
       'description',    :description,
       'hypothesis',     :expected_impact
     ),
     'macro_context',  jsonb_build_object(
       'event_type',  :event_type,
       'event_date',  :date,
       'precedent',   :precedent::jsonb,
       'confidence',  :confidence,
       'source_url',  :source_url
     ),
     'source',         'qr_macro_sentinel',
     'generation',     1
   ),
   'qr_macro_sentinel', 'quant');
```

Hub picks up `experiment.started` on its next 30-min cycle.

### Step 5: Audit cycle (every 4th scan = ~8h cadence)

```sql
SELECT id, event_date, event_type, affected_assets, expected_impact
FROM   openclaw_researcher.macro_events
WHERE  actual_impact IS NULL
  AND  event_date < CURRENT_DATE - INTERVAL '3 days';
```

For each row, query gold layer for the affected assets' 2-day return after `event_date`. Update `actual_impact` and compare against `expected_impact`. If correct → boost confidence weight; if wrong → log miscalibration to `.learnings/LEARNINGS.md`.

### Step 6: Promotion check

For each `event_type` with ≥ 3 confirmed-correct predictions:

Append to `MEMORY.md` under "Macro rules":
```
- {event_type}: {affected_assets} {direction}, typical {return_range} over {window}
  (confirmed N times, last {date})
```

### Step 7: Write cycle marker

```sql
INSERT INTO openclaw_researcher.workflow_events (event_type, agent, data)
VALUES ('macro_scan_complete', 'qr_macro_sentinel',
        jsonb_build_object('query', :query_used,
                           'findings', :n_findings,
                           'emitted', :n_emitted,
                           'audit_cycle', :audit_cycle));
```

Log: `MACRO scan="{query}": {findings} findings, {emitted} emitted, audit={audit_cycle}`.

## Failure modes

| Symptom | Recovery |
|---------|----------|
| Brave API rate limit | Log + skip the scan. Write cycle marker so the gate doesn't fire again for 2h. |
| Web returns no significant findings | Normal. Write cycle marker, log `MACRO: clean scan`. |
| Audit cycle finds 5+ wrong predictions in a row | Log CRITICAL to `.learnings/LEARNINGS.md`. Lower confidence threshold for emission until calibration recovers. |
| `gold.stock_metrics_history` missing data for affected_assets | Skip the audit row, retry on next audit cycle. |

## Success metrics

- 12 scans per day (~one every 2h).
- ≤ 2 high-confidence emissions per day (we are not a signal firehose — quality > volume).
- Audit hit-rate ≥ 60% on high-confidence predictions (calibration check).

## Skills consulted

- `skills/macro_research.md`
- `skills/event_driven_research.md`
