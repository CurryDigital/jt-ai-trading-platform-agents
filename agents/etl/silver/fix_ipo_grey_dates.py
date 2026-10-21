#!/usr/bin/env python3
"""
Silver: repair grey-market (暗盤) fields on unified_ipo_calendar.

1) Recycled-ticker grey misallocation (2026-08-30, kanban t_3ad38fa3):
   the etnet grey scrape updates by ticker only, so for tickers with multiple
   calendar listings the recent listing's grey_close lands on ALL rows.
   etnet only covers the most recent listing (~12mo retention), so clear grey
   fields on every non-latest listing of a multi-listing ticker.

2) grey_session_date = last ^HSI trading day strictly before listing_date.
   Recomputed from silver.unified_prices ('^HSI') so it tracks feed refreshes
   (stale ^HSI at 2026-08-21 gave 3223.HK grey_session_date 2026-08-21 instead
   of 2026-08-24).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection


def run():
    conn = get_connection()
    cur = conn.cursor()

    # 1) clear grey on non-latest listings of recycled tickers
    cur.execute("""
        WITH dup AS (
            SELECT ticker, MAX(listing_date) AS latest_ld
            FROM silver.unified_ipo_calendar
            GROUP BY ticker HAVING count(*) > 1
        )
        UPDATE silver.unified_ipo_calendar c
        SET grey_close = NULL, grey_session_date = NULL, grey_source = NULL,
            updated_at = NOW()
        FROM dup
        WHERE c.ticker = dup.ticker
          AND c.listing_date < dup.latest_ld
          AND (c.grey_close IS NOT NULL OR c.grey_session_date IS NOT NULL
               OR c.grey_source IS NOT NULL)
    """)
    print(f"recycled-ticker grey rows cleared: {cur.rowcount}")

    # 2) recompute grey_session_date from ^HSI trading calendar
    cur.execute("""
        WITH hk_days AS (
            SELECT DISTINCT date FROM silver.unified_prices WHERE ticker = '^HSI'
        )
        UPDATE silver.unified_ipo_calendar c
        SET grey_session_date = (
                SELECT max(d.date) FROM hk_days d WHERE d.date < c.listing_date
            ), updated_at = NOW()
        WHERE c.grey_close IS NOT NULL
    """)
    print(f"grey_session_date recomputed rows: {cur.rowcount}")

    conn.commit()

    cur.execute("""
        SELECT ticker, listing_date, offer_price, grey_close, grey_session_date, grey_source
        FROM silver.unified_ipo_calendar
        WHERE ticker IN ('1989.HK', '3223.HK') ORDER BY ticker, listing_date
    """)
    for r in cur.fetchall():
        print(r)
    cur.execute("SELECT count(*), count(grey_close), count(grey_session_date) FROM silver.unified_ipo_calendar")
    print('calendar totals (rows, grey_close, grey_session_date):', cur.fetchone())
    conn.close()


if __name__ == "__main__":
    run()
