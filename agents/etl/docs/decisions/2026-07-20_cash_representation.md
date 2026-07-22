# Decision: Canonical representation of CASH in ticker-level ETL tables

**Date:** 2026-07-20  
**Context:** `qr_etl` task t_dc6a67b7  
**Decision owner:** ETL Manager

## Problem
Several paper strategies (e.g. `US_STK_GOLD_HDG_05`, `US_STK_VAL_REV_03`) move to 100% cash. Their live signal JSON files and downstream logs contain a ticker named `CASH`. This placeholder was being written into ticker-level tables, producing inconsistent rows:

- `gold.trade_executions`
- `consumption.strategies_signals_current`
- `gold.paper_trades_synthetic`
- `consumption.signal_logs`
- `gold.strategy_ticker_scores`

## Decision
**Option (a) is canonical:** CASH is a portfolio cash-bucket placeholder, *not* a tradeable ticker. It is **not** represented as a row in ticker-level trade or signal tables. A 100% cash position is represented implicitly by the **absence of security positions** for that strategy on that date.

Rejected alternatives:
- **(b) Keep `CASH` rows with synthetic price 1.0** — pollutes ticker-level metrics, breaks price-based joins, and confuses downstream consumers.
- **(c) Rename to `CASH.X` or `USD.CASH`** — still treats cash as a security, with the same join/metric issues.
- **(d) Move to a separate `cash_allocations` table** — useful for capital tracking but out of scope for this ticket; can be added later if needed.

## Implementation
1. **Ingestion filters** now drop `CASH` before writing to ticker-level tables:
   - `etl/backfill_strategy_live_data.py` skips `CASH` in synthetic trade generation and `strategies_signals_current` refresh.
   - `etl/gold/strategy/refresh_paper_trades_synthetic.py` (canonical) filters `CASH` in closed/open trade queries.
   - `etl/consumption/command/command_signal_logs.py` filters `CASH` when selecting from `gold.strategy_ticker_scores`.
2. **Historical cleanup** ran by `workspace/oneoff/remediate_cash_ticker_rows.py`, deleting all `ticker = 'CASH'` rows from the affected tables.
3. **Deployment wrapper** at `~/.hermes/profiles/qr_etl/scripts/refresh_paper_trades_synthetic.py` now delegates to the canonical workspace implementation.

## Downstream impact
- `qr_frontend` consumers querying these tables will no longer see `CASH` rows.
- Strategies that are 100% cash will simply have zero ticker rows for the current/historical period, which is the intended representation.
- Any frontend code that special-cased `ticker = 'CASH'` can be removed.

## Verification
- Post-cleanup row counts verified by `remediate_cash_ticker_rows.py` output.
- `refresh_paper_trades_synthetic.py` and `backfill_strategy_live_data.py` re-run without re-inserting `CASH` rows.
- Spot checks confirm no `CASH` rows remain in `gold.trade_executions` or `consumption.strategies_signals_current`.
