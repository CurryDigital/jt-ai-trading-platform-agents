"""
Strategy implementations dispatched by `param_set.strategy_type`.

Each strategy function takes:
    bars_by_ticker:    Dict[str, List[Bar]]   sorted ascending by date
    param_set:         the full param_set from the experiment
    is_oos_boundary:   the cutoff date that separates IS from OOS

…and returns a list of Trade objects with `period_type` populated based on
the entry date relative to `is_oos_boundary`.

Six strategies are implemented as generic, asset-class-agnostic primitives.
The asset class is selected by `param_set.data_source` (equities by default
— see DEFAULT_DATA_SOURCE / ALLOWED_DATA_SOURCES in backtest.py); the same
strategy code runs against equities, crypto, FX, commodities once those
gold-layer tables exist.

  - momentum         — trend-following on a single asset
  - mean_reversion   — z-score reversion on a single asset
  - breakout         — N-day high break with optional volume confirmation
  - pairs            — z-score on the spread of exactly two assets
  - cross_sectional  — rank by trailing return, hold top/bottom quantile
  - seasonal         — calendar window (configurable start/end month-day)

Anything not in STRATEGY_REGISTRY raises UnsupportedStrategyError so qr_algo
emits workflow.stuck cleanly. Add new strategies by writing a function and
registering it at the bottom — no other code changes required.
"""

from __future__ import annotations

import statistics
from datetime import date as _date
from typing import Any, Callable, Dict, List, Optional, Tuple

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


# ─── Breakout ──────────────────────────────────────────────────────────────

def breakout(
    bars_by_ticker: Dict[str, List[Bar]],
    param_set: Dict[str, Any],
    is_oos_boundary: _date,
) -> List[Trade]:
    """
    N-day high breakout with optional volume confirmation. Per ticker, walk
    forward; when today's close exceeds the rolling N-day high (and volume,
    if available, exceeds avg_volume * volume_multiplier), enter at next bar's
    close. Exit on a trailing stop (price drops `trailing_stop_pct` from the
    peak since entry) OR after `max_holding_days`.

    Parameters (with defaults — never hardcoded):
        lookback_window      (default 20)   — rolling window for the high
        volume_multiplier    (default 1.0)  — set > 1.0 to require volume confirm;
                                              ignored if volume column is None
        trailing_stop_pct    (default 0.10) — exit if peak-since-entry drops this %
        max_holding_days     (default 30)   — time stop
    """
    lookback = int(param_set.get("lookback_window", 20))
    vol_mult = float(param_set.get("volume_multiplier", 1.0))
    trailing_stop_pct = float(param_set.get("trailing_stop_pct", 0.10))
    max_holding_days = int(param_set.get("max_holding_days", 30))

    trades: List[Trade] = []

    for ticker, bars in bars_by_ticker.items():
        if len(bars) < lookback + 2:
            continue

        position: Optional[Dict[str, Any]] = None

        for i in range(lookback, len(bars) - 1):
            today = bars[i]
            tomorrow = bars[i + 1]
            window = bars[i - lookback : i]
            window_high = max(b.close for b in window)

            if position is None:
                if today.close <= window_high:
                    continue
                if vol_mult > 1.0 and today.volume is not None:
                    avg_vol = statistics.fmean(
                        b.volume for b in window if b.volume is not None
                    ) if any(b.volume is not None for b in window) else None
                    if avg_vol is None or today.volume < avg_vol * vol_mult:
                        continue
                position = {
                    "entry_date": tomorrow.date,
                    "entry_price": tomorrow.close,
                    "i_entry": i + 1,
                    "peak_close": tomorrow.close,
                }
                continue

            position["peak_close"] = max(position["peak_close"], today.close)
            held_days = i + 1 - position["i_entry"]
            drawdown_from_peak = (today.close / position["peak_close"]) - 1.0
            time_stop_hit = held_days >= max_holding_days
            trailing_hit = drawdown_from_peak <= -trailing_stop_pct

            if trailing_hit or time_stop_hit:
                reason = "time_stop" if time_stop_hit and not trailing_hit else "trailing_stop"
                trades.append(_close(ticker, position, tomorrow, reason, is_oos_boundary))
                position = None

        if position is not None:
            trades.append(_close(ticker, position, bars[-1], "eod", is_oos_boundary))

    return trades


