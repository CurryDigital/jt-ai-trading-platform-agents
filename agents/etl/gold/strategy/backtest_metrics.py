"""Backtest metric helpers for ETL strategy pipelines.

Usage:
    from gold.strategy.backtest_metrics import compute_oos_metrics, profit_factor

    pnls = [0.012, -0.005, 0.021, -0.009, 0.008]
    metrics = compute_oos_metrics(pnls, annualization_factor=52)

All percentages are stored as decimals (e.g. 0.05 for 5%).
The UI view multiplies by 100 for display.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence


def profit_factor(pnls: Sequence[float]) -> Optional[float]:
    """Gross profit / gross loss (absolute value). Returns None when no losses."""
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return None
    return round(gross_profit / gross_loss, 6)


def win_rate(pnls: Sequence[float]) -> float:
    if not pnls:
        return 0.0
    wins = sum(1 for p in pnls if p > 0)
    return round(wins / len(pnls), 6)


def total_return(pnls: Sequence[float]) -> float:
    """Compound return from a PnL series."""
    if not pnls:
        return 0.0
    prod = 1.0
    for p in pnls:
        prod *= 1 + p
    return round(prod - 1, 6)


def sharpe_ratio(pnls: Sequence[float], annualization_factor: float = 1.0) -> Optional[float]:
    if len(pnls) < 2:
        return None
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return None
    return round(mean / std * math.sqrt(annualization_factor), 6)


def max_drawdown(pnls: Sequence[float]) -> float:
    """Return maximum drawdown as a negative decimal."""
    if not pnls:
        return 0.0
    peak = 1.0
    equity = 1.0
    max_dd = 0.0
    for p in pnls:
        equity *= 1 + p
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)
    return round(max_dd, 6)


def compute_oos_metrics(
    pnls: Sequence[float],
    annualization_factor: float = 1.0,
) -> dict:
    """Compute the canonical OOS metrics required by strategy_backtest_runs.

    Returns dict with:
        profit_factor_oos, trade_count_oos, win_rate_oos,
        returns_oos, sharpe_oos, max_drawdown_oos
    """
    pnls = list(pnls)
    return {
        "profit_factor_oos": profit_factor(pnls),
        "trade_count_oos": len(pnls),
        "win_rate_oos": win_rate(pnls),
        "returns_oos": total_return(pnls),
        "sharpe_oos": sharpe_ratio(pnls, annualization_factor),
        "max_drawdown_oos": max_drawdown(pnls),
    }


def estimate_profit_factor_from_wr_and_payoff(
    win_rate: float, payoff_ratio: float
) -> float:
    """Estimate PF when only win rate and average win/loss ratio are known."""
    if win_rate >= 1.0:
        return 999.0
    if win_rate <= 0.0:
        return 0.0
    loss_rate = 1 - win_rate
    return round((win_rate * payoff_ratio) / loss_rate, 6)


if __name__ == "__main__":
    sample = [0.012, -0.005, 0.021, -0.009, 0.008, -0.004, 0.015]
    print(compute_oos_metrics(sample, annualization_factor=52))
