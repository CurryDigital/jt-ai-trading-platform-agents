#!/usr/bin/env python3
"""Backfill diagnostic: inspect real strategies and data gaps."""
import os
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== gold.strategy_registry columns ===")
cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema='gold' AND table_name='strategy_registry'
    ORDER BY ordinal_position;
""")
for row in cur.fetchall():
    print(f"  {row[0]} {row[1]}")

print("\n=== gold.strategy_registry (promoted strategies) ===")
cur.execute("""
    SELECT *
    FROM gold.strategy_registry
    ORDER BY status, strategy_id;
""")
for row in cur.fetchall():
    print(f"  {row}")

conn.close()
