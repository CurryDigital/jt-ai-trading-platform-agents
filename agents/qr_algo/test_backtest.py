"""
Unit tests for the qr_algo backtest engine.

Pure stdlib — no DB connection, no network. Synthesises price series and
verifies the contract documented in agents/qr_algo/AGENTS.md:

  1. Trade-ledger / metrics integrity (Gate 0 anti-hallucination invariant):
     metrics.trade_count_is + metrics.trade_count_oos == len(trades)
  2. IS/OOS split honours BACKTEST_IS_OOS_SPLIT (70/30).
  3. Drawdown is stored as a NEGATIVE decimal.
  4. Sharpe formula matches the documented annualisation.
  5. Transaction cost is applied per side (round-trip = 2 * TRANSACTION_COST_PCT).
  6. Unsupported strategy_type raises UnsupportedStrategyError so the agent
     can emit workflow.stuck cleanly.
  7. Empty / no-data input does not crash; returns 'no_data' status.

Run: `python3 -m pytest agents/qr_algo/test_backtest.py -v` or just
`python3 agents/qr_algo/test_backtest.py` (a tiny built-in runner is provided).
"""

from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from typing import Dict, List

# Make `from agents.shared.constants import ...` work when run directly.
import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.qr_algo import backtest as bt
from agents.qr_algo.backtest import (
    Bar, Trade,
    UnsupportedStrategyError, InsufficientDataError,
    apply_round_trip_cost, annualised_sharpe, max_drawdown, cvar,
    split_trading_days, label_period, compute_metrics,
)
from agents.qr_algo.strategies import run_strategy
from agents.shared.constants import (
    BACKTEST_IS_OOS_SPLIT, TRANSACTION_COST_PCT, ANNUALISATION_FACTOR, RISK_FREE_RATE,
)


# ─── Synthetic price helpers ────────────────────────────────────────────────

def linear_uptrend_bars(start_close: float, days: int, daily_step: float = 1.0) -> List[Bar]:
    """Strictly monotonically increasing series — momentum should fire."""
    return [
        Bar(date=date(2026, 1, 1) + timedelta(days=i), close=start_close + i * daily_step)
        for i in range(days)
    ]


def oscillating_bars(centre: float, days: int, amplitude: float = 5.0) -> List[Bar]:
    """Sinusoidal series around `centre` — mean-reversion should fire repeatedly."""
    return [
        Bar(date=date(2026, 1, 1) + timedelta(days=i),
            close=centre + amplitude * math.sin(2 * math.pi * i / 20))
        for i in range(days)
    ]


# ─── Pure-math helpers ─────────────────────────────────────────────────────

def test_apply_round_trip_cost_is_per_side():
    # 5 bps per side → 10 bps round trip.
    assert math.isclose(
        apply_round_trip_cost(0.10),
        0.10 - 2 * TRANSACTION_COST_PCT,
        rel_tol=1e-9,
    )


def test_max_drawdown_is_negative_or_zero():
    # Monotonically up → no drawdown.
    assert max_drawdown([0.01] * 10) == 0.0
    # Big single loss → drawdown is the loss itself, negative.
    dd = max_drawdown([0.05, -0.20, 0.01])
    assert dd < 0
    assert math.isclose(dd, (1.05 * 0.80) / 1.05 - 1.0, rel_tol=1e-9)


def test_sharpe_annualisation_matches_contract():
    # Constant tiny daily returns: stddev==0 → guarded to 0.0.
    assert annualised_sharpe([0.001] * 100) == 0.0
    # Mixed returns: verify the formula (mean - rf/252) / std * sqrt(252).
    daily = [0.001, -0.002, 0.0015, -0.0005, 0.003] * 20
    expected = ((sum(daily) / len(daily)) - RISK_FREE_RATE / ANNUALISATION_FACTOR) \
        / (sum((x - sum(daily)/len(daily))**2 for x in daily) / len(daily))**0.5 \
        * math.sqrt(ANNUALISATION_FACTOR)
    assert math.isclose(annualised_sharpe(daily), expected, rel_tol=1e-9)


def test_cvar_is_negative_in_a_losing_tail():
    # Mostly small positives, two big negatives → CVaR(5%) hits the tail.
    series = [0.001] * 95 + [-0.05, -0.07, -0.06, -0.10, -0.08]
    assert cvar(series) < 0


# ─── IS/OOS split ──────────────────────────────────────────────────────────

def test_split_trading_days_70_30():
    bars_by_ticker: Dict[str, List[Bar]] = {
        "AAPL": linear_uptrend_bars(100, 100),
    }
    boundary = split_trading_days(bars_by_ticker, BACKTEST_IS_OOS_SPLIT)
    is_days = [d for d in (b.date for b in bars_by_ticker["AAPL"]) if d <= boundary]
    oos_days = [d for d in (b.date for b in bars_by_ticker["AAPL"]) if d > boundary]
    # 70% IS, 30% OOS (within ±1 from int truncation).
    assert abs(len(is_days) - 70) <= 1
    assert abs(len(oos_days) - 30) <= 1
    assert len(is_days) + len(oos_days) == 100


