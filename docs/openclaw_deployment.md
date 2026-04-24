# OpenClaw Deployment Guide

## Overview

This document covers every step to go from files → 8 running agents
on OpenClaw, including the exact system prompt for each session.

**Canonical session keys (source of truth: hub/router.py AGENT_SESSIONS)**

| Agent | Session key |
|-------|-------------|
| Hub | agent:qr_hub:main |
| Monitor | agent:qr_monitor:main |
| Idea Intake | agent:qr_idea_intake:main |
| Exp. Manager | agent:qr_exp_manager:main |
| DE | agent:qr_data_validator:main |
| Algo | agent:qr_algo:main |
| Risk | agent:qr_risk:main |
| QA | agent:qr_qa:main |
| ETL Manager | agent:qr_etl_manager:main |

---

## Step 1 — Run the schema migrations

Run both against your RDS instance. Both are idempotent (safe to re-run).

```bash
# Migration 001 — base schema
psql "host=$RDS_HOST port=$RDS_PORT dbname=$RDS_DBNAME user=$RDS_USER sslmode=require" \
     -f hub/migration_001.sql

# Migration 002 — patches 001: fixes column name ambiguity, recreates views correctly
psql "host=$RDS_HOST port=$RDS_PORT dbname=$RDS_DBNAME user=$RDS_USER sslmode=require" \
     -f hub/migration_002.sql
```

Always run all three in order.

```bash
# Migration 003 — gold_layer_state + v_data_validator_work
psql "host=$RDS_HOST port=$RDS_PORT dbname=$RDS_DBNAME user=$RDS_USER sslmode=require" \\
     -f hub/migration_003.sql
```

Always run both in order. Migration 002 is safe to re-run even if 001 was clean.

---

## Step 2 — Upload workspace to the EC2 instance

```bash
scp -i "openclaw_kp.pem" -r ./quant_research \
    ubuntu@ec2-13-214-84-37.ap-southeast-1.compute.amazonaws.com:~/.openclaw/workspace/
```

Required layout on instance:
```
/home/ubuntu/.openclaw/workspace/quant_research/
  hub/                        <- router, sdk, service, migrations
  agents/
    hub/                      <- hub, monitor, exp_manager, idea_intake agents
    pipeline/                <- de, algo, risk, qa agents
    shared/                   <- db.py + schema.md, param_set_spec.md, etc.
  sessions/                   <- session config files (copy system prompts from here)
  skills/                     <- all skill .md files
  souls/                      <- all soul .md files
  docs/                       <- this file + architecture + event_contracts
```

---

## Step 3 — Install Python dependencies on the instance

```bash
ssh -i "openclaw_kp.pem" ubuntu@ec2-13-214-84-37.ap-southeast-1.compute.amazonaws.com
pip install psycopg2-binary boto3 python-dotenv --break-system-packages
```

---

## Step 4 — Create agent sessions on OpenClaw

Create one session per agent. Session key MUST exactly match hub/router.py AGENT_SESSIONS.
Full system prompt content for each session is in sessions/<agent>.md.

For each session: create it → paste system prompt → set entrypoint → add env vars → enable sessions_send tool.

---

### Hub — agent:qr_hub:main

Lifecycle: Always-on
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/isolated/hub_agent.py
```
System prompt: see sessions/hub.md
Tools: sessions_send REQUIRED
Channel: None
Note: Start FIRST. All routing depends on Hub being up.

---

### Monitor — agent:qr_monitor:main

Lifecycle: Always-on
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/isolated/monitor_agent.py
```
System prompt: see sessions/monitor.md
Tools: sessions_send
Channel: None
HEARTBEAT: every 30 min (*/30 * * * *)

---

### Idea Intake — agent:qr_idea_intake:main

Lifecycle: Event-reactive (channel listener)
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/isolated/idea_intake_agent.py
```
System prompt: see sessions/idea_intake.md
Tools: sessions_send
Channel: YOUR TELEGRAM BOT OR WHATSAPP NUMBER — bind here

This is the ONLY session with a channel binding.
All other sessions: no channel.

Telegram setup:
1. Create bot via BotFather, get token
2. OpenClaw → Settings → Channels → Telegram → paste token
3. Bind channel to agent:qr_idea_intake:main
4. Send /start — should reply "Ready. Send me a trading idea."

---

### Exp. Manager — agent:qr_exp_manager:main

Lifecycle: Event-reactive
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/isolated/exp_manager_agent.py
```
System prompt: see sessions/exp_manager.md
Tools: sessions_send
Channel: None
HEARTBEAT: daily 16:00 UTC (0 16 * * *), weekly Sunday 00:00 UTC (0 0 * * 0)

---

---

### ETL Manager — agent:qr_etl_manager:main

Lifecycle: Isolated (always-on)
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/isolated/etl_manager_agent.py
```
System prompt: see sessions/etl_manager.md
Tools: sessions_send
Channel: Bind to Telegram (same bot as Idea Intake, or a dedicated second bot)
HEARTBEAT: daily 02:00 UTC (0 2 * * *)

Note: Start 4th. Handles API credentials and manual data loads from operator.
All pipeline agents (DE, Algo, Risk, QA) depend on ETL Manager having refreshed
the gold layer. Run ETL Manager first on a fresh deployment before any experiments.


### Data Validator — agent:qr_data_validator:main

Lifecycle: Pipeline subagent (spawned on demand)
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/pipeline/data_validator_agent.py
```
System prompt: see sessions/data_validator.md
Tools: sessions_send
Channel: None

---

### Algo — agent:qr_algo:main

