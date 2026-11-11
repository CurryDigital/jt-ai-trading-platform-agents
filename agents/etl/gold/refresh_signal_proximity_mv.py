#!/usr/bin/env python3
"""Refresh gold.v_signal_proximity (materialized view).

Context: kanban t_30ec2517 (2026-11-03). The original plain view was polled
every 300s by GET /api/agents/paper/signal-proximity; each poll re-planned a
20k-row seq scan + sort over silver.unified_earnings plus a windowed
double-sort over silver.unified_prices (~1.8s cold — same incident shape as
t_96e90169). Swapped to a materialized view (same name, same columns) via
migrations/2026-11-03_signal_proximity_materialized.sql; this script keeps
it fresh.

Schedule (cron qr_etl.signal_proximity_mv_refresh, "40 0,9,23 * * *"):
  00:40 UTC — CURRENT_DATE rollover (days_until_earnings, seasonal month)
  09:40 UTC — after pipeline A 08:30 (unified_earnings, unified_prices)
  23:40 UTC — after yf_us_postclose_topup 22:30 + regime_wf 23:15
Exit 0 on success, 1 on failure (cron surfaces status).
"""
import os
import sys
import time

import psycopg2

MV = "gold.v_signal_proximity"


def main() -> int:
    host = os.environ["AIRTRADING_DB_HOST"]
    user = os.environ["AIRTRADING_DB_USER"]
    password = os.environ["AIRTRADING_DB_PASSWORD"]
    t0 = time.time()
    conn = psycopg2.connect(
        host=host, user=user, password=password, dbname="aitrading",
        sslmode="require", connect_timeout=15,
        application_name="refresh_signal_proximity_mv",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET statement_timeout = '300s'")
    cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MV}")
    cur.execute(f"SELECT COUNT(*), MAX(last_updated) FROM {MV}")
    rows, latest = cur.fetchone()
    conn.close()
    print(f"✅ {MV} refreshed: {rows} rows, last_updated={latest}, "
          f"{time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - cron must surface any failure
        print(f"❌ refresh failed: {exc}", file=sys.stderr)
        sys.exit(1)
