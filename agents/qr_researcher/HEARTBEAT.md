# HEARTBEAT.md — qr_researcher (every 30 min, self-gated 6h)

```
schedule: */30 * * * *
target:   agent:qr_researcher:main
message:  Self-gated. If MAX(workflow_events.created_at WHERE event_type='researcher_cycle_complete') > NOW() - 6h → HEARTBEAT_OK. Otherwise pick mode = (UTC hour) % 4, draft 1-2 hypotheses, dedup against the last 30 days, emit experiment.started, write cycle marker. Operator chat mandate OVERRIDES the gate.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 0 | Self-gate: skip unless > 6h since last `researcher_cycle_complete` (unless chat mandate) |
| 1 | Pick mode = (UTC hour) % 4 = {news, data, cross_asset, failure_driven} |
| 2 | Generate 1-2 hypotheses per the chosen mode |
| 3 | Dedup against `experiment.started` in last 30 days (strategy_type + asset_universe) |
| 4 | Queue: INSERT strategy_workflow, INSERT experiment.started |
| 5 | Write cycle marker; append to `memory/YYYY-MM-DD.md` |

## Exit conditions

- Self-gate hit (< 6h since last cycle, no chat mandate) → `HEARTBEAT_OK`.
- All hypotheses dedup'd → log "no novel hypotheses this cycle", still write cycle marker.
- Pipeline at FLOOD_CONTROL_LIMIT (50 in-flight) → skip queueing, write cycle marker (don't retry for 6h).
- Hypotheses queued → log `RESEARCHER {mode}: {N} hypotheses queued`.

## Override

To force a re-run before the 6h gate elapses:

```sql
DELETE FROM openclaw_researcher.workflow_events
WHERE  agent = 'qr_researcher'
  AND  event_type = 'researcher_cycle_complete'
  AND  created_at > NOW() - INTERVAL '6 hours';
```

The next 30-min wake will run a fresh cycle.
