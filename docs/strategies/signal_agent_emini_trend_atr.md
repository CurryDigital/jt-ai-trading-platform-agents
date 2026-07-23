<!-- source: authored -->
# E-mini S&P trend + ATR (signal agent #11)

| field | value |
|---|---|
| **doc_id** | `signal_agent_emini_trend_atr` |
| **agent** | signal agent (`agents/signals/strategies/`) — numeric-id space, writes `gold.strategy_signals` |
| **asset class** | equity |
| **regime gate** | active only in `TREND` (via `gold.regime_label`) |
| **signal mechanism** | computed (BaseStrategy subclass `compute_signal()`) |
| **implementation status** | real |

## Overview
Signal-agent strategy. Its BUY logic lives in Python (a `BaseStrategy`
subclass), NOT in `gold.strategy_signal_criteria`. Gated by the regime engine:
`is_active_today()` returns False (→ signal 0) unless today's regime matches
and the strategy id is in that regime's active set.

## Universe
ES / SPY proxy

## Buy-signal pipeline
Needs ≥50 rows; trend-following long with an ATR-based filter/stop. See strategy_11.py for the exact trend + ATR rule.

Result: `compute_signal()` returns +1 (long) / −1 (short) / 0 (flat); the
runner (`run_signals.py`) sizes it (1% vol target) and writes
`gold.strategy_signals(date, strategy_id, signal, position_size, regime, ...)`.

## Exit logic
ATR-based trailing stop.

## Backtest summary (OOS)
This signal-agent strategy is in the numeric-id space; its OOS stats (if any)
live under `gold.strategy_backtests` (smallint id), NOT the semantic
`gold.strategy_backtest_runs`. See OPERATOR_NOTES P0-2.

## Known issues / TODO
- Signal-agent numeric strategies write `gold.strategy_signals`, a path largely
  separate from the semantic (frontend) strategy pipeline. Confirm whether this
  strategy should be promoted into the semantic registry or remain experimental.
