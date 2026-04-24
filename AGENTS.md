# AGENTS.md — Quant Research Pipeline

## Agent topology

| Agent | Lifecycle | Heartbeat | Role |
|-------|-----------|-----------|------|
| qr_hub | Always-on | 5m | Central event router + stuck detection |
| qr_researcher | Always-on | 6h | Autonomous idea generation |
| qr_macro_sentinel | Always-on | 2h | Geopolitical event monitoring |
| qr_architect | Always-on | 1h | Self-improving architecture loop |
| qr_monitor | Always-on | 30m | Watchdog for stuck workflows |
| qr_etl_manager | Always-on | daily | Data supply chain |
| qr_idea_intake | Reactive | — | Telegram idea parsing |
| qr_exp_manager | Reactive + daily | daily | Variant generation |
| qr_data_validator | Reactive | — | Data quality gating |
| qr_algo | Reactive | — | Backtest execution |
| qr_risk | Reactive | — | Risk evaluation |
| qr_debate | Reactive | — | Bull/Bear adversarial |
| qr_qa | Reactive | — | Final quality gates |

## Pipeline flow

```
Idea sources (intake / researcher / macro) → experiment.started
  → Hub routes → validator → dataset.ready
  → Hub routes → algo → backtest.completed
  → Hub routes → risk → risk.evaluated
  → Hub routes → debate → debate.completed
  → Hub routes → qa → qa.validated
  → Hub routes → exp_manager (variants) + idea_intake (notify)
```

## Rules
1. All inter-agent communication goes through the events table
2. Hub is the ONLY agent that calls sessions_send to wake others
3. Pipeline agents emit output events to DB, Hub picks them up
4. Every agent checks idempotency before processing
5. Lessons learned go to .learnings/, promoted to MEMORY.md when recurring
