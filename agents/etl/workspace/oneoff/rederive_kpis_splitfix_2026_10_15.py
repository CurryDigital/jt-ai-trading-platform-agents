#!/usr/bin/env python3
"""
One-off: full-history re-derive of gold.kpis_metrics for the 7 split-fixed
tickers (kanban t_8866358c). Reuses the exact SQL from
gold/equity/build_equity_kpis.py, only swapping the 90-day rolling-window
filter for a ticker filter. silver.unified_prices and
silver.technical_indicators were already healed (split_factor_backfill +
recompute_ti_splitfix, 2026-10-15), so the join sources are clean.

Author: qr_etl  Date: 2026-10-15
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ETL = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
sys.path.insert(0, os.path.join(ETL, 'gold', 'equity'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
import build_equity_kpis as bek

TICKERS = sys.argv[1].split(',') if len(sys.argv) > 1 else ['CVNA', 'KLAC', 'DD', 'CRWD', 'MNST', 'APH', 'CTVA']

NEEDLE = "WHERE p.date >= CURRENT_DATE - INTERVAL '90 days'"
assert NEEDLE in bek.SQL, 'build_equity_kpis.SQL window filter not found — script changed?'
SQL = bek.SQL.replace(NEEDLE, "WHERE p.ticker = ANY(%(ts)s)")

conn = get_connection()
cur = conn.cursor()
cur.execute(SQL, {'ts': TICKERS})
print(f'OK gold.kpis_metrics full-history re-derive: {cur.rowcount} rows upserted for {len(TICKERS)} tickers')
conn.commit()
conn.close()
