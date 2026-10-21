#!/usr/bin/env python3
"""
DATA_FIX (goal gold_daily_ohlcv_gap_remediation_v1, step 2c):
Mirror silver -> gold for every (ticker, date) present close-valid in
silver.unified_prices but absent from gold.daily_ohlcv.

Per GAP_AUDIT.md (step 2): pure INSERT ... SELECT, ON CONFLICT DO NOTHING,
rows tagged primary_source='gapfix_v1_20261014:<orig primary_source>'.
Batched per month to checkpoint progress and keep transactions small.

Run AFTER silver merge (clean_unified_prices.py) has restated silver.

Usage: heal_gold_from_silver_v1.py [--dry-run]
Run with etl-venv or /usr/bin/python3 (psycopg2 only).
"""
import os, sys, argparse

ETL = os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl")
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

TAG = "gapfix_v1_20261014"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    print("counting healable rows (silver close-valid, absent from gold) ...")
    cur.execute("""
        SELECT count(*) FROM silver.unified_prices s
        WHERE s.open IS NOT NULL AND s.high IS NOT NULL
          AND s.low IS NOT NULL AND s.close IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM gold.daily_ohlcv g
                          WHERE g.ticker = s.ticker AND g.date = s.date)
    """)
    total = cur.fetchone()[0]
    print(f"  healable rows: {total:,}")
    if args.dry_run or total == 0:
        conn.close()
        return

    cur.execute("""
        SELECT DISTINCT date_trunc('month', date)::date
        FROM silver.unified_prices s
        WHERE s.open IS NOT NULL AND s.high IS NOT NULL
          AND s.low IS NOT NULL AND s.close IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM gold.daily_ohlcv g
                          WHERE g.ticker = s.ticker AND g.date = s.date)
        ORDER BY 1
    """)
    months = [r[0] for r in cur.fetchall()]
    print(f"  months to heal: {len(months)} ({months[0]} .. {months[-1]})")

    inserted_total = 0
    for m in months:
        cur.execute("""
            INSERT INTO gold.daily_ohlcv
                (ticker, asset_class, market, date, open, high, low, close,
                 volume, adjusted_close, returns_1d, primary_source,
                 created_at, updated_at)
            SELECT s.ticker, s.asset_class, s.market, s.date,
                   s.open, s.high, s.low, s.close, s.volume,
                   s.adjusted_close, s.returns_1d,
                   %s || ':' || COALESCE(s.primary_source, 'unknown'),
                   NOW(), NOW()
            FROM silver.unified_prices s
            WHERE s.date >= %s AND s.date < %s + INTERVAL '1 month'
              AND s.open IS NOT NULL AND s.high IS NOT NULL
              AND s.low IS NOT NULL AND s.close IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM gold.daily_ohlcv g
                              WHERE g.ticker = s.ticker AND g.date = s.date)
            ON CONFLICT (ticker, date) DO NOTHING
        """, (TAG, m, m))
        n = cur.rowcount
        conn.commit()
        inserted_total += n
        if n:
            print(f"  {m}: +{n:,} rows (cumulative {inserted_total:,})")

    print(f"DONE: {inserted_total:,} rows inserted into gold.daily_ohlcv, tag={TAG}")
    conn.close()

if __name__ == '__main__':
    main()
