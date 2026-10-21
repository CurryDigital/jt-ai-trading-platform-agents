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
-- t_65d96f4a: live book equity is the account BASE currency (HKD for
-- DUP825942) — labeled via currency col; equity_usd converted at ingest
-- time via the shared fx layer. History was tagged (not rewritten) by
-- migration 2026-10-09_fx_currency_labeling.sql.
INSERT INTO gold.account_nav_daily (book, as_of_date, equity, pnl, currency, equity_usd, fx_rate, fx_date)
SELECT
    'live'::varchar(10) AS book,
    CURRENT_DATE AS as_of_date,
    net_liquidation AS equity,
    0 AS pnl,
    COALESCE(base_currency, 'HKD') AS currency,
    net_liquidation_usd AS equity_usd,
    fx_rate,
    fx_date
FROM gold.ibkr_account_summary
WHERE account IS NOT NULL
  AND account <> ''
  AND net_liquidation IS NOT NULL
ON CONFLICT (book, as_of_date) DO UPDATE SET
    equity = EXCLUDED.equity,
    pnl    = EXCLUDED.pnl,
    currency = EXCLUDED.currency,
    equity_usd = EXCLUDED.equity_usd,
    fx_rate = EXCLUDED.fx_rate,
    fx_date = EXCLUDED.fx_date;
"""

SQL_UPSERT_SNAPSHOT = """
-- Paper snapshots only.  Live IBKR NAV is sourced above from
-- gold.ibkr_account_summary.net_liquidation and must NOT be overwritten
-- by a stale positions-only portfolio snapshot.
-- Paper book is SIM USD: currency='USD', equity_usd = equity, fx_rate = 1.
INSERT INTO gold.account_nav_daily (book, as_of_date, equity, pnl, currency, equity_usd, fx_rate, fx_date)
SELECT
    portfolio_type AS book,
    snapshot_date AS as_of_date,
    COALESCE(total_value, 0) AS equity,
    COALESCE(daily_pnl, 0) AS pnl,
    'USD' AS currency,
    COALESCE(total_value, 0) AS equity_usd,
    1 AS fx_rate,
    snapshot_date AS fx_date
FROM gold.portfolio_snapshots
WHERE portfolio_type = 'paper'
  AND total_value IS NOT NULL
ON CONFLICT (book, as_of_date) DO UPDATE SET
    equity = EXCLUDED.equity,
    pnl    = EXCLUDED.pnl,
    currency = EXCLUDED.currency,
    equity_usd = EXCLUDED.equity_usd,
    fx_rate = EXCLUDED.fx_rate,
    fx_date = EXCLUDED.fx_date;
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
