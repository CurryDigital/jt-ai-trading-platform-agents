# HEARTBEAT.md — qr_etl_manager (every 30 min, self-gated daily)

```
schedule: */30 * * * *
target:   agent:qr_etl_manager:main
message:  Self-gated. If a 'daily_cycle_complete' workflow_event exists for today (UTC) → HEARTBEAT_OK. Otherwise — only between 14:00-14:30 UTC, OR if the wake was triggered by an etl.refresh_requested event — UPDATE gold_layer_state SET state='locked', run bronze sources, run daily_refresh.sh, UPDATE gold_layer_state with final state ∈ {ready,partial,stale,failed}, emit etl.completed | etl.partial | etl.failed, write daily_cycle_complete workflow_event.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 0 | Self-gate: today's marker exists OR not in 14:00-14:30 UTC window AND not manually triggered → `HEARTBEAT_OK` |
| 1 | UPDATE `gold_layer_state` SET state='locked', locked_since=NOW() |
| 2 | Run 4 bronze sources in order; capture exit + reason per source |
| 3 | Run `agents/etl/daily_refresh.sh` (silver / gold / consumption) |
| 4 | Compute final state per the truth table in AGENTS.md |
| 5 | UPDATE `gold_layer_state` with final state, sources_ok/failed, refreshed_at, locked_since=NULL |
| 6 | INSERT `etl.completed` / `etl.partial` / `etl.failed` event |
| 7 | INSERT `daily_cycle_complete` workflow_event marker |

## Exit conditions

- Today's marker present → `HEARTBEAT_OK`.
- Outside 14:00-14:30 UTC and no manual trigger → `HEARTBEAT_OK`.
- Refresh complete → log `ETL {state}: ok={N}, failed={M}, duration={Ts}` and exit.
- Manual trigger via `etl.refresh_requested` → run now regardless of window.

## Override

Force a re-refresh even if today's marker exists:

```sql
DELETE FROM openclaw_researcher.workflow_events
WHERE  agent = 'qr_etl_manager'
  AND  event_type = 'daily_cycle_complete'
  AND  created_at::date = CURRENT_DATE;

-- then operator emits etl.refresh_requested OR waits for next 14:00 UTC wake
```

## Hard rules

- Never UPDATE `gold_layer_state` to `state='locked'` without setting `locked_since=NOW()`. qr_monitor's `clear_stale_gold_lock(12)` relies on `locked_since` to detect wedged refreshes.
- Never UPDATE `gold_layer_state` to `state='ready'` if `daily_refresh.sh` exited non-zero. `ready` means downstream agents may proceed; lying here cascades into bad backtests.
