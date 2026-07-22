#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== paper_trades_synthetic for HK_Quality_BlueChips sample ===")
cur.execute("""
    SELECT strategy_id, ticker, direction, entry_date, exit_date, entry_price, exit_price, pnl, pnl_pct, status
    FROM gold.paper_trades_synthetic
    WHERE strategy_id = 'HK_Quality_BlueChips'
    ORDER BY entry_date LIMIT 10
""")
for row in cur.fetchall():
    print(row)

print("\n=== signal_logs for HK_Quality_BlueChips sample ===")
cur.execute("""
    SELECT strategy_id, signal_date, ticker, signal_type, signal_criteria, logged_at
    FROM consumption.signal_logs
    WHERE strategy_id = 'HK_Quality_BlueChips'
    ORDER BY signal_date, ticker LIMIT 10
""")
for row in cur.fetchall():
    print(row)

print("\n=== unified_prices for 0001.HK recent dates ===")
cur.execute("""
    SELECT ticker, date, close FROM silver.unified_prices
    WHERE ticker = '0001.HK' AND date >= '2026-07-01'
    ORDER BY date LIMIT 20
""")
for row in cur.fetchall():
    print(row)

conn.close()