# ─── Pairs ─────────────────────────────────────────────────────────────────

def pairs(
    bars_by_ticker: Dict[str, List[Bar]],
    param_set: Dict[str, Any],
    is_oos_boundary: _date,
) -> List[Trade]:
    """
    Spread z-score on exactly two assets. Compute spread = price_A - hedge_ratio*price_B,
    z-score it over `lookback_window`, and trade convergence:
      z < -entry_threshold → long spread (long A, short B)
      z > +entry_threshold → short spread (short A, long B)
      |z| < exit_threshold → close both legs

    For the trade ledger, each leg is recorded as a separate Trade row tagged
    with the same period_type. Pnl is computed long-only-equivalent: long-A
    leg uses (exit_a / entry_a - 1); short-B leg uses -(exit_b / entry_b - 1)
    (i.e. profit when B falls). Round-trip cost is applied per leg.

    Parameters (defaults — no hardcoding):
        lookback_window  (default 60)
        entry_threshold  (default 2.0)  — |z| > this → enter
        exit_threshold   (default 0.5)  — |z| < this → exit
        hedge_ratio      (default 1.0)  — multiplier on asset_B in the spread
        max_holding_days (default 30)
    """
    asset_universe = list(param_set.get("asset_universe", []))
    if len(asset_universe) != 2:
        raise UnsupportedStrategyError(
            f"pairs strategy requires exactly 2 tickers, got {len(asset_universe)}: {asset_universe}"
        )

    a_ticker, b_ticker = asset_universe
    bars_a = bars_by_ticker.get(a_ticker, [])
    bars_b = bars_by_ticker.get(b_ticker, [])
    if not bars_a or not bars_b:
        return []

    aligned = _align_two_series(bars_a, bars_b)
    if not aligned:
        return []

    lookback = int(param_set.get("lookback_window", 60))
    entry_threshold = float(param_set.get("entry_threshold", 2.0))
    exit_threshold = float(param_set.get("exit_threshold", 0.5))
    hedge_ratio = float(param_set.get("hedge_ratio", 1.0))
    max_holding_days = int(param_set.get("max_holding_days", 30))

    if len(aligned) < lookback + 2:
        return []

    trades: List[Trade] = []
    position: Optional[Dict[str, Any]] = None

    for i in range(lookback, len(aligned) - 1):
        today_a, today_b = aligned[i]
        tomorrow_a, tomorrow_b = aligned[i + 1]

        spread_window = [
            a.close - hedge_ratio * b.close
            for (a, b) in aligned[i - lookback : i]
        ]
        mean = statistics.fmean(spread_window)
        sd = statistics.pstdev(spread_window)
        if sd == 0:
            continue
        spread_today = today_a.close - hedge_ratio * today_b.close
        z = (spread_today - mean) / sd

        if position is None:
            if abs(z) > entry_threshold:
                # z<0 → spread is below mean, expect to widen up: long A, short B
                # z>0 → spread is above mean, expect to narrow: short A, long B
                direction = -1 if z < 0 else 1   # +1 = short A / long B; -1 = long A / short B
                position = {
                    "entry_date": tomorrow_a.date,
                    "entry_a": tomorrow_a.close,
                    "entry_b": tomorrow_b.close,
                    "i_entry": i + 1,
                    "direction": direction,
                }
            continue

        held_days = i + 1 - position["i_entry"]
        if abs(z) < exit_threshold or held_days >= max_holding_days:
            reason = "signal" if abs(z) < exit_threshold else "time_stop"
            trades.extend(_close_pair(
                a_ticker, b_ticker, position, tomorrow_a, tomorrow_b, reason, is_oos_boundary
            ))
            position = None

    if position is not None:
        last_a, last_b = aligned[-1]
        trades.extend(_close_pair(
            a_ticker, b_ticker, position, last_a, last_b, "eod", is_oos_boundary
        ))

    return trades


# ─── Cross-sectional rank ───────────────────────────────────────────────────

