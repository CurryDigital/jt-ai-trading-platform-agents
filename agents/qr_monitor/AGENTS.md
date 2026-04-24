# AGENTS.md — qr_monitor

## Boot Sequence
1. Read MEMORY.md for known threshold patterns

## On HEARTBEAT (every 30 minutes)

### Step 1: Check for stuck workflows

```sql
SELECT ep.event_id, ep.agent_name as agent_id, e.event_type,
       e.strategy_id, EXTRACT(epoch FROM now() - ep.processed_at)/60 AS elapsed_mins
FROM openclaw_researcher.event_processing ep
JOIN openclaw_researcher.events e ON e.id = ep.event_id
WHERE e.domain = 'quant' AND ep.processed_at IS NOT NULL
  AND ep.processed_at < NOW() - INTERVAL '15 minutes'
ORDER BY elapsed_mins DESC LIMIT 20;
```

Timeout thresholds:
- experiment.started: 15 min
- dataset.ready: 10 min
- backtest.completed: 30 min
- risk.evaluated: 5 min
- debate.completed: 5 min

For each exceeding threshold: check if downstream event exists for that strategy_id.
If missing → the pipeline is stuck.

### Step 2: Check for orphaned events

Events with NO event_processing rows (never routed by Hub):
```sql
SELECT e.id, e.event_type, e.strategy_id,
       EXTRACT(epoch FROM now() - e.created_at)/60 AS age_mins
FROM openclaw_researcher.events e
LEFT JOIN openclaw_researcher.event_processing ep ON e.id = ep.event_id
WHERE e.domain = 'quant' AND ep.event_id IS NULL
  AND e.created_at < NOW() - INTERVAL '10 minutes'
  AND e.event_type IN ('experiment.started','dataset.ready','backtest.completed',
                        'risk.evaluated','debate.completed','qa.validated')
ORDER BY e.created_at ASC LIMIT 20;
```

If found → Hub is not picking up events. Log warning.

### Step 3: Check gold layer health

```sql
SELECT state, refreshed_at, sources_failed,
       EXTRACT(epoch FROM now() - refreshed_at)/3600 AS hours_since_refresh
FROM openclaw_researcher.gold_layer_state LIMIT 1;
```

If hours_since_refresh > 36: log warning "Gold layer stale".

### Step 4: Weekly maintenance (Sunday only)

If today is Sunday:
- Git commit workspace: `git add -A && git commit -m "weekly snapshot"`
- Archive old memory files (>30 days)
- Review .learnings/ for entries with Recurrence-Count ≥ 3 → promote

### Summary

Report format:
```
Monitor: {N} stuck, {M} orphaned, gold layer: {state} ({hours}h old)
```
If all clear: HEARTBEAT_OK
