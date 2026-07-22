#!/usr/bin/env python3
"""Verify backfilled data."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== trade_executions count per PAPER strategy ===")
cur.execute("""
    SELECT strategy_id, COUNT(*) AS n, COUNT(pnl) AS closed, COALESCE(SUM(pnl),0) AS total_pnl
    FROM gold.trade_executions
    WHERE strategy_id IN (SELECT strategy_id FROM gold.strategy_registry WHERE execution_mode='PAPER' AND status='paper')
    GROUP BY strategy_id
    ORDER BY strategy_id
""")
for row in cur.fetchall():
    print(f"  {row[0]}: total={row[1]} closed={row[2]} pnl={row[3]}")

print("\n=== monthly returns sample ===")
cur.execute("SELECT strategy_id, year, month, return_pct FROM consumption.performance_monthly_returns ORDER BY strategy_id, year, month LIMIT 20")
for row in cur.fetchall():
    print(f"  {row}")

print("\n=== strategies signals current count per strategy ===")
cur.execute("SELECT strategy_id, COUNT(*) FROM consumption.strategies_signals_current GROUP BY strategy_id ORDER BY strategy_id")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

print("\n=== strategies signals current sample ===")
cur.execute("SELECT strategy_id, ticker, signal, signal_strength, current_price FROM consumption.strategies_signals_current LIMIT 10")
for row in cur.fetchall():
    print(f"  {row}")

conn.close()
