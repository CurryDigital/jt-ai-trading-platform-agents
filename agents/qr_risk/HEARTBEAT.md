# HEARTBEAT.md — qr_risk (every 30 min)

```
schedule: */30 * * * *
target:   agent:qr_risk:main
message:  Drain v_qr_risk_work. Load thresholds from risk_config (name NOT LIKE 'qa_%'). Run 6 checks, compute risk_score = flags/6, set risk_approved = (score == 0). ALWAYS emit risk.evaluated — even on rejection. Full SQL in AGENTS.md.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 1 | Pull up to 5 from `v_qr_risk_work` |
| 2 | Idempotency check |
| 3 | Load `metrics` from payload + concentration from trade ledger |
| 4 | Load 6 thresholds from `risk_config` |
| 5 | Evaluate 6 checks via `check_threshold` |
| 6 | UPDATE `strategy_workflow` (score, flags, approved, notes) |
| 7 | INSERT `risk.evaluated` event (ALWAYS — even on reject) |
| 8 | INSERT `event_processing` |

## Exit conditions

- 0 rows in v_qr_risk_work → `HEARTBEAT_OK`.
- All rows processed → log `EVALUATED {N} strategies` and exit.
- `risk_config` empty → log CRITICAL and exit. Do NOT default to "approve everything".
