#!/usr/bin/env python3
"""
Silver: build unified_ipo_performance from unified_ipo_calendar + unified_prices.

One row per (ticker, listing_date) — recycled tickers (e.g. 9868.HK, 1989.HK)
get one performance row per calendar listing.

return_1d = offer -> first-day close; return_1m/3m = offer -> close ~21/63
trading days later; return_10d/20d = offer -> close on the 10th/20th trading
day (rows[9]/rows[19], matching the API day-20 lateral OFFSET 19 — kanban
t_e71cffde, 2026-09-02). All returns are decimal fractions (0.10 = 10%).

For recycled tickers the price window for an earlier listing is capped at the
next listing_date of the same ticker, so returns never cross into the successor
company's price history (2026-08-30, kanban t_3ad38fa3).

Full-rebuild semantics: the in-scope slice (HK tickers, listing_date >=
2015-01-01) is DELETEd and re-inserted on every run, inside one transaction.
Upsert-only rebuilds left stale rows behind whenever a listing stopped
qualifying (e.g. recycled-ticker first listings with zero price bars in their
capped window kept successor-price rows written before the cap fix —
kanban t_3791b6f2: 2451.HK/2023-10-12, 2545.HK/2024-07-03).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection


def run():
    conn = get_connection()
    cur = conn.cursor()
    # Full rebuild of the in-scope slice (same transaction as the inserts
    # below): purges rows for listings that no longer qualify.
    cur.execute("""
        DELETE FROM silver.unified_ipo_performance
        WHERE ticker LIKE '%%.HK' AND listing_date >= '2015-01-01'
    """)
    n_deleted = cur.rowcount
    cur.execute("""
        SELECT ticker, listing_date, offer_price
        FROM silver.unified_ipo_calendar
        WHERE ticker LIKE '%.HK' AND listing_date >= '2015-01-01'
        ORDER BY ticker, listing_date
    """)
    ipos = cur.fetchall()

    # next listing date per ticker (for capping recycled-ticker windows)
    next_listing = {}
    by_ticker = {}
    for tk, ld, _ in ipos:
        by_ticker.setdefault(tk, []).append(ld)
    for tk, dates in by_ticker.items():
        dates.sort()
        for i, d in enumerate(dates[:-1]):
            next_listing[(tk, d)] = dates[i + 1]

    n_ok = n_nopx = 0
    for ticker, ldate, offer in ipos:
        cap = next_listing.get((ticker, ldate))
        if cap:
            cur.execute("""
                SELECT date, open, high, low, close, volume
                FROM silver.unified_prices
                WHERE ticker = %s AND date >= %s AND date < %s
                ORDER BY date
                LIMIT 70
            """, (ticker, ldate, cap))
        else:
            cur.execute("""
                SELECT date, open, high, low, close, volume
                FROM silver.unified_prices
                WHERE ticker = %s AND date >= %s
                ORDER BY date
                LIMIT 70
            """, (ticker, ldate))
        rows = cur.fetchall()
        if not rows:
            n_nopx += 1
            continue
        fd = rows[0]
        fd_date, fd_o, fd_h, fd_l, fd_c, fd_v = fd

        def close_at(n):
            return float(rows[n][4]) if len(rows) > n else None

        offer_f = float(offer) if offer is not None else None
        base = offer_f if offer_f else None
        r1d = (float(fd_c) / base - 1) if base else None
        c10 = close_at(9)
        c20 = close_at(19)
        c1m = close_at(21)
        c3m = close_at(63)
        r10d = (c10 / base - 1) if (base and c10) else None
        r20d = (c20 / base - 1) if (base and c20) else None
        r1m = (c1m / base - 1) if (base and c1m) else None
        r3m = (c3m / base - 1) if (base and c3m) else None
        cur.execute("""
            INSERT INTO silver.unified_ipo_performance
                (ticker, listing_date, offer_price, first_day_date, first_day_open,
                 first_day_high, first_day_low, first_day_close, first_day_volume,
                 return_1d, return_10d, return_20d, return_1m, return_3m)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (ticker, listing_date) DO UPDATE SET
                offer_price      = EXCLUDED.offer_price,
                first_day_date   = EXCLUDED.first_day_date,
                first_day_open   = EXCLUDED.first_day_open,
                first_day_high   = EXCLUDED.first_day_high,
                first_day_low    = EXCLUDED.first_day_low,
                first_day_close  = EXCLUDED.first_day_close,
                first_day_volume = EXCLUDED.first_day_volume,
                return_1d        = EXCLUDED.return_1d,
                return_10d       = EXCLUDED.return_10d,
                return_20d       = EXCLUDED.return_20d,
                return_1m        = EXCLUDED.return_1m,
                return_3m        = EXCLUDED.return_3m
        """, (ticker, ldate, offer_f, fd_date,
              float(fd_o), float(fd_h), float(fd_l), float(fd_c),
              int(float(fd_v)) if fd_v is not None else None,
              r1d, r10d, r20d, r1m, r3m))
        n_ok += 1
    conn.commit()
    cur.execute("""SELECT count(*), count(return_1d), count(return_10d),
                          count(return_20d), count(return_1m), count(return_3m)
                   FROM silver.unified_ipo_performance""")
    print('perf state (rows, r1d, r10d, r20d, r1m, r3m):', cur.fetchone())
    print(f'deleted_stale_scope={n_deleted} built={n_ok} no_price_data={n_nopx}')
    conn.close()


if __name__ == "__main__":
    run()
