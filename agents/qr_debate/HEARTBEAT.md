# HEARTBEAT.md — qr_debate (every 30 min)

```
schedule: */30 * * * *
target:   agent:qr_debate:main
message:  Drain v_qr_debate_work, max 5 per cycle. If risk_approved=false, fast-fail with conviction=0 and skip the bull/bear write-up. Otherwise produce 3 bullets bull, 3 bullets bear, conviction ∈ [0,1]. Emit debate.completed. Telemetry only — qr_qa does not wait. Full SQL in AGENTS.md.
```

## Cycle outline (full SQL in AGENTS.md)

| Step | Purpose |
|------|---------|
| 1 | Pull up to 5 from `v_qr_debate_work` |
| 2 | Idempotency check (cast event_id to text — historical type drift) |
| 3 | Load metrics, risk decision, hypothesis |
| 4 | Fast-fail if `risk_approved=false` (conviction=0, skip 5-7) |
| 5 | Bull case (3 bullets) |
| 6 | Bear case (3 bullets) |
| 7 | Conviction score ∈ [0, 1] |
| 8 | UPDATE `strategy_workflow`, INSERT `debate.completed`, INSERT `event_processing` |

## Exit conditions

- 0 rows in v_qr_debate_work → `HEARTBEAT_OK`.
- All rows processed → log `DEBATED {N} strategies, mean_conviction={mu:.2f}` and exit.

## Hard rules

- No sub-agents. Process sequentially.
- Max 5 strategies per wake. If the queue is deeper, the next 30-min cycle picks up the rest.
