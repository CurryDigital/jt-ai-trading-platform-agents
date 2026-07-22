#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== trade_executions rows by strategy ===")
cur.execute("""
    SELECT strategy_id, COUNT(*) as n, SUM(pnl) as total_pnl, MIN(executed_at) as first_trade, MAX(executed_at) as last_trade
    FROM gold.trade_executions
    WHERE execution_mode = 'PAPER_TRADING'
    GROUP BY strategy_id
    ORDER BY strategy_id
""")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} trades, total_pnl=${row[2]}, first={row[3]}, last={row[4]}")

print("\n=== strategies with 0 trades ===")
cur.execute("""
    SELECT s.strategy_id
    FROM gold.strategy_registry s
    WHERE s.execution_mode='PAPER' AND s.status='paper'
      AND NOT EXISTS (SELECT 1 FROM gold.trade_executions t WHERE t.strategy_id = s.strategy_id)
""")
for row in cur.fetchall():
    print(f"  {row[0]}")

print("\n=== strategies_signals_current rows by strategy ===")
cur.execute("""
    SELECT strategy_id, COUNT(*) as n, MAX(updated_at) as latest
    FROM consumption.strategies_signals_current
    GROUP BY strategy_id
    ORDER BY strategy_id
""")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} signals, latest={row[2]}")

print("\n=== performance_monthly_returns sample ===")
cur.execute("SELECT * FROM consumption.performance_monthly_returns LIMIT 20")
for row in cur.fetchall():
    print(f"  {row}")

print("\n=== performance_monthly_returns rows by strategy ===")
cur.execute("""
    SELECT strategy_id, COUNT(*) as n, SUM(total_pnl) as total_pnl
    FROM consumption.performance_monthly_returns
    GROUP BY strategy_id
    ORDER BY strategy_id
""")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} months, total_pnl=${row[2]}")

print("\n=== check consumption objects ===")
cur.execute("""
    SELECT table_schema, table_name, table_type
    FROM information_schema.tables
    WHERE table_schema='consumption'
      AND (table_name ILIKE 'performance_monthly_returns' OR table_name ILIKE 'strategies_signals_current')
""")
for row in cur.fetchall():
    print(f"  {row[0]}.{row[1]} ({row[2]})")

conn.close()
