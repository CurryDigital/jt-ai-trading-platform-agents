#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== HK_Quality_BlueChips pnl distribution ===")
cur.execute("""
    SELECT COUNT(*) as total, 
           SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winners,
           SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losers,
           SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END) as zero,
           SUM(pnl) as total_pnl
    FROM gold.trade_executions WHERE strategy_id = 'HK_Quality_BlueChips'
""")
print(cur.fetchone())

print("\n=== HK_Quality_BlueChips sample trades ===")
cur.execute("""
    SELECT strategy_id, ticker, side, quantity, price, entry_price, exit_price, pnl, pnl_pct, status, executed_at
    FROM gold.trade_executions WHERE strategy_id = 'HK_Quality_BlueChips'
    ORDER BY executed_at LIMIT 10
""")
for row in cur.fetchall():
    print(row)

print("\n=== US_STK_GOLD_HDG_05 trades ===")
cur.execute("SELECT * FROM gold.trade_executions WHERE strategy_id = 'US_STK_GOLD_HDG_05'")
for row in cur.fetchall():
    print(row)

print("\n=== HK_LowVol_Weekly trades ===")
cur.execute("""
    SELECT strategy_id, ticker, side, quantity, price, entry_price, exit_price, pnl, status, executed_at
    FROM gold.trade_executions WHERE strategy_id = 'HK_LowVol_Weekly'
""")
for row in cur.fetchall():
    print(row)

conn.close()