def cross_sectional(
    bars_by_ticker: Dict[str, List[Bar]],
    param_set: Dict[str, Any],
    is_oos_boundary: _date,
) -> List[Trade]:
    """
    Rank-based portfolio strategy. Every `rebalance_days`, rank every ticker
    in the universe by its trailing `lookback_window`-day return, then hold
    the top quantile (default 20%). Direction='long_top' is momentum;
    direction='long_bottom' is value/contrarian. Position is closed and
    re-opened at every rebalance.

    Parameters (defaults — no hardcoding):
        lookback_window  (default 60)        — ranking metric: trailing return
        quantile         (default 0.20)      — fraction of universe held
        rebalance_days   (default 21)        — calendar/trading days between rebalances
        direction        (default 'long_top') — 'long_top' | 'long_bottom'
    """
    lookback = int(param_set.get("lookback_window", 60))
    quantile = float(param_set.get("quantile", 0.20))
    rebalance_days = int(param_set.get("rebalance_days", 21))
    direction = str(param_set.get("direction", "long_top"))
    if direction not in ("long_top", "long_bottom"):
        raise UnsupportedStrategyError(
            f"cross_sectional direction must be 'long_top' or 'long_bottom', got {direction!r}"
        )

    common_dates = _common_dates(bars_by_ticker)
    if len(common_dates) < lookback + rebalance_days + 1:
        return []

    # Build a per-ticker price-by-date lookup for O(1) reads at rebalance.
    by_ticker_by_date: Dict[str, Dict[_date, Bar]] = {
        t: {b.date: b for b in bars} for t, bars in bars_by_ticker.items()
    }

    trades: List[Trade] = []
    holdings: Dict[str, Dict[str, Any]] = {}  # ticker → {entry_date, entry_price, i_entry}
    n_universe = len(bars_by_ticker)
    n_top = max(1, int(n_universe * quantile))

    for i in range(lookback, len(common_dates) - 1, rebalance_days):
        today = common_dates[i]
        # close existing positions at today's close
        for t, h in list(holdings.items()):
            exit_bar = by_ticker_by_date[t].get(today)
            if exit_bar is None:
                continue
            trades.append(_close(t, h, exit_bar, "rebalance", is_oos_boundary))
            del holdings[t]

        # rank by trailing return
        ranks: List[Tuple[str, float]] = []
        for ticker, bars in bars_by_ticker.items():
            past = by_ticker_by_date[ticker].get(common_dates[i - lookback])
            now = by_ticker_by_date[ticker].get(today)
            if past is None or now is None or past.close == 0:
                continue
            ranks.append((ticker, (now.close / past.close) - 1.0))
        if not ranks:
            continue
        ranks.sort(key=lambda x: x[1], reverse=(direction == "long_top"))
        winners = [t for t, _ in ranks[:n_top]]

        # open new positions at the next bar's close (no look-ahead)
        if i + 1 >= len(common_dates):
            break
        entry_day = common_dates[i + 1]
        for t in winners:
            entry_bar = by_ticker_by_date[t].get(entry_day)
            if entry_bar is None:
                continue
            holdings[t] = {
                "entry_date": entry_day,
                "entry_price": entry_bar.close,
                "i_entry": i + 1,
            }

    # End-of-period flush
    last_day = common_dates[-1]
    for t, h in holdings.items():
        exit_bar = by_ticker_by_date[t].get(last_day)
        if exit_bar is None:
            continue
        trades.append(_close(t, h, exit_bar, "eod", is_oos_boundary))

    return trades


# ─── Seasonal ──────────────────────────────────────────────────────────────

