#!/usr/bin/env python3
"""
Gold Portfolio: Account NAV Daily
Reads from: gold.ibkr_account_summary, gold.portfolio_snapshots
Writes to:  gold.account_nav_daily
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_UPSERT_LIVE = """
INSERT INTO gold.account_nav_daily (book, as_of_date, equity, pnl)
SELECT
    'live'::varchar(10) AS book,
    CURRENT_DATE AS as_of_date,
    net_liquidation AS equity,
    0 AS pnl
FROM gold.ibkr_account_summary
WHERE account IS NOT NULL
  AND account <> ''
  AND net_liquidation IS NOT NULL
ON CONFLICT (book, as_of_date) DO UPDATE SET
    equity = EXCLUDED.equity,
    pnl    = EXCLUDED.pnl;
"""

SQL_UPSERT_SNAPSHOT = """
-- Paper snapshots only.  Live IBKR NAV is sourced above from
-- gold.ibkr_account_summary.net_liquidation and must NOT be overwritten
-- by a stale positions-only portfolio snapshot.
INSERT INTO gold.account_nav_daily (book, as_of_date, equity, pnl)
SELECT
    portfolio_type AS book,
    snapshot_date AS as_of_date,
    COALESCE(total_value, 0) AS equity,
    COALESCE(daily_pnl, 0) AS pnl
FROM gold.portfolio_snapshots
WHERE portfolio_type = 'paper'
  AND total_value IS NOT NULL
ON CONFLICT (book, as_of_date) DO UPDATE SET
    equity = EXCLUDED.equity,
    pnl    = EXCLUDED.pnl;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_UPSERT_LIVE)
    live_rows = cur.rowcount
    cur.execute(SQL_UPSERT_SNAPSHOT)
    snap_rows = cur.rowcount
    conn.commit()
    conn.close()
    print(f"✅ gold.account_nav_daily synced: live={live_rows} snapshot={snap_rows} rows")

if __name__ == "__main__":
    run()
