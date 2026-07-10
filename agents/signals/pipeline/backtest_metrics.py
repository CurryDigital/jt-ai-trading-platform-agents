#!/usr/bin/env python3
"""
ETL backtest metrics helper.

Provides deterministic OOS metrics from a returns series and from a list of
per-trade PnL values. This module is intended to be imported by any ETL runner
that persists to gold.strategy_backtest_runs so that profit_factor_oos,
trade_count_oos, win_rate_oos, returns_oos, max_drawdown_oos and sharpe_oos
are always populated consistently.

Usage:
    from pipeline.backtest_metrics import compute_oos_metrics  # agents/signals/
    metrics = compute_oos_metrics(oos_returns, trade_count=...)
    # then INSERT/UPDATE gold.strategy_backtest_runs with metrics dict
"""
from __future__ import annotations
from typing import Iterable, Optional
import math
import numpy as np
import pandas as pd


__all__ = ["compute_oos_metrics", "sharpe_from_returns", "max_drawdown_from_returns"]


def _to_series(returns: Iterable[float]) -> pd.Series:
    if isinstance(returns, pd.Series):
        return returns.dropna()
    return pd.Series([float(x) for x in returns if x is not None and not (isinstance(x, float) and math.isnan(x))])


def sharpe_from_returns(returns: Iterable[float], periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    """Annualized Sharpe ratio from a periodic return series."""
    r = _to_series(returns)
    if r.empty or r.std() == 0 or len(r) < 2:
        return 0.0
    excess = r - risk_free
    return float(excess.mean() / excess.std() * math.sqrt(periods_per_year))


def max_drawdown_from_returns(returns: Iterable[float]) -> float:
    """Maximum drawdown as a negative ratio (e.g. -0.15 for 15%)."""
    r = _to_series(returns)
    if r.empty:
        return 0.0
    cum = (1 + r).cumprod()
    rolling_max = cum.cummax()
    dd = (cum - rolling_max) / rolling_max
    return float(dd.min()) if not dd.empty else 0.0


def compute_oos_metrics(
    oos_returns: Iterable[float],
    trade_count: Optional[int] = None,
    periods_per_year: int = 252,
) -> dict:
    """
    Compute OOS metrics from a periodic return series.

    Args:
        oos_returns: Series of periodic returns (e.g. daily or weekly).
        trade_count: Optional number of closed trades. If None, estimated from
                     non-zero return periods (acceptable for bar-level strategies).
        periods_per_year: 252 for daily, 52 for weekly.

    Returns:
        dict with keys:
            returns_oos, max_drawdown_oos, sharpe_oos, trade_count_oos,
            win_rate_oos, profit_factor_oos
    """
    r = _to_series(oos_returns)
    if r.empty:
        return {
            "returns_oos": 0.0,
            "max_drawdown_oos": 0.0,
            "sharpe_oos": 0.0,
            "trade_count_oos": 0,
            "win_rate_oos": 0.0,
            "profit_factor_oos": None,
        }

    total_ret = float((1 + r).prod() - 1)
    sharpe = sharpe_from_returns(r, periods_per_year=periods_per_year)
    max_dd = max_drawdown_from_returns(r)

    non_zero = r[abs(r) > 1e-12]
    win_rate = float((non_zero > 0).mean()) if not non_zero.empty else 0.0

    gains = float(r[r > 0].sum()) if not r[r > 0].empty else 0.0
    losses = float(-r[r < 0].sum()) if not r[r < 0].empty else 0.0
    profit_factor = gains / losses if losses > 0 else None

    trade_count_out = trade_count if trade_count is not None else int((non_zero != 0).sum())

    return {
        "returns_oos": round(total_ret, 8),
        "max_drawdown_oos": round(max_dd, 8),
        "sharpe_oos": round(sharpe, 8),
        "trade_count_oos": int(trade_count_out),
        "win_rate_oos": round(win_rate, 8),
        "profit_factor_oos": round(profit_factor, 8) if profit_factor is not None else None,
    }


def compute_from_trade_pnls(pnls: Iterable[float]) -> dict:
    """
    Compute OOS metrics from a list of per-trade PnL values (not returns).
    Returns, win rate, and profit factor are derived from PnL.
    """
    vals = pd.Series([float(x) for x in pnls if x is not None and not (isinstance(x, float) and math.isnan(x))])
    if vals.empty:
        return {
            "returns_oos": 0.0,
            "max_drawdown_oos": 0.0,
            "sharpe_oos": 0.0,
            "trade_count_oos": 0,
            "win_rate_oos": 0.0,
            "profit_factor_oos": None,
        }
    total_ret = float(vals.sum())
    # Equity-curve drawdown from cumulative PnL
    cum = vals.cumsum()
    rolling_max = cum.cummax()
    dd = (cum - rolling_max) / rolling_max.replace(0, np.nan)
    max_dd = float(dd.min()) if not dd.empty else 0.0

    win_rate = float((vals > 0).mean())
    gains = float(vals[vals > 0].sum()) if not vals[vals > 0].empty else 0.0
    losses = float(-vals[vals < 0].sum()) if not vals[vals < 0].empty else 0.0
    profit_factor = gains / losses if losses > 0 else None

    return {
        "returns_oos": round(total_ret, 8),
        "max_drawdown_oos": round(max_dd, 8),
        "sharpe_oos": 0.0,  # cannot infer from PnL alone without time index
        "trade_count_oos": len(vals),
        "win_rate_oos": round(win_rate, 8),
        "profit_factor_oos": round(profit_factor, 8) if profit_factor is not None else None,
    }


if __name__ == "__main__":
    # sanity check
    sample = pd.Series([0.01, -0.005, 0.008, 0.012, -0.003, 0.004, 0.015, -0.007])
    print(compute_oos_metrics(sample, trade_count=8, periods_per_year=252))
