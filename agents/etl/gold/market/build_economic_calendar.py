#!/usr/bin/env python3
"""
build_economic_calendar.py
==========================
Populates gold.economic_calendar (created in db_setup/migrations/002) from
consumption.macro_calendar_dashboard — the FRED-derived release calendar.

Transform: the source is a per-DATE table of boolean flags (cpi_flag,
nfp_flag, fed_funds_flag, event_flag). This builder unpivots the UPCOMING
release days into named events the frontend renders:

    region='US', event='CPI', event_date='Jun 25', importance='High'

Only US events exist today (FRED is US macro). HK events need a separate
source (HKMA / HKEX calendar) that isn't ingested yet — this builder leaves
HK empty rather than fabricate it.

Importance mapping:
    CPI, NFP, Fed Funds → 'High'   (rate-path movers)
    EIA                 → 'Med'
    other flags         → 'Low'
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


DELETE_SQL = "DELETE FROM gold.economic_calendar WHERE region = 'US';"

# Unpivot the flag columns into one row per (date, event). Only keep dates
# from today forward (upcoming events) plus the last 3 days (recently
# released, still shown on the calendar). to_char formats the display string.
INSERT_SQL = """
WITH windowed AS (
    SELECT date, cpi_flag, nfp_flag, fed_funds_flag, event_flag
    FROM   consumption.macro_calendar_dashboard
    WHERE  date >= CURRENT_DATE - INTERVAL '3 days'
      AND  date <= CURRENT_DATE + INTERVAL '30 days'
),
unpivoted AS (
    SELECT date, 'CPI'        AS event, 'High' AS importance FROM windowed WHERE cpi_flag = 1
    UNION ALL
    SELECT date, 'Nonfarm Payrolls', 'High'                 FROM windowed WHERE nfp_flag = 1
    UNION ALL
    SELECT date, 'Fed Funds Rate',   'High'                 FROM windowed WHERE fed_funds_flag = 1
)
INSERT INTO gold.economic_calendar (region, event, event_date, importance, updated_at)
SELECT
    'US',
    event,
    to_char(date, 'Mon DD'),          -- 'Jun 25' display string
    importance,
    NOW()
FROM unpivoted
ORDER BY date;
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL)
            cur.execute(INSERT_SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.economic_calendar — {n} US event rows upserted")
        return n
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='economic_calendar',
                asset_class='macro',
                expected_max_staleness_hours=48,
                error=error,
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


if __name__ == "__main__":
    try:
        build()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
