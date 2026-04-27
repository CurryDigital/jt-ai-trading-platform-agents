"""
Backtest engine for qr_algo.

Implements the contract declared in agents/qr_algo/AGENTS.md:
- 70/30 IS/OOS split by trading days (BACKTEST_IS_OOS_SPLIT)
- 5 bps round-trip transaction cost (TRANSACTION_COST_PCT per side, applied twice)
- Sharpe = (mean_daily_return - rf/252) / std_daily_return * sqrt(252)
- Max drawdown stored as a NEGATIVE decimal
- Trade ledger is the source of truth — Gate 0 (anti-hallucination) verifies
  that metrics.trade_count_is + metrics.trade_count_oos equals COUNT(trades)

Inputs come from gold.stock_metrics_history (read-only view). Outputs are a
list of Trade tuples (matching the strategy_backtest_trades schema) plus a
metrics dict matching the schema documented in qr_algo/AGENTS.md::Step 2c.

Pure stdlib + agents.shared.constants — no pandas/numpy dependency.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date as _date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agents.shared.constants import (
    BACKTEST_IS_OOS_SPLIT,
    TRANSACTION_COST_PCT,
    RISK_FREE_RATE,
    ANNUALISATION_FACTOR,
)


# ─── Types ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Bar:
    """One day of price data for one ticker. Matches gold.stock_metrics_history."""
    date: _date
    close: float
    volume: Optional[float] = None


@dataclass
class Trade:
    """One closed position. Matches the strategy_backtest_trades table."""
    ticker: str
    period_type: str          # 'IS' or 'OOS'
    entry_date: _date
    exit_date: _date
    entry_price: float
    exit_price: float
    pnl_pct: float            # net of transaction costs (round-trip)
    holding_days: float
    exit_reason: str          # 'signal' | 'time_stop' | 'eod'

    def as_db_row(self, strategy_id: str) -> Tuple:
        return (
            strategy_id,
            self.ticker,
            self.period_type,
            self.entry_date,
            self.exit_date,
            float(self.entry_price),
            float(self.exit_price),
            float(self.pnl_pct),
            float(self.holding_days),
            self.exit_reason,
        )


class UnsupportedStrategyError(ValueError):
    """Raised when param_set.strategy_type has no implementation in this engine."""


class InsufficientDataError(RuntimeError):
    """Raised when the gold layer has no usable data for the requested universe + range."""


# ─── Data loading ───────────────────────────────────────────────────────────

def load_prices(conn, asset_universe: List[str], start: _date, end: _date) -> Dict[str, List[Bar]]:
    """
    Pull price bars for every ticker in `asset_universe` between `start` and `end`
    (inclusive) from gold.stock_metrics_history. Returns a per-ticker list of
    Bar objects sorted ascending by date. Tickers with zero rows are omitted —
    qr_data_validator's coverage check should already have flagged that.
    """
    out: Dict[str, List[Bar]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, date, close::float, volume::float
            FROM   gold.stock_metrics_history
            WHERE  ticker = ANY(%s)
              AND  date BETWEEN %s AND %s
            ORDER  BY ticker, date
            """,
            (list(asset_universe), start, end),
        )
        for ticker, day, close, volume in cur.fetchall():
            out.setdefault(ticker, []).append(Bar(date=day, close=close, volume=volume))
    return out


# ─── IS/OOS split ───────────────────────────────────────────────────────────

def split_trading_days(
    bars_by_ticker: Dict[str, List[Bar]],
    is_ratio: float = BACKTEST_IS_OOS_SPLIT,
) -> _date:
    """
    Determine the date that separates IS (first 70%) from OOS (last 30%) by
    *trading-day count across the union of all tickers*. Returns the boundary
    date — every bar with `date <= boundary` is IS, every bar after is OOS.
    """
    all_days = sorted({bar.date for bars in bars_by_ticker.values() for bar in bars})
    if not all_days:
        raise InsufficientDataError("no trading days across the universe")
    cutoff_idx = max(1, int(len(all_days) * is_ratio)) - 1
    return all_days[cutoff_idx]


def label_period(d: _date, is_oos_boundary: _date) -> str:
    return "IS" if d <= is_oos_boundary else "OOS"


# ─── Transaction-cost helper ────────────────────────────────────────────────

def apply_round_trip_cost(gross_pnl_pct: float) -> float:
    """
    Apply TRANSACTION_COST_PCT on entry AND exit (per side).
    Returns net pnl_pct.
    """
    return gross_pnl_pct - 2.0 * TRANSACTION_COST_PCT


