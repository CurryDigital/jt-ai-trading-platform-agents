# agents/signals/ — Signal Generation

The strategy framework and daily signal runner.
Split out from `agents/etl/` on 2026-06-22.

```
agents/etl/      ← ETL pipeline:  bronze → silver → gold  (DB ingestion)
agents/signals/  ← THIS:          gold → gold.strategy_signals  (signal generation)
```

## Quickstart

```bash
cd agents/signals

# Validate the registry (no DB)
python3 -c "from strategies.registry_loader import load_registry; load_registry()"

# Run the unit tests (no DB, no network)
python3 tests/test_registry_loader.py

# Run today's signals (needs DB + gold.regime_label populated)
bash run_signal_cycle.sh

# Add a new strategy (no edits to run_signals.py needed)
python3 strategies/register_strategy.py --help
```

## Files

| Path | What it does |
|---|---|
| `AGENT.md` | Charter — ownership, deps, cron contract |
| `run_signal_cycle.sh` | Cron entry point |
| `strategies/registry.json` | Single source of truth for strategy onboarding |
| `strategies/registry_loader.py` | Validating loader (stdlib only) |
| `strategies/base_strategy.py` | BaseStrategy: regime gate + position sizer + save() |
| `strategies/run_signals.py` | Iterates enabled strategies, writes signals |
| `strategies/register_strategy.py` | CLI for new strategies |
| `strategies/STRATEGIES.md` | Onboarding doc |
| `strategies/stubs.py` | Disabled stub classes (kept so historic IDs are reserved) |
| `strategies/trend/strategy_NN.py` | Real strategy implementations |
| `regime/regime_rules.py` | `assign_regime()` + `STRATEGY_MAP` (derived from registry) |
| `regime/train_hmm.py` | HMM training (offline) |
| `tests/test_registry_loader.py` | 10 unit tests for the loader |
| `tests/test_regime.py` | Regime engine integration tests (needs DB) |

## What this agent does NOT do

- Does not ingest bronze data (see `agents/etl/bronze/`).
- Does not clean silver (see `agents/etl/silver/`).
- Does not build gold KPIs (see `agents/etl/gold/`).
- Does not modify schema (see `db_setup/migrations/`).
- Reads-only from gold; writes only to `gold.strategy_signals`.
