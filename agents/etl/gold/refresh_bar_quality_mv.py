#!/usr/bin/env python3
"""Refresh gold.v_us_equity_bar_quality (materialized view).

Context: kanban t_96e90169 (2026-11-03). The original plain view forced a
parallel seq scan of gold.daily_ohlcv (4.3M rows) on EVERY
/api/system/freshness poll; frontend 10s aborts left the queries running,
they piled up (11 leaders + parallel workers) and saturated the burstable
RDS, starving every other endpoint. Swapped to a materialized view
(same name, same columns) refreshed by this script on a cron.

Schedule: after pipeline A (08:30 UTC) and after yf_us_postclose_topup
(22:30 UTC) so the DQ signal tracks both daily ingest passes.
Exit 0 on success, 1 on failure (cron surfaces status).
"""
import os
import sys
import time

import psycopg2

MV = "gold.v_us_equity_bar_quality"


def main() -> int:
    host = os.environ["AIRTRADING_DB_HOST"]
    user = os.environ["AIRTRADING_DB_USER"]
    password = os.environ["AIRTRADING_DB_PASSWORD"]
    t0 = time.time()
    conn = psycopg2.connect(
        host=host, user=user, password=password, dbname="aitrading",
        sslmode="require", connect_timeout=15,
        application_name="refresh_bar_quality_mv",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET statement_timeout = '300s'")
    cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {MV}")
    cur.execute(f"SELECT COUNT(*), MAX(date) FROM {MV}")
    rows, latest = cur.fetchone()
    conn.close()
    print(f"✅ {MV} refreshed: {rows} rows, latest_suspect={latest}, "
          f"{time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - cron must surface any failure
        print(f"❌ refresh failed: {exc}", file=sys.stderr)
        sys.exit(1)
