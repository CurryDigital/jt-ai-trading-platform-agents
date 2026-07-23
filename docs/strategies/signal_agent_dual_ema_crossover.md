<!-- source: authored -->
# Dual EMA crossover (signal agent #1)

| field | value |
|---|---|
| **doc_id** | `signal_agent_dual_ema_crossover` |
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
SPY, QQQ, IWM, GLD, TLT

## Buy-signal pipeline
For each basket ETF: EMA10 and EMA50 (adjust=False) of close; delta = (EMA10−EMA50)/close, inverse-vol weighted (1/σ20). Net long signal (+1) when the vol-weighted mean delta clears the long threshold (params: ema_fast=10, ema_slow=50, delta_long_threshold=0.001). Reads gold.daily_ohlcv.

Result: `compute_signal()` returns +1 (long) / −1 (short) / 0 (flat); the
runner (`run_signals.py`) sizes it (1% vol target) and writes
`gold.strategy_signals(date, strategy_id, signal, position_size, regime, ...)`.

## Exit logic
Signal flips to 0/short when the weighted delta falls below delta_short_threshold (−0.001).

## Backtest summary (OOS)
This signal-agent strategy is in the numeric-id space; its OOS stats (if any)
live under `gold.strategy_backtests` (smallint id), NOT the semantic
`gold.strategy_backtest_runs`. See OPERATOR_NOTES P0-2.

## Known issues / TODO
- Signal-agent numeric strategies write `gold.strategy_signals`, a path largely
  separate from the semantic (frontend) strategy pipeline. Confirm whether this
  strategy should be promoted into the semantic registry or remain experimental.
