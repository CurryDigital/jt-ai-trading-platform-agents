# HEARTBEAT.md — qr_qa (every 30 min)

```
schedule: */30 * * * *
target:   agent:qr_qa:main
message:  Drain v_qr_qa_work. Run 5 gates in order, stop at first fail. ON PASS — INSERT strategy_lineage AND emit qa.validated in ONE transaction. ON FAIL — emit qa.validated(passed=false) with failed_gate. Mark processed. Full SQL in AGENTS.md.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 1 | Pull up to 5 from `v_qr_qa_work` |
| 2 | Idempotency check |
| 3 | Load metrics + trade ledger evidence |
| 4 | Load 4 QA thresholds (`name LIKE 'qa_%'`) |
| 5 | Run gates 0-5 in strict order; stop at first fail |
| 6 | ON PASS: atomic lineage + event INSERT (single transaction). ON FAIL: rejection event only. |
| 7 | INSERT `event_processing` |

## Exit conditions

- 0 rows in v_qr_qa_work → `HEARTBEAT_OK`.
- All rows processed → log `QA: {pass}/{N} passed` and exit.
- QA threshold rows missing in `risk_config` → log CRITICAL and raise. Do NOT default to "pass".

## Hard rules

- Atomicity: lineage INSERT and qa.validated INSERT share one connection + one commit. If you ever split them across two transactions, you've broken the invariant — the operator's MTBF for "promoted but no event" goes from 0 to ∞.
- Order matters: Gate 0 first. If trade ledger doesn't match metrics, nothing else is real.
