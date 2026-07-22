#!/usr/bin/env python3
"""Check silver.unified_prices for recent prices."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== silver.unified_prices schema sample ===")
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='silver' AND table_name='unified_prices' ORDER BY ordinal_position")
for row in cur.fetchall():
    print(f"  {row[0]} {row[1]}")

print("\n=== Latest prices for key tickers ===")
for ticker in ['SPY', 'QQQ', 'AAPL', 'TSLA', 'JEPQ', 'JEPI', 'VYM', 'IAU', 'GLD', 'TLT', '2800.HK', '0005.HK', 'META', 'NVDA', 'XLF', 'XLK']:
    cur.execute("SELECT ticker, date, close FROM silver.unified_prices WHERE ticker=%s ORDER BY date DESC LIMIT 1", (ticker,))
    row = cur.fetchone()
    if row:
        print(f"  {ticker}: {row[1]} {row[2]}")
    else:
        print(f"  {ticker}: not found")

conn.close()
