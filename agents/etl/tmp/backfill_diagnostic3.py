#!/usr/bin/env python3
import json, os, sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

for sid in ['ETF_US_Sector_Relative_Momentum', 'US_STK_MOM_LDR_01', 'HK_Quality_BlueChips']:
    path = f'/home/ubuntu/.hermes/profiles/qr_research/workspace/{sid}_live_signals.json'
    if not os.path.exists(path):
        print(f"{sid}: file missing")
        continue
    with open(path) as f:
        data = json.load(f)
    print(f"\n=== {sid} ===")
    print(f"generated_at: {data.get('generated_at')}")
    signals = data.get('signals', [])
    print(f"signals_type: {type(signals).__name__}")
    if isinstance(signals, dict):
        print(f"signals_keys: {list(signals.keys())[:10]}")
        for k, v in list(signals.items())[:3]:
            print(f"  {k}: {v}")
    elif isinstance(signals, list):
        print(f"num_signals: {len(signals)}")
        for s in signals[:3]:
            print(f"  {s}")
    else:
        print(f"signals: {signals}")

print("\n=== bronze/gold tables with strategy_id ===")
cur.execute("""
    SELECT table_schema, table_name, column_name, data_type
    FROM information_schema.columns
    WHERE column_name='strategy_id' AND table_schema IN ('bronze', 'silver', 'gold', 'consumption')
    ORDER BY table_schema, table_name, ordinal_position;
""")
for row in cur.fetchall():
    print(f"  {row[0]}.{row[1]}.{row[2]} {row[3]}")

conn.close()