# ─── Metric helpers (stdlib only) ───────────────────────────────────────────

def _safe_stdev(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return statistics.pstdev(xs)


def annualised_sharpe(daily_returns: List[float]) -> float:
    if not daily_returns:
        return 0.0
    mean = statistics.fmean(daily_returns)
    sd = _safe_stdev(daily_returns)
    if sd == 0:
        return 0.0
    excess = mean - RISK_FREE_RATE / ANNUALISATION_FACTOR
    return excess / sd * math.sqrt(ANNUALISATION_FACTOR)


def annualised_return(daily_returns: List[float]) -> float:
    if not daily_returns:
        return 0.0
    return statistics.fmean(daily_returns) * ANNUALISATION_FACTOR


def max_drawdown(daily_returns: List[float]) -> float:
    """
    Compute max drawdown of the cumulative return path. Returns a NEGATIVE
    number (or 0.0 if no series). The strategy_workflow.metrics contract
    requires drawdown stored as a negative decimal; this preserves the sign.
    """
    if not daily_returns:
        return 0.0
    cumulative = 1.0
    peak = 1.0
    worst = 0.0
    for r in daily_returns:
        cumulative *= (1.0 + r)
        peak = max(peak, cumulative)
        drawdown = (cumulative / peak) - 1.0  # ≤ 0
        worst = min(worst, drawdown)
    return worst


def cvar(daily_returns: List[float], alpha: float = 0.05) -> float:
    """
    Conditional Value at Risk at the `alpha` tail (default 5%).
    Returned as a NEGATIVE decimal magnitude — i.e. the average of the worst
    `alpha` fraction of daily returns. Risk gate `tail_risk` compares
    abs(cvar) against the threshold.
    """
    if not daily_returns:
        return 0.0
    sorted_r = sorted(daily_returns)
    cutoff = max(1, int(len(sorted_r) * alpha))
    return statistics.fmean(sorted_r[:cutoff])


# ─── Daily portfolio return reconstruction ─────────────────────────────────

def daily_portfolio_returns(
    trades: List[Trade],
    asset_universe: List[str],
    period_dates: List[_date],
) -> List[float]:
    """
    Approximate daily portfolio returns from the trade ledger.

    Each trade contributes pnl_pct / holding_days to every trading day in
    [entry_date+1, exit_date]. We then divide by len(asset_universe) so the
    portfolio is equal-weighted across the requested universe (positions on
    inactive tickers contribute zero — those slots sit in cash).

    This is a deliberate approximation suitable for low-frequency strategies.
    For tick-level or high-frequency work we'd need to track concurrent
    positions explicitly. Documented in AGENTS.md as the current contract.
    """
    if not trades or not period_dates:
        return []

    universe_size = max(1, len(asset_universe))
    contributions: Dict[_date, float] = defaultdict(float)

    for trade in trades:
        days = max(1.0, trade.holding_days)
        per_day = trade.pnl_pct / days
        # Distribute across each trading day inside the holding window.
        for d in period_dates:
            if trade.entry_date < d <= trade.exit_date:
                contributions[d] += per_day

    return [contributions.get(d, 0.0) / universe_size for d in period_dates]


# ─── Metric assembly ───────────────────────────────────────────────────────

def _per_ticker_exposure(trades: List[Trade]) -> float:
    """
    Single-asset concentration: notional per ticker / total notional, picked at
    its peak. Uses trade count as a proxy for notional (equal-weight slots).
    qr_risk also recomputes this from the ledger as a defense-in-depth check.
    """
    if not trades:
        return 0.0
    counts: Dict[str, int] = defaultdict(int)
    for t in trades:
        counts[t.ticker] += 1
    total = sum(counts.values())
    return max(counts.values()) / total if total else 0.0


def compute_metrics(
    trades: List[Trade],
    bars_by_ticker: Dict[str, List[Bar]],
    asset_universe: List[str],
    is_oos_boundary: _date,
) -> Dict[str, Any]:
    """
    Roll the trade ledger up into the summary metric dict that risk + qa
    expect. The trade_count_* fields here MUST match COUNT(*) of inserted
    rows in strategy_backtest_trades (Gate 0 anti-hallucination invariant).
    """
    is_trades = [t for t in trades if t.period_type == "IS"]
    oos_trades = [t for t in trades if t.period_type == "OOS"]

    all_days = sorted({b.date for bars in bars_by_ticker.values() for b in bars})
    is_days = [d for d in all_days if d <= is_oos_boundary]
    oos_days = [d for d in all_days if d > is_oos_boundary]

    is_returns = daily_portfolio_returns(is_trades, asset_universe, is_days)
    oos_returns = daily_portfolio_returns(oos_trades, asset_universe, oos_days)

    sharpe_is = annualised_sharpe(is_returns)
    sharpe_oos = annualised_sharpe(oos_returns)
    sharpe_ratio_is_oos = sharpe_oos / sharpe_is if sharpe_is else 0.0

    win_rate = (
        sum(1 for t in trades if t.pnl_pct > 0) / len(trades)
        if trades else 0.0
    )

    total_holding_days = sum(t.holding_days for t in trades)
    avg_holding_days = total_holding_days / len(trades) if trades else 0.0

    # Turnover proxy: trades per year divided by max concurrent positions.
    span_years = max(1.0, len(all_days) / ANNUALISATION_FACTOR)
    max_positions = max(1, len(asset_universe) // 2)
    turnover_rate = (len(trades) / span_years) / max_positions

    return {
        "sharpe_is":              round(sharpe_is, 4),
        "sharpe_oos":             round(sharpe_oos, 4),
        "sharpe_ratio_is_oos":    round(sharpe_ratio_is_oos, 4),
        "returns_annualised_is":  round(annualised_return(is_returns), 4),
        "returns_annualised_oos": round(annualised_return(oos_returns), 4),
        "max_drawdown":           round(max_drawdown(is_returns + oos_returns), 4),
        "win_rate":               round(win_rate, 4),
        "trade_count_is":         len(is_trades),
        "trade_count_oos":        len(oos_trades),
        "avg_holding_days":       round(avg_holding_days, 2),
        "turnover_rate":          round(turnover_rate, 4),
        "cvar":                   round(cvar(oos_returns + is_returns), 4),
        "max_single_asset_exposure": round(_per_ticker_exposure(trades), 4),
    }


# ─── Top-level entry point ─────────────────────────────────────────────────

def run_backtest(
    conn,
    param_set: Dict[str, Any],
) -> Tuple[List[Trade], Dict[str, Any], str]:
    """
    Execute a backtest end-to-end.

    Returns:
        trades  — list of Trade objects (write to strategy_backtest_trades FIRST)
        metrics — summary dict (write to strategy_workflow.metrics SECOND)
        status  — 'completed' | 'no_data'

    Raises:
        UnsupportedStrategyError — strategy_type has no implementation here
        InsufficientDataError    — gold layer returned nothing for the universe
    """
    # Imported here to avoid circular import (strategies imports Trade from us).
    from agents.qr_algo.strategies import run_strategy

    asset_universe = list(param_set.get("asset_universe", []))
    if not asset_universe:
        raise InsufficientDataError("param_set.asset_universe is empty")

    date_range = param_set.get("date_range", {})
    try:
        start = _parse_date(date_range.get("start"))
        end = _parse_date(date_range.get("end"))
    except ValueError as e:
        raise InsufficientDataError(
            f"param_set.date_range invalid: {date_range!r} ({e})"
        )
    if start is None or end is None:
        raise InsufficientDataError(f"param_set.date_range invalid: {date_range!r}")

    bars_by_ticker = load_prices(conn, asset_universe, start, end)
    if not any(bars_by_ticker.values()):
        return [], _empty_metrics(), "no_data"

    is_oos_boundary = split_trading_days(bars_by_ticker)
    trades = run_strategy(
        strategy_type=param_set.get("strategy_type", ""),
        bars_by_ticker=bars_by_ticker,
        param_set=param_set,
        is_oos_boundary=is_oos_boundary,
    )
    metrics = compute_metrics(trades, bars_by_ticker, asset_universe, is_oos_boundary)
    return trades, metrics, "completed"


# ─── Internals ─────────────────────────────────────────────────────────────

def _parse_date(s: Optional[str]) -> Optional[_date]:
    if s is None:
        return None
    if isinstance(s, _date):
        return s
    return datetime.strptime(s, "%Y-%m-%d").date()


def _empty_metrics() -> Dict[str, Any]:
    """Returned when load_prices yields no usable data — risk gate will reject."""
    return {
        "sharpe_is": 0.0, "sharpe_oos": 0.0, "sharpe_ratio_is_oos": 0.0,
        "returns_annualised_is": 0.0, "returns_annualised_oos": 0.0,
        "max_drawdown": 0.0, "win_rate": 0.0,
        "trade_count_is": 0, "trade_count_oos": 0,
        "avg_holding_days": 0.0, "turnover_rate": 0.0,
        "cvar": 0.0, "max_single_asset_exposure": 0.0,
    }
