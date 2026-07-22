#!/usr/bin/env python3
"""Get exact trade_executions schema and current rows."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== gold.trade_executions schema ===")
cur.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'gold' AND table_name = 'trade_executions'
    ORDER BY ordinal_position
""")
for row in cur.fetchall():
    print(f"  {row[0]} {row[1]} null={row[2]}")

print("\n=== Current trade_executions rows ===")
cur.execute("SELECT * FROM gold.trade_executions LIMIT 10")
for row in cur.fetchall():
    print(f"  {row}")

print("\n=== Count by strategy ===")
cur.execute("SELECT strategy_id, COUNT(*) FROM gold.trade_executions GROUP BY strategy_id ORDER BY strategy_id")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.close()
