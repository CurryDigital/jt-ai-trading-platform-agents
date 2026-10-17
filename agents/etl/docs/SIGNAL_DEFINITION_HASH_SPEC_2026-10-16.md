# SPEC — Signal-definition hash for backtests, live sleeves, and promotion

Date: 2026-10-16
Owner: qr_etl (spec only; no code changes in this artifact)

## Problem

Backtest evidence and live sleeve behavior can drift apart when a strategy's
signal definition changes (criteria, universe rules, parameters, engine code,
or data inputs). Promotion evidence generated under definition A must not be
used to promote definition B.

## Rule

Every backtest run and every live sleeve carries a `signal_definition_hash`.
The promotion gate compares hashes exactly. A mismatch blocks promotion with
reason `SIGNAL_DEFINITION_MISMATCH`.

## Hash inputs (canonical order)

Build a canonical JSON document with sorted keys and no whitespace-dependent
formatting, then SHA-256 it. Include:

- `strategy_id`
- `signal_mechanism` (`computed` / `ingested` / etc.)
- `engine`: name + version + code sha256 when computable
- `params`: strategy configs relevant to signal generation (canonical JSON)
- `universe_rule`: explicit ticker list hash or universe-builder rule hash
- `criteria`: signal criteria / thresholds (canonical JSON)
- `fill_convention` and rebalance cadence
- `data_dependencies`: required gold/silver tables + minimum data tags
  (e.g. `gold_data_tag=gapfix_v1_20261014` when applicable)

Exclude: timestamps, run ids, row counts, computed scores, and anything produced
by evaluating the signals.

## Storage (proposed; migration later)

- `gold.strategy_backtest_runs.signal_definition_hash text NULL`
- `gold.strategy_registry.signal_definition_hash text NULL` (current live definition)
- `gold.strategy_signal_definition_history` (append-only):
  `strategy_id, signal_definition_hash, definition_json jsonb, valid_from,
   recorded_at, recorded_by, source`
- Promotion/gate tables store both sides:
  `backtest_signal_definition_hash`, `live_signal_definition_hash`, and a
  boolean `signal_definition_match`.

## Promotion comparison

Promotion is valid only when:

```
backtest_signal_definition_hash = live_signal_definition_hash
```

If either side is NULL, promotion is `needs_input` (legacy unrunnable state),
not pass.

## Operational notes

- Hash writers must log the canonical definition JSON to
  `gold.strategy_signal_definition_history` before/with the hash write.
- Any intentional signal-definition change requires a new hash, fresh backtest
  evidence under that hash, and an explicit promotion review.
- This spec does not change current promotion behavior by itself; it defines
  the contract for the migration and gate change.
