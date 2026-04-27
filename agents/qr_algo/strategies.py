"""
Strategy implementations dispatched by `param_set.strategy_type`.

Each strategy function takes:
    bars_by_ticker:    Dict[str, List[Bar]]   sorted ascending by date
    param_set:         the full param_set from the experiment
    is_oos_boundary:   the cutoff date that separates IS from OOS

…and returns a list of Trade objects with `period_type` populated based on
the entry date relative to `is_oos_boundary`.

Two strategies ship in this commit (matching the most-used entries in
skills/strategy_registry.md):
  - momentum:        N-day return crosses entry_threshold → buy; opposite or time stop → sell
  - mean_reversion:  z-score of close vs N-day mean crosses -entry_threshold → buy; reverts → sell

Other types (breakout, pairs, earnings_drift, etc.) raise UnsupportedStrategyError
so qr_algo can emit workflow.stuck cleanly. Add new strategies by registering
a function in STRATEGY_REGISTRY below.
"""

from __future__ import annotations

import statistics
from datetime import date as _date
from typing import Any, Callable, Dict, List, Optional

from agents.qr_algo.backtest import (
    Bar, Trade, UnsupportedStrategyError,
    apply_round_trip_cost, label_period,
)


# ─── Momentum ───────────────────────────────────────────────────────────────

def momentum(
    bars_by_ticker: Dict[str, List[Bar]],
    param_set: Dict[str, Any],
    is_oos_boundary: _date,
) -> List[Trade]:
    """
    Per ticker, walk forward day by day. When we are flat and the trailing
    `lookback_window`-day return exceeds `entry_threshold`, enter at the next
    bar's close. Exit when the return-since-entry falls below `exit_threshold`
    OR we have held for `max_holding_days`. End-of-period flush exits any
    open position at the last available close.
    """
    lookback = int(param_set.get("lookback_window", 20))
    entry_threshold = float(param_set.get("entry_threshold", 0.05))
    exit_threshold = float(param_set.get("exit_threshold", -0.02))
    max_holding_days = int(param_set.get("max_holding_days", 30))

    trades: List[Trade] = []

    for ticker, bars in bars_by_ticker.items():
        if len(bars) < lookback + 2:
            continue

        position: Optional[Dict[str, Any]] = None

        for i in range(lookback, len(bars) - 1):
            today = bars[i]
            tomorrow = bars[i + 1]

            if position is None:
                lookback_return = (today.close / bars[i - lookback].close) - 1.0
                if lookback_return > entry_threshold:
                    position = {
                        "entry_date": tomorrow.date,
                        "entry_price": tomorrow.close,
                        "i_entry": i + 1,
                    }
                continue

            held_days = i + 1 - position["i_entry"]
            return_since_entry = (today.close / position["entry_price"]) - 1.0
            time_stop_hit = held_days >= max_holding_days
            signal_exit = return_since_entry < exit_threshold

            if signal_exit or time_stop_hit:
                exit_reason = "time_stop" if time_stop_hit and not signal_exit else "signal"
                trades.append(_close(
                    ticker, position, tomorrow, exit_reason, is_oos_boundary
                ))
                position = None

        if position is not None:
            last = bars[-1]
            trades.append(_close(ticker, position, last, "eod", is_oos_boundary))

    return trades


# ─── Mean reversion ────────────────────────────────────────────────────────

def mean_reversion(
    bars_by_ticker: Dict[str, List[Bar]],
    param_set: Dict[str, Any],
    is_oos_boundary: _date,
) -> List[Trade]:
    """
    Per ticker, walk forward and compute a rolling z-score against the trailing
    `lookback_window` closes. Enter long at next bar's close when z drops below
    -entry_threshold (oversold). Exit when z rises back above exit_threshold
    (mean reverted) OR we have held for `max_holding_days`.
    """
    lookback = int(param_set.get("lookback_window", 20))
    entry_threshold = float(param_set.get("entry_threshold", 2.0))
    exit_threshold = float(param_set.get("exit_threshold", 0.0))
    max_holding_days = int(param_set.get("max_holding_days", 20))

    trades: List[Trade] = []

    for ticker, bars in bars_by_ticker.items():
        if len(bars) < lookback + 2:
            continue

        position: Optional[Dict[str, Any]] = None

        for i in range(lookback, len(bars) - 1):
            today = bars[i]
            tomorrow = bars[i + 1]

            window = [b.close for b in bars[i - lookback : i]]
            mean = statistics.fmean(window)
            sd = statistics.pstdev(window)
            if sd == 0:
                continue
            z = (today.close - mean) / sd

            if position is None:
                if z < -entry_threshold:
                    position = {
                        "entry_date": tomorrow.date,
                        "entry_price": tomorrow.close,
                        "i_entry": i + 1,
                    }
                continue

            held_days = i + 1 - position["i_entry"]
            time_stop_hit = held_days >= max_holding_days
            signal_exit = z > exit_threshold

            if signal_exit or time_stop_hit:
                exit_reason = "time_stop" if time_stop_hit and not signal_exit else "signal"
                trades.append(_close(
                    ticker, position, tomorrow, exit_reason, is_oos_boundary
                ))
                position = None

        if position is not None:
            last = bars[-1]
            trades.append(_close(ticker, position, last, "eod", is_oos_boundary))

    return trades


# ─── Dispatch ───────────────────────────────────────────────────────────────

StrategyFn = Callable[[Dict[str, List[Bar]], Dict[str, Any], _date], List[Trade]]

STRATEGY_REGISTRY: Dict[str, StrategyFn] = {
    "momentum":       momentum,
    "mean_reversion": mean_reversion,
}


def run_strategy(
    strategy_type: str,
    bars_by_ticker: Dict[str, List[Bar]],
    param_set: Dict[str, Any],
    is_oos_boundary: _date,
) -> List[Trade]:
    fn = STRATEGY_REGISTRY.get(strategy_type)
    if fn is None:
        raise UnsupportedStrategyError(
            f"strategy_type={strategy_type!r} not implemented in qr_algo. "
            f"Supported: {sorted(STRATEGY_REGISTRY)}"
        )
    return fn(bars_by_ticker, param_set, is_oos_boundary)


# ─── Helpers ───────────────────────────────────────────────────────────────

def _close(
    ticker: str,
    position: Dict[str, Any],
    exit_bar: Bar,
    reason: str,
    is_oos_boundary: _date,
) -> Trade:
    gross_pnl = (exit_bar.close / position["entry_price"]) - 1.0
    holding = (exit_bar.date - position["entry_date"]).days
    return Trade(
        ticker=ticker,
        period_type=label_period(position["entry_date"], is_oos_boundary),
        entry_date=position["entry_date"],
        exit_date=exit_bar.date,
        entry_price=float(position["entry_price"]),
        exit_price=float(exit_bar.close),
        pnl_pct=apply_round_trip_cost(gross_pnl),
        holding_days=float(max(holding, 1)),
        exit_reason=reason,
    )
