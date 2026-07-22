#!/usr/bin/env python3
"""
Collect universe tickers and live broker/symbol mapping table.

Reads universe_tickers from gold.strategy_registry for
ETF_HK_Balanced_Trend and HK_Quality_BlueChips, then joins with the live
broker mapping table bronze.ibkr_contracts.

Outputs:
  - universe_tickers_broker_mapping.csv
  - universe_tickers_broker_mapping.json

Columns: universe_name, normalized_ticker, broker_symbol, con_id, sec_type,
         exchange, primary_exchange, currency, local_symbol, trading_class,
         mapping_status, captured_at
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"
))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

from db import get_connection  # noqa: E402

STRATEGIES = ["ETF_HK_Balanced_Trend", "HK_Quality_BlueChips"]


def normalize_ticker(ticker: str) -> str:
    """Keep .HK suffix if present; AGG stays AGG."""
    ticker = ticker.strip().upper()
    if ticker.endswith(".HK"):
        # Preserve 4-digit HK code with leading zeros, e.g. 0001.HK
        code = ticker[:-3].lstrip("0")
        if not code:
            code = "0"
        return f"{code.zfill(4)}.HK"
    return ticker


def broker_symbol(ticker: str) -> str:
    """IBKR local symbol: strip .HK and leading zeros; AGG unchanged."""
    if ticker == "AGG":
        return "AGG"
    if ticker.endswith(".HK"):
        code = ticker[:-3].lstrip("0")
        return code if code else "0"
    return ticker


def load_universes(cur):
    cur.execute(
        """
        SELECT strategy_id, universe_tickers
        FROM gold.strategy_registry
        WHERE strategy_id = ANY(%s)
        ORDER BY strategy_id;
        """,
        (STRATEGIES,),
    )
    return {r[0]: [normalize_ticker(t) for t in r[1]] for r in cur.fetchall()}


def load_broker_mappings(cur, tickers):
    symbols = [broker_symbol(t) for t in tickers]
    cur.execute(
        """
        SELECT con_id, symbol, sec_type, exchange, primary_exchange,
               currency, local_symbol, trading_class
        FROM bronze.ibkr_contracts
        WHERE symbol = ANY(%s) OR local_symbol = ANY(%s)
        ORDER BY symbol;
        """,
        (tickers, symbols),
    )
    rows = {}
    for r in cur.fetchall():
        key = r[1]  # symbol column is normalized yfinance ticker
        rows[key] = {
            "con_id": r[0],
            "symbol": r[1],
            "sec_type": r[2],
            "exchange": r[3],
            "primary_exchange": r[4],
            "currency": r[5],
            "local_symbol": r[6],
            "trading_class": r[7],
        }
    return rows


def main():
    out_dir = os.environ.get(
        "HERMES_KANBAN_WORKSPACE",
        os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/workspace")
    )
    os.makedirs(out_dir, exist_ok=True)
    captured_at = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    cur = conn.cursor()

    universes = load_universes(cur)
    all_tickers = sorted(set(t for tickers in universes.values() for t in tickers))
    mappings = load_broker_mappings(cur, all_tickers)

    records = []
    for strategy_id in STRATEGIES:
        for ticker in universes.get(strategy_id, []):
            mapping = mappings.get(ticker)
            rec = {
                "universe_name": strategy_id,
                "normalized_ticker": ticker,
                "broker_symbol": broker_symbol(ticker),
                "con_id": mapping["con_id"] if mapping else None,
                "sec_type": mapping["sec_type"] if mapping else None,
                "exchange": mapping["exchange"] if mapping else None,
                "primary_exchange": mapping["primary_exchange"] if mapping else None,
                "currency": mapping["currency"] if mapping else None,
                "local_symbol": mapping["local_symbol"] if mapping else None,
                "trading_class": mapping["trading_class"] if mapping else None,
                "mapping_status": "mapped" if mapping else "missing",
                "captured_at": captured_at,
            }
            records.append(rec)

    conn.close()

    csv_path = os.path.join(out_dir, "universe_tickers_broker_mapping.csv")
    json_path = os.path.join(out_dir, "universe_tickers_broker_mapping.json")

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    with open(json_path, "w") as f:
        json.dump({
            "generated_at": captured_at,
            "source_universes": STRATEGIES,
            "broker_table": "bronze.ibkr_contracts",
            "total_records": len(records),
            "unique_tickers": len(all_tickers),
            "mapped_count": sum(1 for r in records if r["mapping_status"] == "mapped"),
            "missing_count": sum(1 for r in records if r["mapping_status"] == "missing"),
            "records": records,
        }, f, indent=2, default=str)

    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print(f"Records: {len(records)} | Unique tickers: {len(all_tickers)} | Mapped: {sum(1 for r in records if r['mapping_status'] == 'mapped')} | Missing: {sum(1 for r in records if r['mapping_status'] == 'missing')}")


if __name__ == "__main__":
    main()