def test_label_period_assigns_correctly():
    boundary = date(2026, 6, 30)
    assert label_period(date(2026, 1, 1), boundary) == "IS"
    assert label_period(date(2026, 6, 30), boundary) == "IS"   # boundary inclusive on IS side
    assert label_period(date(2026, 7, 1), boundary) == "OOS"


# ─── Strategy dispatch + Trade generation ──────────────────────────────────

def test_unsupported_strategy_raises_clean_exception():
    bars = {"AAPL": linear_uptrend_bars(100, 60)}
    boundary = split_trading_days(bars)
    try:
        run_strategy("nonexistent_alpha", bars, {}, boundary)
    except UnsupportedStrategyError as e:
        assert "nonexistent_alpha" in str(e)
        assert "momentum" in str(e)  # registry list surfaced for the operator
        return
    raise AssertionError("expected UnsupportedStrategyError")


def test_momentum_fires_on_persistent_uptrend():
    bars = {"UPONLY": linear_uptrend_bars(100, 80, daily_step=2.0)}
    boundary = split_trading_days(bars)
    trades = run_strategy(
        "momentum", bars,
        {"lookback_window": 5, "entry_threshold": 0.05, "exit_threshold": -0.10,
         "max_holding_days": 10},
        boundary,
    )
    assert trades, "expected at least one momentum trade on a strict uptrend"
    for t in trades:
        # Round-trip cost is applied — gross would be > pnl_pct.
        gross = (t.exit_price / t.entry_price) - 1.0
        assert math.isclose(t.pnl_pct, gross - 2 * TRANSACTION_COST_PCT, rel_tol=1e-9)
        assert t.period_type in ("IS", "OOS")


def test_mean_reversion_fires_on_oscillation():
    bars = {"OSC": oscillating_bars(100, 200, amplitude=10.0)}
    boundary = split_trading_days(bars)
    # Z-score on a 20-day-period sine wave with amplitude=10 peaks around ±1.4
    # against its rolling stddev (≈ 10/√2). entry_threshold=1.0 is well within
    # range so the strategy fires repeatedly.
    trades = run_strategy(
        "mean_reversion", bars,
        {"lookback_window": 20, "entry_threshold": 1.0, "exit_threshold": 0.0,
         "max_holding_days": 15},
        boundary,
    )
    assert trades, "expected mean-reversion trades on a sinusoidal series"
    # Some trades should land in IS and some in OOS over a 200-day window.
    assert any(t.period_type == "IS" for t in trades)


# ─── End-to-end: ledger / metrics consistency (Gate 0 invariant) ───────────

def test_metrics_trade_count_matches_ledger_count():
    bars = {
        "A": linear_uptrend_bars(100, 100, daily_step=1.5),
        "B": oscillating_bars(50, 100, amplitude=5.0),
    }
    boundary = split_trading_days(bars)
    trades_mom = run_strategy(
        "momentum", bars,
        {"lookback_window": 10, "entry_threshold": 0.03, "exit_threshold": -0.05,
         "max_holding_days": 15},
        boundary,
    )
    metrics = compute_metrics(trades_mom, bars, ["A", "B"], boundary)

    # The exact invariant qr_qa Gate 0 enforces.
    assert metrics["trade_count_is"] + metrics["trade_count_oos"] == len(trades_mom)
    assert metrics["trade_count_is"] >= 0
    assert metrics["trade_count_oos"] >= 0


def test_metrics_drawdown_sign_is_negative_or_zero():
    """Contract: max_drawdown stored as a negative decimal."""
    bars = {"OSC": oscillating_bars(100, 250, amplitude=8.0)}
    boundary = split_trading_days(bars)
    trades = run_strategy(
        "mean_reversion", bars,
        {"lookback_window": 20, "entry_threshold": 1.5},
        boundary,
    )
    metrics = compute_metrics(trades, bars, ["OSC"], boundary)
    assert metrics["max_drawdown"] <= 0


def test_run_backtest_with_no_data_returns_no_data_status():
    """run_backtest must not crash on an empty load; the agent emits workflow.stuck."""

    class _EmptyConn:
        """Stand-in for psycopg2 connection — yields zero rows."""
        def cursor(self):
            return _EmptyCursor()

    class _EmptyCursor:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, *a, **kw): pass
        def fetchall(self): return []

    trades, metrics, status = bt.run_backtest(
        _EmptyConn(),
        {"asset_universe": ["GHOST"],
         "date_range": {"start": "2026-01-01", "end": "2026-03-01"},
         "strategy_type": "momentum"},
    )
    assert status == "no_data"
    assert trades == []
    assert metrics["trade_count_is"] == 0 and metrics["trade_count_oos"] == 0


def test_run_backtest_invalid_param_set_raises_insufficient_data():
    class _EmptyConn:
        def cursor(self): return _EmptyCursor()

    class _EmptyCursor:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, *a, **kw): pass
        def fetchall(self): return []

    for bad in [
        {},
        {"asset_universe": []},
        {"asset_universe": ["X"], "date_range": {"start": "bogus", "end": "2026-01-01"}},
    ]:
        try:
            bt.run_backtest(_EmptyConn(), bad)
        except InsufficientDataError:
            continue
        raise AssertionError(f"expected InsufficientDataError for param_set={bad!r}")


# ─── Tiny test runner so this file is runnable without pytest ──────────────

def _main():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    _main()
