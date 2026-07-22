#!/usr/bin/env python3
"""Check signal logs for missing strategies."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

missing = ['ETF_Covered_Call_Income_Rotation', 'ETF_Multi_Asset_Tactical_Allocation', 'HK_LowVol_Weekly', 'HK_LowVol_TrendFilter_Weekly']

print("=== signal_logs for missing strategies ===")
for sid in missing:
    cur.execute("""
        SELECT strategy_id, MIN(signal_date), MAX(signal_date), COUNT(*)
        FROM consumption.signal_logs
        WHERE strategy_id = %s
        GROUP BY strategy_id
    """, (sid,))
    rows = cur.fetchall()
    if rows:
        for row in rows:
            print(f"  {row[0]}: {row[1]}..{row[2]} count={row[3]}")
    else:
        print(f"  {sid}: no signal_logs")

print("\n=== signal_logs count for all PAPER strategies ===")
cur.execute("""
    SELECT r.strategy_id, COUNT(sl.*) as n
    FROM gold.strategy_registry r
    LEFT JOIN consumption.signal_logs sl ON sl.strategy_id = r.strategy_id
    WHERE r.execution_mode='PAPER' AND r.status='paper'
    GROUP BY r.strategy_id
    ORDER BY r.strategy_id
""")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.close()
