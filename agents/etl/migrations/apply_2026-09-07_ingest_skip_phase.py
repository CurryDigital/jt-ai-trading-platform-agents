#!/usr/bin/env python3
"""t_589e846f: apply migration 2026-09-07_annual_pnl_audit_ingest_skip_phase.sql
via the shared ETL db module (avoids manual .env handling)."""
import os
import sys

ETL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ETL_ROOT, "shared", "scripts"))

from db import get_connection  # noqa: E402

SQL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "2026-09-07_annual_pnl_audit_ingest_skip_phase.sql",
)


def main():
    with open(SQL_PATH) as f:
        sql = f.read()
    conn = get_connection()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql)
    cur.execute(
        """
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'gold.strategy_backtest_runs_annual_pnl_audit'::regclass
          AND conname LIKE '%phase%';
        """
    )
    for row in cur.fetchall():
        print(row)
    cur.close()
    conn.close()
    print("migration applied")


if __name__ == "__main__":
    main()
