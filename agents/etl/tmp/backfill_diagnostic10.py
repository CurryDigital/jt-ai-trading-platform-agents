#!/usr/bin/env python3
"""Check schema of consumption.performance_monthly_returns."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema='consumption' AND table_name='performance_monthly_returns' ORDER BY ordinal_position")
for row in cur.fetchall():
    print(row)

cur.execute("SELECT * FROM consumption.performance_monthly_returns LIMIT 5")
for row in cur.fetchall():
    print(row)

conn.close()
