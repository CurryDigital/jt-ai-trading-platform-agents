# HEARTBEAT.md — qr_macro_sentinel (every 30 min, self-gated 2h)

```
schedule: */30 * * * *
target:   agent:qr_macro_sentinel:main
message:  Self-gated. If MAX(workflow_events.created_at WHERE event_type='macro_scan_complete') > NOW() - 2h → HEARTBEAT_OK. Otherwise rotate one query from the watchlist, log significant findings to macro_events + .learnings/MACRO_EVENTS.md, emit experiment.started ONLY when confidence=high AND historical precedent ≥ 3.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 0 | Self-gate: skip unless > 2h since last `macro_scan_complete` |
| 1 | Pick one rotating query, run Brave search (1 request per scan) |
| 2 | Assess each significant finding (assets, direction, precedent, confidence) |
| 3 | Log all findings to `macro_events` table + `.learnings/MACRO_EVENTS.md` |
| 4 | Emit `experiment.started` ONLY if confidence='high' AND ≥3 precedents |
| 5 | Audit cycle (every 4th scan): backfill `actual_impact` from gold layer for events ≥ 3 days old |
| 6 | Promotion: ≥3 confirmed-correct → append macro rule to MEMORY.md |
| 7 | Write `macro_scan_complete` workflow_event marker |

## Exit conditions

- Self-gate hit (< 2h since last scan) → `HEARTBEAT_OK`.
- Web returns nothing significant → log `MACRO: clean scan`, write marker.
- Brave API rate limit → log + skip + write marker (do NOT retry inside this heartbeat).

## Override

To force a re-scan inside the 2h window:

```sql
DELETE FROM openclaw_researcher.workflow_events
WHERE  agent = 'qr_macro_sentinel'
  AND  event_type = 'macro_scan_complete'
  AND  created_at > NOW() - INTERVAL '2 hours';
```
