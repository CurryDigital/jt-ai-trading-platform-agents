#!/usr/bin/env python3
"""Backfill diagnostic: inspect signal files, schemas, and consumption views."""
import os, json, sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== gold.trade_executions columns ===")
cur.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema='gold' AND table_name='trade_executions'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f"  {row[0]} {row[1]} null={row[2]}")

print("\n=== gold.strategy_signals columns ===")
cur.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_schema='gold' AND table_name='strategy_signals'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f"  {row[0]} {row[1]} null={row[2]}")

print("\n=== gold.trade_executions all rows ===")
cur.execute("SELECT * FROM gold.trade_executions LIMIT 20;")
for row in cur.fetchall():
    print(f"  {row}")

print("\n=== gold.strategy_signals all rows ===")
cur.execute("SELECT * FROM gold.strategy_signals LIMIT 20;")
for row in cur.fetchall():
    print(f"  {row}")

print("\n=== Live signal files for PAPER strategies ===")
base = '/home/ubuntu/.hermes/profiles/qr_research/workspace'
cur.execute("""
    SELECT strategy_id, signal_file_path
    FROM gold.strategy_registry
    WHERE execution_mode='PAPER' AND status='paper';
""")
for sid, path in cur.fetchall():
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            print(f"  {sid}: {type(data).__name__}, keys={list(data.keys())[:5] if isinstance(data, dict) else 'N/A'}")
        except Exception as e:
            print(f"  {sid}: ERROR {e}")
    else:
        print(f"  {sid}: path missing or None: {path}")

conn.close()
