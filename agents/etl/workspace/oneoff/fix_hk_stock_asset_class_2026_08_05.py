#!/usr/bin/env python3
"""One-off fix (kanban t_b735bbbd): normalize asset_class 'HK Stock' -> 'STOCK'
in gold.asset_registry, then backfill bronze.yf_prices for the 29 stale
hk_stk_52wh_mom_04 universe tickers.

Root cause: bronze/yfinance/ingest_yfinance_prices.py get_active_tickers()
filters asset_class IN ('STOCK','ETF','INDEX'); 21 HK rows carried the
nonstandard 'HK Stock' label from one-off batch scripts and were silently
excluded from every daily ingest since 2026-07-17.
"""
import sys, os
os.chdir(os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl'))
sys.path.insert(0, 'shared/scripts')
sys.path.insert(0, 'bronze/yfinance')

from db import get_connection

STALE_TICKERS = [
    '0001.HK','0002.HK','0003.HK','0005.HK','0006.HK','0016.HK','0027.HK',
    '0388.HK','0700.HK','0836.HK','0939.HK','0941.HK','1038.HK','1299.HK',
    '1398.HK','1928.HK','2318.HK','2388.HK','2628.HK',
    '0088.HK','0197.HK','0228.HK','0506.HK','0838.HK','0978.HK','1044.HK',
    '3868.HK','6190.HK','9616.HK',
]

# Step 1: normalize asset_class
conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT ticker, is_active FROM gold.asset_registry WHERE asset_class='HK Stock' ORDER BY ticker")
rows = cur.fetchall()
print(f"'HK Stock' rows before normalize: {len(rows)}")
for t, a in rows:
    print(f"  {t} active={a}")
cur.execute("UPDATE gold.asset_registry SET asset_class='STOCK' WHERE asset_class='HK Stock'")
print(f"normalized rows: {cur.rowcount}")
conn.commit()
conn.close()

# Step 2: backfill bronze (days_back=25 covers the 2026-07-17 gap with margin)
from ingest_yfinance_prices import ingest_yf_prices
ingest_yf_prices(tickers=STALE_TICKERS, days_back=25)
print("DONE")
