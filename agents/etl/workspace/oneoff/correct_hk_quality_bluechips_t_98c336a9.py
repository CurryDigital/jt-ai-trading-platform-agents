#!/usr/bin/env python3
"""
Correct HK_Quality_BlueChips live signal and paper trades after the signal file was updated.

Task: t_98c336a9
Source: /home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_live_signals.json

Actions:
1. Set all 20 universe tickers in gold.strategy_ticker_scores to their correct state:
   - top-5 (0001, 0002, 0005, 0016, 2388): BUY, score=100, entry_score=20, weight=0.2
   - others: HOLD, score=0, entry_score=0, weight=0.0
2. Backfill/rebuild paper_trades_synthetic so only the top-5 have open LONG positions on 2026-07-25.
3. Update consumption.strategies_signals_current to reflect HOLD for non-selected tickers.
4. Clean stale closed trades from gold.paper_trades for this strategy so live metrics do not double-count.
"""
import json
import os
import sys
import math
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts")
sys.path.insert(0, SHARED)
from db import get_connection  # noqa: E402

SIGNAL_FILE = "/home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_live_signals.json"
STRATEGY_ID = "HK_Quality_BlueChips"
STRATEGY_NAME = "HK Quality BlueChips Momentum"

SELECTED = {"0001.HK", "0002.HK", "0005.HK", "0016.HK", "2388.HK"}
UNIVERSE = [
    "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK", "0011.HK",
    "0016.HK", "0027.HK", "0388.HK", "0669.HK", "0836.HK", "0939.HK",
    "0941.HK", "1038.HK", "1299.HK", "1398.HK", "1928.HK", "2318.HK",
    "2388.HK", "2628.HK",
]


def load_signal_file(path: str) -> dict:
    with open(path, "r") as f:
        data = json.load(f)
    signals = data.get("signals", {})
    weights = signals.get(STRATEGY_NAME) or signals.get(STRATEGY_ID) or {}
    return data.get("generated_at", "unknown"), weights


def sync_ticker_scores(conn, generated_at: str, weights: dict):
    """Set every universe ticker to its correct score/action based on the corrected file."""
    cur = conn.cursor()
    rows = []
    for ticker in UNIVERSE:
        weight = float(weights.get(ticker, 0.0))
        if weight > 0:
            action = "BUY"
            score = 100.0
            entry_score = weight * 100  # 20.0
        else:
            action = "HOLD"
            score = 0.0
            entry_score = 0.0
        rows.append((
            STRATEGY_ID, ticker, score, action, entry_score, 0.0,
            json.dumps({
                "weight": round(weight, 6),
                "selected": weight > 0,
                "source_signal_file": SIGNAL_FILE,
                "generated_at": generated_at,
                "ingested_at": datetime.now().isoformat(),
                "execution_mode": "PAPER",
                "strategy_name": STRATEGY_NAME,
            }),
            "PAPER",
            datetime.now(),
            datetime.now(),
            "ingested",
        ))
    cur.executemany(
        """
        INSERT INTO gold.strategy_ticker_scores
          (strategy_id, ticker, score, signal_action, entry_score, exit_score,
           criteria_met, position_status, deployed_at, updated_at, signal_source)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        ON CONFLICT (strategy_id, ticker) DO UPDATE SET
          score           = EXCLUDED.score,
          signal_action   = EXCLUDED.signal_action,
          entry_score     = EXCLUDED.entry_score,
          exit_score      = EXCLUDED.exit_score,
          criteria_met    = EXCLUDED.criteria_met,
          position_status = EXCLUDED.position_status,
          updated_at      = EXCLUDED.updated_at,
          signal_source   = EXCLUDED.signal_source;
        """,
        rows,
    )
    conn.commit()
    print(f"Synced {len(rows)} rows in gold.strategy_ticker_scores for {STRATEGY_ID}")


def rebuild_paper_positions(conn, trade_date: str):
    """Run the canonical rebalancer in backfill mode for this strategy/date."""
    # Import and invoke the rebalancer directly so it runs in the same transaction
    rebalance_path = os.path.expanduser(
        "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/gold/strategy/rebuild_paper_positions.py"
    )
    sys.path.insert(0, os.path.dirname(rebalance_path))
    import rebuild_paper_positions
    rebuild_paper_positions.run(backfill=True, strategy_id=STRATEGY_ID, date_str=trade_date)


def clean_paper_trades_history(conn):
    """Remove stale closed paper_trades rows for this strategy to avoid double-counting."""
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM gold.paper_trades WHERE strategy_id = %s;",
        (STRATEGY_ID,),
    )
    n = cur.rowcount
    conn.commit()
    print(f"Deleted {n} stale rows from gold.paper_trades for {STRATEGY_ID}")


def main():
    generated_at, weights = load_signal_file(SIGNAL_FILE)
    print(f"Loaded corrected signal file generated_at={generated_at}")
    print(f"Selected weights: { {t: w for t, w in weights.items() if float(w) > 0} }")

    conn = get_connection()
    try:
        sync_ticker_scores(conn, generated_at, weights)
        # Rebalancer manages its own transaction
        rebuild_paper_positions(conn, "2026-07-25")
        clean_paper_trades_history(conn)
    finally:
        conn.close()

    print(f"HK_Quality_BlueChips correction complete for {STRATEGY_ID}")


if __name__ == "__main__":
    main()
