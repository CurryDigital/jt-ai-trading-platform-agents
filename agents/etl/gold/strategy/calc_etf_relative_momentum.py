#!/usr/bin/env python3
"""
Recalculate relative-momentum scores for ETF_US_Sector_Relative_Momentum.

Sources:
  - silver.unified_prices for daily closes
  - gold.strategy_ticker_scores for the current universe

Updates:
  - gold.strategy_ticker_scores(score, signal_action, entry_score, exit_score, criteria_met, updated_at)

Logic:
  - Composite momentum = average of 1m, 3m, 6m, 12m total returns.
  - Rank ETFs by composite momentum.
  - Top N = BUY (score 100 down to 70), others = NEUTRAL (score 0-40).
  - Tie-breaker by most recent 1m return.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta, date, timezone
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# 2026-07-22: use the shared DB pool instead of a local psycopg2 connect with a
# HARDCODED PLAINTEXT PASSWORD fallback (removed — never commit credentials).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path:
    sys.path.insert(0, _ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

STRATEGY_ID = "ETF_US_Sector_Relative_Momentum"
TOP_N = 3
# 2026-07-22: lookbacks are CALENDAR days (fetch_closest_price finds the close
# on-or-before target_date). The old values (21/63/126/252) were trading-day
# counts used as calendar-day deltas, so "1m" was really ~15 trading days and
# "12m" ~8.3 months — every momentum window was materially wrong.
LOOKBACKS = {
    "1m": 30,
    "3m": 91,
    "6m": 182,
    "12m": 365,
}


def connect():
    return get_connection()


@dataclass
class MomentumRow:
    ticker: str
    returns: Dict[str, Optional[float]] = field(default_factory=dict)
    composite: float = 0.0
    rank: int = 0


def fetch_universe(cur) -> List[str]:
    # 2026-07-22: read the universe from gold.strategy_registry.universe_tickers
    # (the source of truth), not from gold.strategy_ticker_scores — the table
    # this script WRITES. The old self-referential read returned empty on any
    # first run or after a truncate, silently disabling the strategy.
    cur.execute(
        "SELECT universe_tickers FROM gold.strategy_registry WHERE strategy_id = %s",
        (STRATEGY_ID,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return []
    return sorted(t for t in row[0] if t and t != 'CASH')


def fetch_closest_price(cur, ticker: str, target_date: date) -> Optional[float]:
    """Return the close price on or before target_date."""
    cur.execute(
        """
        SELECT close, date
        FROM silver.unified_prices
        WHERE ticker = %s AND date <= %s AND close IS NOT NULL
        ORDER BY date DESC
        LIMIT 1;
        """,
        (ticker, target_date),
    )
    row = cur.fetchone()
    if row:
        return float(row[0])
    return None


def fetch_latest_price(cur, ticker: str) -> Optional[float]:
    cur.execute(
        """
        SELECT close FROM silver.unified_prices
        WHERE ticker = %s AND close IS NOT NULL
        ORDER BY date DESC LIMIT 1;
        """,
        (ticker,),
    )
    row = cur.fetchone()
    return float(row[0]) if row else None


def compute_momentum(cur, ticker: str, latest_date: date) -> Optional[MomentumRow]:
    latest_price = fetch_latest_price(cur, ticker)
    if latest_price is None:
        logger.warning("No latest price for %s", ticker)
        return None

    returns: Dict[str, Optional[float]] = {}
    valid_returns = []
    for label, days in LOOKBACKS.items():
        target = latest_date - timedelta(days=days)
        past_price = fetch_closest_price(cur, ticker, target)
        if past_price and past_price > 0:
            r = latest_price / past_price - 1.0
            returns[label] = round(r, 6)
            valid_returns.append(r)
        else:
            returns[label] = None

    if not valid_returns:
        logger.warning("No valid lookback returns for %s", ticker)
        return None

    composite = sum(valid_returns) / len(valid_returns)
    return MomentumRow(ticker=ticker, returns=returns, composite=round(composite, 6))


def assign_scores(rows: List[MomentumRow]) -> Dict[str, Dict]:
    """Rank by composite momentum, assign BUY/NEUTRAL and target weights.

    Research handoff target for this strategy is 30/30/30 per the top-3
    momentum names, with 10% residual cash. Scores are therefore emitted as
    percentages that sum to 100 so the position rebalancer can use them as
    target weights directly.
    """
    sorted_rows = sorted(
        rows,
        key=lambda r: (r.composite, r.returns.get("1m") or -1e9),
        reverse=True,
    )
    for i, row in enumerate(sorted_rows, start=1):
        row.rank = i

    n = len(sorted_rows)
    out = {}
    for row in sorted_rows:
        if row.rank <= TOP_N:
            action = "BUY"
            score = 30.0
        else:
            action = "HOLD"
            score = 0.0

        out[row.ticker] = {
            "score": round(score, 2),
            "signal_action": action,
            "entry_score": 10.0 if action == "BUY" else 0.0,
            "exit_score": 0.0,
            "criteria_met": {
                "lookback_returns": row.returns,
                "composite_momentum": row.composite,
                "rank": row.rank,
                "top_n": TOP_N,
                "rebalanced_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    # Residual cash target: 10%.
    out["CASH"] = {
        "score": 10.0,
        "signal_action": "HOLD",
        "entry_score": 0.0,
        "exit_score": 0.0,
        "criteria_met": {
            "rationale": "residual cash per 30% max-weight cap",
            "rebalanced_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return out


def upsert_scores(cur, scores: Dict[str, Dict]) -> int:
    """Insert or update scores, including CASH which is not in the ETF universe."""
    upserted = 0
    for ticker, meta in scores.items():
        cur.execute(
            """
            INSERT INTO gold.strategy_ticker_scores
                (strategy_id, ticker, score, signal_action, entry_score, exit_score, criteria_met, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (strategy_id, ticker) DO UPDATE SET
                score = EXCLUDED.score,
                signal_action = EXCLUDED.signal_action,
                entry_score = EXCLUDED.entry_score,
                exit_score = EXCLUDED.exit_score,
                criteria_met = EXCLUDED.criteria_met,
                updated_at = EXCLUDED.updated_at;
            """,
            (
                STRATEGY_ID,
                ticker,
                meta["score"],
                meta["signal_action"],
                meta["entry_score"],
                meta["exit_score"],
                json.dumps(meta["criteria_met"]),
            ),
        )
        upserted += cur.rowcount
    return upserted


def update_scores(cur, scores: Dict[str, Dict]) -> int:
    """Deprecated wrapper retained for backwards compatibility."""
    return upsert_scores(cur, scores)


def main():
    conn = connect()
    conn.autocommit = True
    cur = conn.cursor()

    try:
        cur.execute("SELECT MAX(date) FROM silver.unified_prices WHERE close IS NOT NULL;")
        latest_date = cur.fetchone()[0]
        if not isinstance(latest_date, date):
            logger.error("Unexpected latest_date type: %s", type(latest_date))
            sys.exit(1)
        if latest_date is None:
            logger.error("No price data available")
            sys.exit(1)
        logger.info("Latest price date: %s", latest_date)

        universe = fetch_universe(cur)
        if not universe:
            logger.error("No universe found for %s", STRATEGY_ID)
            sys.exit(1)
        logger.info("Universe (%d): %s", len(universe), universe)

        rows = []
        for ticker in universe:
            row = compute_momentum(cur, ticker, latest_date)
            if row:
                logger.info(
                    "%-5s composite=%+.2f%% 1m=%+.2f%% 3m=%+.2f%% 12m=%+.2f%%",
                    ticker,
                    row.composite * 100,
                    (row.returns.get("1m") or 0) * 100,
                    (row.returns.get("3m") or 0) * 100,
                    (row.returns.get("12m") or 0) * 100,
                )
                rows.append(row)

        scores = assign_scores(rows)
        for ticker, meta in sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True):
            logger.info("%-5s score=%.1f action=%s", ticker, meta["score"], meta["signal_action"])

        updated = update_scores(cur, scores)
        logger.info("Updated %d rows in gold.strategy_ticker_scores", updated)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
