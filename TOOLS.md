# TOOLS.md — Infrastructure & shared tool surface

Per-agent tool surfaces (allowed Bash commands, MCP servers, API keys) live
in `agents/<id>/TOOLS.md`. This file is the cross-agent baseline.

---

## Database (single source of truth)

- **Engine:** PostgreSQL on RDS (`ap-southeast-1`)
- **Schema:** `openclaw_researcher` (writable) + `gold` (READ-ONLY view)
- **Auth:** static password from `/home/ubuntu/.openclaw/.env::DB_PASSWORD`
  (IAM-token auth removed — caused intermittent connection drops; see
  hub/router.py::HubRouter._get_conn)
- **Connection rule:** open per-call, close in `finally`. No connection
  pooling — agents are short-lived per event.

### Tables an agent may write

| Table | Writers | Notes |
|-------|---------|-------|
| `events`             | any agent (`emit_event` / direct INSERT) | append-only |
| `event_processing`   | any agent on dedup | `(event_id, agent_name)` PK |
| `strategy_workflow`  | qr_idea_intake, qr_algo, qr_risk, qr_qa | one row per strategy_id |
| `strategy_lineage`   | qr_qa only (atomic w/ qa.validated) | append-only |
| `workflow_events`    | any agent (audit log) | high volume, paginate reads |
| `routing_rules`      | qr_architect (proposals only — never auto-write) | |
| `risk_config`        | operator + qr_architect proposals | |
| `gold_layer_state`   | qr_etl_manager (UPDATE) + qr_monitor (auto-unlock) | singleton |

### Read-only views (use these instead of raw queries)

| View | For | Filters |
|------|-----|---------|
| `v_pending_events`           | qr_hub                 | not yet routed by hub |
| `v_monitor_overview`         | qr_monitor             | in-flight + elapsed_minutes + gold state |
| `v_data_validator_work`      | qr_data_validator      | experiment.started + gold-layer state |
| `v_risk_work`                | qr_risk                | backtest.completed pending |
| `v_debate_work`              | qr_debate              | risk.evaluated pending |
| `v_exp_manager_work`         | qr_exp_manager         | qa.validated pending |
| `v_strategy_lineage_full`    | operator queries       | full denormalised history |
| `v_gold_layer_status`        | any                    | hours_since_refresh + state |

### Helper functions

| Function | Use |
|----------|-----|
| `emit_event(type, sid, payload, source, domain)`   | append + log to workflow_events |
| `record_processing(event_id, agent_name)`          | mark dedup |
| `record_lineage(...)`                              | (legacy — qr_qa now writes lineage inline for atomicity) |
| `get_pending_for_agent(agent, domain)`             | sdk fallback |
| `clear_stale_gold_lock(hours=12)`                  | qr_monitor heartbeat |

---

## Filesystem

- **Workspace:** `/home/ubuntu/.openclaw/workspace/quant_research`
- **Repo root:** symlinked under workspace
- **Learnings:** `agents/<id>/.learnings/<topic>.md` — promoted to `MEMORY.md` after 3 recurrences
- **Notification queue (fallback):** `hub/.notification_queue` (one JSON line per dispatch when `sessions_send` is unavailable)

---

## OpenClaw harness

| Capability | Use |
|------------|-----|
| `sessions_send(session_key, message)` | **only qr_hub** may call this; emit events otherwise |
| Scheduler (`cron` blocks in HEARTBEAT.md) | reads each `agents/<id>/HEARTBEAT.md` |
| Skill loader (`skills/<name>.md`) | any agent reads its skills via `Read` |
| `agents/shared/constants.py` | single source of truth for IDs, timeouts, knobs |
| `agents/shared/threshold.py::check_threshold` | risk + qa gate evaluation |

---

## Agent session keys (kept in sync with `hub/router.py::AGENT_SESSIONS`)

| Agent | Session key |
|-------|-------------|
| qr_hub             | agent:qr_hub:main |
| qr_monitor         | agent:qr_monitor:main |
| qr_architect       | agent:qr_architect:main |
| qr_researcher      | agent:qr_researcher:main |
| qr_macro_sentinel  | agent:qr_macro_sentinel:main |
| qr_idea_intake     | agent:qr_idea_intake:main |
| qr_etl_manager     | agent:qr_etl_manager:main |
| qr_exp_manager     | agent:qr_exp_manager:main |
| qr_data_validator  | agent:qr_data_validator:main |
| qr_algo            | agent:qr_algo:main |
| qr_risk            | agent:qr_risk:main |
| qr_debate          | agent:qr_debate:main |
| qr_qa              | agent:qr_qa:main |

---

## External tool surfaces (per-agent)

The following tools are sandboxed to specific agents — listed here so
qr_architect can audit cross-agent reach. See each agent's `TOOLS.md` for
allow-listed commands.

| Tool | Agent(s) | Why |
|------|----------|-----|
| Telegram bot API     | qr_idea_intake          | only operator-facing channel |
| Brave Search API     | qr_macro_sentinel, qr_researcher | web research |
| `python3 agents/etl/bronze/*/ingest_*.py` | qr_etl_manager | bronze pulls |
| `bash agents/etl/daily_refresh.sh`        | qr_etl_manager | silver/gold transform |
| Web fetch (read-only)| qr_macro_sentinel, qr_researcher | source verification |

No agent has unrestricted shell access. Anything not in its `TOOLS.md` allow-list is denied.
