#!/usr/bin/env python3
"""
One-off: full-history recompute of silver.technical_indicators for the 7
split-fixed tickers (kanban t_8866358c). Reuses compute_for_ticker + UPSERT_SQL
from silver/compute_technical_indicators.py so indicator math is identical to
the nightly pipeline; only the load window differs (full history vs 420d
warmup + 45d write tail).

Author: qr_etl  Date: 2026-10-15
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ETL = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
sys.path.insert(0, os.path.join(ETL, 'silver'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
import compute_technical_indicators as cti
from psycopg2.extras import execute_values

TICKERS = sys.argv[1].split(',') if len(sys.argv) > 1 else ['CVNA', 'KLAC', 'DD', 'CRWD', 'MNST', 'APH', 'CTVA']

conn = get_connection()
cur = conn.cursor()
cur.execute("""
    SELECT ticker, date, high, low, close, volume
    FROM silver.unified_prices
    WHERE ticker = ANY(%s) AND close > 0 AND close IS NOT NULL
    ORDER BY ticker, date""", (TICKERS,))
rows = cur.fetchall()
by_ticker = {}
for r in rows:
    by_ticker.setdefault(r[0], []).append(r[1:])

payload = []
for t, trows in by_ticker.items():
    vals = cti.compute_for_ticker(trows)
    for v in vals:
        payload.append((t,) + v[1:])
    print(f'  {t}: {len(trows)} rows recomputed')

execute_values(cur, cti.UPSERT_SQL, payload,
    template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
    page_size=1000)
conn.commit()
print(f'OK silver.technical_indicators full-history recompute: {len(payload)} rows across {len(by_ticker)} tickers')
conn.close()