Lifecycle: Pipeline subagent
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/pipeline/algo_agent.py
```
System prompt: see sessions/algo.md
Tools: sessions_send
Channel: None

---

### Risk — agent:qr_risk:main

Lifecycle: Pipeline subagent
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/pipeline/risk_agent.py
```
System prompt: see sessions/risk.md
Tools: sessions_send
Channel: None

---

### QA — agent:qr_qa:main

Lifecycle: Pipeline subagent
Entrypoint:
```
python /home/ubuntu/.openclaw/workspace/quant_research/agents/pipeline/qa_agent.py
```
System prompt: see sessions/qa.md
Tools: sessions_send
Channel: None

---

## Step 5 — Set environment variables

Set on every session (or at gateway level):

```
RDS_HOST=<your-rds-endpoint>
RDS_PORT=5432
RDS_USER=openclaw_user
RDS_DBNAME=aitrading
AWS_REGION=ap-southeast-1
```

EC2 instance profile must have rds-db:connect IAM permission for openclaw_user.
No passwords — IAM token auth via boto3 is automatic.

---

## Step 6 — Verify AGENT_SESSIONS in hub/router.py

If OpenClaw assigns different keys, update hub/router.py:

```python
AGENT_SESSIONS = {
    "qr_monitor":     "agent:qr_monitor:main",
    "qr_data_validator":          "agent:qr_data_validator:main",
    "qr_algo":        "agent:qr_algo:main",
    "qr_risk":        "agent:qr_risk:main",
    "qr_qa":          "agent:qr_qa:main",
    "qr_exp_manager": "agent:qr_exp_manager:main",
    "qr_idea_intake": "agent:qr_idea_intake:main",
    "qr_hub":         "agent:qr_hub:main",
}
```

After any change: re-SCP hub/router.py to the instance.

---

## Step 7 — Spawn order

```
1. hub_agent         — FIRST. Must be running before any events flow.
2. monitor_agent        — Second. Safe to start in parallel with Hub.
3. idea_intake_agent    — Third. Bind to Telegram.
4. etl_manager_agent   — Fourth. Bind to Telegram (credentials + manual loads). Binds to Telegram/WhatsApp.
4. All others        — Dormant until woken. OpenClaw spawns on demand via sessions_send.
```

---

## Step 8 — Smoke test

Insert a test experiment directly into the DB:

```sql
INSERT INTO openclaw_researcher.events
    (event_type, domain, payload_json, source_agent, status)
VALUES (
    'experiment.started', 'quant',
    '{
        "experiment_id": "smoke-test-001",
        "param_set": {
            "strategy_type": "momentum",
            "lookback_window": 20,
            "entry_threshold": 1.5,
            "exit_threshold": 0.5,
            "asset_universe": ["AAPL","MSFT","GOOGL"],
            "date_range": {"start": "2022-01-01", "end": "2023-12-31"}
        },
        "generation": 1,
        "parent_experiment_id": null,
        "source": "manual"
    }',
    'manual', 'pending'
);
```

Expected cascade:
  Hub routes to DE → DE emits dataset.ready
  → Hub routes to Algo → Algo emits backtest.completed
  → Hub routes to Risk → Risk emits risk.evaluated
  → Hub routes to QA → QA emits qa.validated
  → Hub routes to Exp. Manager + Idea Intake
  → Exp. Manager generates variants
  → Idea Intake notifies operator via Telegram

Check progress:
```sql
-- Event trail
SELECT event_type, source_agent, status, created_at
FROM openclaw_researcher.events ORDER BY created_at DESC LIMIT 20;

-- Workflow audit
SELECT event_type, agent, from_status, to_status, created_at
FROM openclaw_researcher.workflow_events ORDER BY created_at DESC LIMIT 20;

-- Lineage (populated on QA pass)
SELECT strategy_id, sharpe_oos, max_drawdown, promoted_at
FROM openclaw_researcher.strategy_lineage ORDER BY promoted_at DESC LIMIT 5;
```

---

## Step 9 — Test Idea Intake via Telegram

Send to your bot:
```
momentum on AAPL, MSFT, GOOGL last 2 years
```

Expected reply:
```
Queued: momentum on [AAPL, MSFT, GOOGL], 2024-03-19 → yesterday.
Lookback: 20d (default), entry: 1.5 (default), exit: 0.5 (default).
Experiment ID: <uuid>
```

Then send:
```
status
```

Expected reply:
```
Pipeline status:
  In progress: 1 experiments
  Today: 0 evaluated, 0 passed QA
  No lineage entries yet.
```

---

## Troubleshooting

**Hub not routing**
Check Hub session is running. Check AGENT_SESSIONS keys match exactly.
Check v_pending_events has rows.

**sessions_send failing**
Check sessions_send tool is enabled. Check session key spelling.
Fallback queue: hub/.notification_queue

**DE failing Gate 1 (missing bars)**
ETL may be stale:
```sql
SELECT MAX(date) FROM gold.stock_metrics_history WHERE ticker = 'AAPL';
-- Should be yesterday on a trading day
```
If stale, run manually:
```bash
python /home/ubuntu/.openclaw/workspace/quant_research/agents/etl/gold/equity/build_stock_metrics_history.py
```

**risk_config empty**
Re-run migration_002.sql. Then verify:
```sql
SELECT COUNT(*) FROM openclaw_researcher.risk_config WHERE is_active = true;
-- Should return >= 5
```

**Pipeline agent stuck**
Monitor re-queues automatically once. If escalated to failed:
```sql
SELECT * FROM openclaw_researcher.workflow_events
WHERE to_status = 'failed' ORDER BY created_at DESC LIMIT 5;
```
