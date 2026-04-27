# HEARTBEAT.md — qr_data_validator (every 30 min)

```
schedule: */30 * * * *
target:   agent:qr_data_validator:main
message:  Drain v_data_validator_work. Gold-layer gate first; if locked/stale, skip without marking. Otherwise run the 5 quality checks, update strategy_workflow, emit dataset.ready, mark processed. Full SQL in AGENTS.md.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 1 | Pull up to 5 pending events from `v_data_validator_work` |
| 2a | Idempotency check |
| 2b | Gold-layer state branch (`ready`/`partial` proceed, `locked`/`stale` skip without marking) |
| 2c | Extract idea spec from payload |
| 2d | Run 5 checks, collect flags (warnings only — never block) |
| 2e | Decide: proceed, retry, or escalate to `workflow.stuck` after `MAX_RETRY_COUNT` failures |
| 2f | UPDATE strategy_workflow, INSERT dataset.ready event |
| 2g | INSERT event_processing |

## Exit conditions

- 0 rows in v_data_validator_work → `HEARTBEAT_OK`.
- All rows processed → log `VALIDATED {N} experiments` and exit.
- Gold layer locked/stale → log per-strategy skip messages; exit without `HEARTBEAT_OK` (work remains).
