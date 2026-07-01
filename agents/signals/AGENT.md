# AGENT.md — Signal Generation Agent

**Agent:** 📈 Signal Generation
**Role:** Strategy framework, registry, daily signal runner, regime gating
**Domain:** `quant`
**Vibe:** Disciplined, registry-driven, no hidden state.

---

## What this agent owns

Strategy code and signal generation **only**. The Data Engineering (ETL)
agent at `agents/etl/` owns bronze/silver/gold ingestion. This agent
consumes the gold layer it produces and writes one row per
strategy per day to `gold.strategy_signals`.

```
agents/
├── etl/                          ← Data Engineering (separate agent)
│   ├── bronze/ silver/ gold/      builds gold.daily_ohlcv, gold.regime_label, …
│   └── shared/scripts/db.py       canonical DB pool (this agent imports from here)
│
└── signals/                       ← THIS AGENT
    ├── AGENT.md                   you are here
    ├── README.md                  operator quickstart
    ├── run_signal_cycle.sh        cron entry point (runs run_signals.py)
    ├── strategies/
    │   ├── registry.json          single source of truth — id, regime, enabled, params
    │   ├── registry_loader.py     validating loader (stdlib only)
    │   ├── base_strategy.py       BaseStrategy: regime gate + position sizer + save()
    │   ├── run_signals.py         daily runner — iterates enabled strategies
    │   ├── register_strategy.py   CLI: create + register a new strategy in 1 command
    │   ├── STRATEGIES.md          onboarding doc
    │   ├── stubs.py               disabled stub classes (no-op)
    │   └── trend/strategy_NN.py   real strategy implementations
    ├── regime/
    │   ├── regime_rules.py        assign_regime() + STRATEGY_MAP (derived from registry)
    │   └── train_hmm.py           HMM training (offline, run when calibration drifts)
    └── tests/
        ├── test_registry_loader.py
        └── test_regime.py
```

---

## Dependency contract

Signals **reads** gold-layer tables built by the ETL agent. It does NOT
write to any bronze/silver table. The only schemas it writes:

| Table | Operation | Trigger |
|-------|-----------|---------|
| `gold.strategy_signals` | UPSERT one row per (date, strategy_id) | every cron cycle |

If the ETL agent's gold layer is stale or missing, this agent should
**skip** that day's run rather than guess (`gold.regime_label` empty
→ `is_active_today()` returns False → all strategies emit signal=0).

The cron entry point reads `gold_layer_state.state` first; if the
state is `failed` or `locked`, it exits cleanly without writing signals.

---

## How to add a new strategy

```bash
cd agents/signals
python3 strategies/register_strategy.py \
    --id 21 \
    --name "Crypto vol carry" \
    --regime CARRY \
    --asset-class crypto \
    --module strategies.crypto.strategy_21 \
    --class-name Strategy21
```

Edit the generated file, implement `compute_signal()`, flip `enabled: true`
in `registry.json`. Next cron cycle runs it. **No code restart, no edits
to run_signals.py.**

Full walkthrough: `strategies/STRATEGIES.md`.

---

## Database connection

This agent uses the ETL agent's canonical DB pool:

```python
import sys, os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'etl', 'shared', 'scripts')))
from db import get_connection
```

That's the only cross-agent dependency. If we ever extract the DB
helper into its own shared module, both agents update one import line.

---

## Cron schedule

| Cron | Script | Purpose |
|------|--------|---------|
| Daily (after ETL gold layer completes) | `run_signal_cycle.sh` | Iterate enabled strategies, write `gold.strategy_signals` |

The ETL agent owns its own cron (`agents/etl/daily_refresh.sh`). This
agent's cron should be scheduled to fire AFTER the ETL cron completes
successfully — typically by reading `gold_layer_state.state = 'ready'`
or `'partial'` before proceeding.

---

## Operational guardrails

- **Read-only on bronze/silver**. Period.
- **No DDL changes from this agent**. Schema migrations live in `db_setup/migrations/`
  and are applied by the operator separately.
- **All strategy parameters live in `registry.json` `params` field** (forward state).
  Today most strategy classes still hardcode their own params — see
  STRATEGIES.md "What params is for" for the migration pattern.
- **Failed-strategy isolation**: one strategy raising must not stop other
  strategies' signal writes. `run_signals.py` wraps each strategy in
  `try/except`, logs, and continues. The cycle exit code reflects the
  count of failures.
