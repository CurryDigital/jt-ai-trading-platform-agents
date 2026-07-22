#!/usr/bin/env python3
"""Get detailed schemas of paper_trades_synthetic and strategies_signals_current."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

for table in ['gold.paper_trades_synthetic', 'consumption.strategies_signals_current']:
    print(f"\n=== {table} schema ===")
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (table.split('.')[0], table.split('.')[1]))
    for row in cur.fetchall():
        print(f"  {row[0]} {row[1]} null={row[2]}")

print("\n=== Distinct strategies in paper_trades_synthetic ===")
cur.execute("SELECT strategy_id, COUNT(*) FROM gold.paper_trades_synthetic GROUP BY strategy_id ORDER BY strategy_id")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

print("\n=== Date range in paper_trades_synthetic ===")
cur.execute("""
    SELECT strategy_id, MIN(entry_date), MAX(entry_date), MIN(exit_date), MAX(exit_date)
    FROM gold.paper_trades_synthetic
    GROUP BY strategy_id
    ORDER BY strategy_id
""")
for row in cur.fetchall():
    print(f"  {row[0]}: entry {row[1]}..{row[2]}, exit {row[3]}..{row[4]}")

print("\n=== Strategies in consumption.strategies_signals_current ===")
cur.execute("SELECT strategy_id, COUNT(*) FROM consumption.strategies_signals_current GROUP BY strategy_id ORDER BY strategy_id")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.close()
