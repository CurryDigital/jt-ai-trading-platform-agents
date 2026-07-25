<!-- source: authored -->
# Natgas seasonal (signal agent #15)

| field | value |
|---|---|
| **doc_id** | `signal_agent_natgas_seasonal` |
| **agent** | signal agent (`agents/signals/strategies/`) — numeric-id space, writes `gold.strategy_signals` |
| **asset class** | commodity |
| **regime gate** | active only in `TREND` (via `gold.regime_label`) |
| **signal mechanism** | computed (BaseStrategy subclass `compute_signal()`) |
| **implementation status** | real (simple) |

## Overview
Signal-agent strategy. Its BUY logic lives in Python (a `BaseStrategy`
subclass), NOT in `gold.strategy_signal_criteria`. Gated by the regime engine:
`is_active_today()` returns False (→ signal 0) unless today's regime matches
and the strategy id is in that regime's active set.

## Universe
NG=F / UNG

## Buy-signal pipeline
Pure calendar seasonal: long (+1) during the Nov–Feb heating season (months 11,12,1,2), flat otherwise. No price input — a seasonality bet.

Result: `compute_signal()` returns +1 (long) / −1 (short) / 0 (flat); the
runner (`run_signals.py`) sizes it (1% vol target) and writes
`gold.strategy_signals(date, strategy_id, signal, position_size, regime, ...)`.

## Exit logic
Flat outside the Nov–Feb window.

## Backtest summary (OOS)
This signal-agent strategy is in the numeric-id space; its OOS stats (if any)
live under `gold.strategy_backtests` (smallint id), NOT the semantic
`gold.strategy_backtest_runs`. See OPERATOR_NOTES P0-2.

## Known issues / TODO
- Signal-agent numeric strategies write `gold.strategy_signals`, a path largely
  separate from the semantic (frontend) strategy pipeline. Confirm whether this
  strategy should be promoted into the semantic registry or remain experimental.
