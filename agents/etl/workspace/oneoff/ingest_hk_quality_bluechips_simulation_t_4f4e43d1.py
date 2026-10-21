#!/usr/bin/env python3
"""
Ingest HK_Quality_BlueChips YTD simulation trades into gold.paper_trades_synthetic.

Task: t_4f4e43d1
Source: /home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_simulation_trades.csv

Behaviour:
- Read the simulation trade ledger (BUY/SELL legs).
- Pair BUY and SELL legs into closed round-trip rows.
- Keep unpaired BUY rows as 'open' positions (the 5 current holdings).
- Replace all existing HK_Quality_BlueChips rows in gold.paper_trades_synthetic
  to avoid duplicates and ensure the simulation tail is current.
- Preserve CSV values: pnl/pnl_pct are stored as decimal ratios (source format),
  signal_weight is stored as the raw CSV decimal (e.g. 0.2).
"""
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts")
sys.path.insert(0, SHARED)
from db import get_connection  # noqa: E402

CSV_PATH = "/home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_simulation_trades.csv"
STRATEGY_ID = "HK_Quality_BlueChips"


def parse_decimal(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_csv(path):
    rows = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "entry_date": r["entry_date"].strip() or None,
                "exit_date": r["exit_date"].strip() or None,
                "ticker": r["ticker"].strip(),
                "side": r["side"].strip().upper(),
                "quantity": parse_decimal(r.get("quantity")),
                "entry_price": parse_decimal(r.get("entry_price")),
                "exit_price": parse_decimal(r.get("exit_price")),
                "pnl": parse_decimal(r.get("pnl")),
                "pnl_pct": parse_decimal(r.get("pnl_pct")),
                "status": r["status"].strip().lower(),
                "signal_weight": parse_decimal(r.get("signal_weight")),
                "assigned_capital": parse_decimal(r.get("assigned_capital")),
                "direction": r["direction"].strip().upper(),
            })
    return rows


def pair_rows(rows):
    """Pair BUY/SELL legs into round-trip rows. Unpaired BUY rows remain open."""
    # Group by (entry_date, exit_date, ticker, entry_price, signal_weight, assigned_capital, direction)
    # Each group should contain exactly one BUY and one SELL for closed round-trips.
    groups = defaultdict(list)
    for r in rows:
        key = (r["entry_date"], r["exit_date"], r["ticker"], r["entry_price"],
               r["signal_weight"], r["assigned_capital"], r["direction"])
        groups[key].append(r)

    closed = []
    open_rows = []
    warnings = []

    for key, group in groups.items():
        entry_date, exit_date, ticker, entry_price, signal_weight, assigned_capital, direction = key
        buy_rows = [g for g in group if g["side"] == "BUY"]
        sell_rows = [g for g in group if g["side"] == "SELL"]

        if len(group) == 2 and len(buy_rows) == 1 and len(sell_rows) == 1:
            buy = buy_rows[0]
            sell = sell_rows[0]
            closed.append({
                "strategy_id": STRATEGY_ID,
                "ticker": ticker,
                "direction": direction,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_price": buy["entry_price"],
                "exit_price": sell["exit_price"],
                "n_shares": abs(buy["quantity"]) if buy["quantity"] else None,
                "pnl": sell["pnl"],
                "pnl_pct": sell["pnl_pct"],
                "status": "closed",
                "signal_weight": signal_weight,
                "assigned_capital": assigned_capital,
            })
        elif len(group) == 1 and len(buy_rows) == 1 and buy_rows[0]["status"] == "open":
            buy = buy_rows[0]
            open_rows.append({
                "strategy_id": STRATEGY_ID,
                "ticker": ticker,
                "direction": direction,
                "entry_date": entry_date,
                "exit_date": None,
                "entry_price": buy["entry_price"],
                "exit_price": None,
                "n_shares": abs(buy["quantity"]) if buy["quantity"] else None,
                "pnl": None,
                "pnl_pct": None,
                "status": "open",
                "signal_weight": signal_weight,
                "assigned_capital": assigned_capital,
            })
        else:
            warnings.append(f"Unmatched group for {key}: {len(group)} rows, {len(buy_rows)} BUY, {len(sell_rows)} SELL")

    return closed, open_rows, warnings


def ingest():
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(f"Simulation CSV not found: {CSV_PATH}")

    rows = load_csv(CSV_PATH)
    print(f"Loaded {len(rows)} rows from {CSV_PATH}")

    buy_count = sum(1 for r in rows if r["side"] == "BUY")
    sell_count = sum(1 for r in rows if r["side"] == "SELL")
    open_count = sum(1 for r in rows if r["status"] == "open")
    print(f"  BUY: {buy_count}, SELL: {sell_count}, OPEN: {open_count}")

    closed, open_rows, warnings = pair_rows(rows)
    print(f"  Paired into {len(closed)} closed round-trips")
    print(f"  Unpaired open BUY rows: {len(open_rows)}")
    for w in warnings:
        print(f"  WARNING: {w}")

    all_rows = closed + open_rows
    if not all_rows:
        print("No rows to ingest. Exiting.")
        return

    conn = get_connection()
    cur = conn.cursor()
    try:
        # Verify expected schema columns exist
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'paper_trades_synthetic'
        """)
        existing_cols = {r[0] for r in cur.fetchall()}
        required_cols = {"strategy_id", "ticker", "direction", "entry_date", "exit_date",
                         "entry_price", "exit_price", "n_shares", "pnl", "pnl_pct",
                         "status", "signal_weight", "assigned_capital"}
        missing = required_cols - existing_cols
        if missing:
            raise RuntimeError(f"Missing required columns: {missing}")

        # Count before
        cur.execute(
            "SELECT status, COUNT(*) FROM gold.paper_trades_synthetic WHERE strategy_id = %s GROUP BY status",
            (STRATEGY_ID,),
        )
        before = dict(cur.fetchall())
        print(f"  Existing rows before: {before}")

        # Remove all existing rows for this strategy to avoid duplicates
        cur.execute(
            "DELETE FROM gold.paper_trades_synthetic WHERE strategy_id = %s",
            (STRATEGY_ID,),
        )
        deleted = cur.rowcount
        print(f"  Deleted {deleted} existing rows for {STRATEGY_ID}")

        # Insert simulation rows
        insert_sql = """
            INSERT INTO gold.paper_trades_synthetic
              (strategy_id, ticker, direction, entry_date, exit_date, entry_price,
               exit_price, n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital,
               created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """
        values = []
        for r in all_rows:
            values.append((
                r["strategy_id"],
                r["ticker"],
                r["direction"],
                r["entry_date"],
                r["exit_date"],
                r["entry_price"],
                r["exit_price"],
                r["n_shares"],
                r["pnl"],
                r["pnl_pct"],
                r["status"],
                r["signal_weight"],
                r["assigned_capital"],
            ))

        cur.executemany(insert_sql, values)
        inserted = cur.rowcount
        print(f"  Inserted {inserted} rows")

        # Count after
        cur.execute(
            "SELECT status, COUNT(*) FROM gold.paper_trades_synthetic WHERE strategy_id = %s GROUP BY status",
            (STRATEGY_ID,),
        )
        after = dict(cur.fetchall())
        print(f"  Rows after: {after}")

        conn.commit()
        print("Ingestion complete")
    except Exception as e:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    ingest()
