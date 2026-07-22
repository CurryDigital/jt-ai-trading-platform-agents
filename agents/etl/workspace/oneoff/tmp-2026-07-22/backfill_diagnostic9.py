#!/usr/bin/env python3
"""Get signal file paths from registry."""
import sys, os, json
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute("""
    SELECT strategy_id, signal_file_path
    FROM gold.strategy_registry
    WHERE execution_mode='PAPER' AND status='paper'
    ORDER BY strategy_id
""")
for sid, path in cur.fetchall():
    exists = os.path.exists(path) if path else False
    print(f"{sid}: {path} exists={exists}")
    if exists:
        try:
            with open(path) as f:
                text = f.read()
            print(f"  first 200 chars: {text[:200]}")
        except Exception as e:
            print(f"  error: {e}")

conn.close()
