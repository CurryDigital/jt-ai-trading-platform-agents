#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

conn = get_connection()
with conn.cursor() as cur:
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'bronze' AND table_name = 'ibkr_contracts'
        ORDER BY ordinal_position;
    """)
    for row in cur.fetchall():
        print(row)

    print("\n--- constraints ---")
    cur.execute("""
        SELECT conname, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'bronze.ibkr_contracts'::regclass;
    """)
    for row in cur.fetchall():
        print(row)

    print("\n--- sample rows ---")
    cur.execute("SELECT * FROM bronze.ibkr_contracts LIMIT 3")
    for row in cur.fetchall():
        print(row)
conn.close()
