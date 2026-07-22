#!/usr/bin/env python3
"""One-off remediation: delete CASH rows from ticker-level trade/signal tables.

Canonical CASH representation: CASH is a portfolio cash-bucket placeholder, not a
tradeable ticker. It is excluded from ticker-level tables; 100% cash is represented
implicitly by the absence of security positions.
"""
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.hermes/profiles/qr_etl/env/etl.env"))


TABLES = [
    "gold.trade_executions",
    "consumption.strategies_signals_current",
    "gold.paper_trades_synthetic",
    "consumption.signal_logs",
    "gold.strategy_ticker_scores",
]

TICKER_COLUMNS = {
    "gold.trade_executions": "ticker",
    "consumption.strategies_signals_current": "ticker",
    "gold.paper_trades_synthetic": "ticker",
    "consumption.signal_logs": "ticker",
    "gold.strategy_ticker_scores": "ticker",
}


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def count_cash_rows(cur, table):
    col = TICKER_COLUMNS.get(table, "ticker")
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = 'CASH'")
    return cur.fetchone()[0]


def delete_cash_rows(cur, table):
    col = TICKER_COLUMNS.get(table, "ticker")
    cur.execute(f"DELETE FROM {table} WHERE {col} = 'CASH'")
    return cur.rowcount


def main():
    conn = get_conn()
    cur = conn.cursor()

    print("=== CASH remediation pre-cleanup counts ===")
    pre_counts = {}
    for table in TABLES:
        cnt = count_cash_rows(cur, table)
        pre_counts[table] = cnt
        print(f"  {table}: {cnt}")

    print("\n=== Deleting CASH rows ===")
    deleted = {}
    for table in TABLES:
        n = delete_cash_rows(cur, table)
        deleted[table] = n
        print(f"  {table}: deleted {n}")

    conn.commit()

    print("\n=== CASH remediation post-cleanup counts ===")
    for table in TABLES:
        cnt = count_cash_rows(cur, table)
        print(f"  {table}: {cnt}")

    cur.close()
    conn.close()

    total_deleted = sum(deleted.values())
    print(f"\nTotal CASH rows deleted: {total_deleted}")
    if total_deleted == 0:
        print("No CASH rows found; nothing to clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