def seasonal(
    bars_by_ticker: Dict[str, List[Bar]],
    param_set: Dict[str, Any],
    is_oos_boundary: _date,
) -> List[Trade]:
    """
    Hold every asset in the universe between (start_month, start_day) and
    (end_month, end_day) of each year. The window may wrap year-end
    (e.g. Nov 1 → Apr 30 = "winter rally"). One trade per ticker per year.

    Parameters (no defaults that imply a specific season — caller must specify):
        start_month  (1..12)
        start_day    (1..31)
        end_month    (1..12)
        end_day      (1..31)
    """
    try:
        start_m = int(param_set["start_month"])
        start_d = int(param_set["start_day"])
        end_m = int(param_set["end_month"])
        end_d = int(param_set["end_day"])
    except (KeyError, ValueError, TypeError) as e:
        raise UnsupportedStrategyError(
            f"seasonal requires start_month, start_day, end_month, end_day in param_set; got error: {e}"
        )

    trades: List[Trade] = []

    for ticker, bars in bars_by_ticker.items():
        if not bars:
            continue
        position: Optional[Dict[str, Any]] = None
        for i in range(len(bars) - 1):
            today = bars[i]
            tomorrow = bars[i + 1]
            in_window = _date_in_window(today.date, start_m, start_d, end_m, end_d)
            in_window_tomorrow = _date_in_window(tomorrow.date, start_m, start_d, end_m, end_d)

            if position is None and not in_window and in_window_tomorrow:
                position = {
                    "entry_date": tomorrow.date,
                    "entry_price": tomorrow.close,
                    "i_entry": i + 1,
                }
                continue

            if position is not None and in_window and not in_window_tomorrow:
                trades.append(_close(ticker, position, tomorrow, "seasonal_exit", is_oos_boundary))
                position = None

        if position is not None:
            trades.append(_close(ticker, position, bars[-1], "eod", is_oos_boundary))

    return trades


# ─── Dispatch ───────────────────────────────────────────────────────────────

StrategyFn = Callable[[Dict[str, List[Bar]], Dict[str, Any], _date], List[Trade]]

STRATEGY_REGISTRY: Dict[str, StrategyFn] = {
    "momentum":        momentum,
    "mean_reversion":  mean_reversion,
    "breakout":        breakout,
    "pairs":           pairs,
    "cross_sectional": cross_sectional,
    "seasonal":        seasonal,
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


def _align_two_series(bars_a: List[Bar], bars_b: List[Bar]) -> List[Tuple[Bar, Bar]]:
    """Inner-join two bar series on date (ascending)."""
    by_date_b = {b.date: b for b in bars_b}
    return [(a, by_date_b[a.date]) for a in bars_a if a.date in by_date_b]


def _close_pair(
    a_ticker: str,
    b_ticker: str,
    position: Dict[str, Any],
    exit_a: Bar,
    exit_b: Bar,
    reason: str,
    is_oos_boundary: _date,
) -> List[Trade]:
    """
    Close a pair position. direction=-1 → long A / short B; direction=+1 → short A / long B.
    Each leg is one row in the trade ledger so qr_qa Gate 0 still ties out.
    """
    direction = position["direction"]
    period = label_period(position["entry_date"], is_oos_boundary)
    holding = max(1, (exit_a.date - position["entry_date"]).days)

    # Long-A / Short-B if direction = -1; signs flip otherwise.
    a_pnl_long_eq = (exit_a.close / position["entry_a"]) - 1.0
    b_pnl_long_eq = (exit_b.close / position["entry_b"]) - 1.0
    if direction == -1:
        a_pnl, b_pnl = a_pnl_long_eq, -b_pnl_long_eq
    else:
        a_pnl, b_pnl = -a_pnl_long_eq, b_pnl_long_eq

    return [
        Trade(
            ticker=a_ticker,
            period_type=period,
            entry_date=position["entry_date"],
            exit_date=exit_a.date,
            entry_price=float(position["entry_a"]),
            exit_price=float(exit_a.close),
            pnl_pct=apply_round_trip_cost(a_pnl),
            holding_days=float(holding),
            exit_reason=reason,
        ),
        Trade(
            ticker=b_ticker,
            period_type=period,
            entry_date=position["entry_date"],
            exit_date=exit_b.date,
            entry_price=float(position["entry_b"]),
            exit_price=float(exit_b.close),
            pnl_pct=apply_round_trip_cost(b_pnl),
            holding_days=float(holding),
            exit_reason=reason,
        ),
    ]


def _common_dates(bars_by_ticker: Dict[str, List[Bar]]) -> List[_date]:
    """Sorted intersection of dates that exist in every ticker's series."""
    if not bars_by_ticker:
        return []
    sets = [set(b.date for b in bars) for bars in bars_by_ticker.values()]
    common = set.intersection(*sets) if sets else set()
    return sorted(common)


def _date_in_window(d: _date, start_m: int, start_d: int, end_m: int, end_d: int) -> bool:
    """True if `d`'s (month, day) is inside [start, end] inclusive. Handles year-wrap."""
    md = (d.month, d.day)
    start = (start_m, start_d)
    end = (end_m, end_d)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end
