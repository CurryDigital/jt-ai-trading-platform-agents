#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute("""
SELECT strategy_id, universe_tickers, pg_typeof(universe_tickers)
FROM gold.strategy_registry
WHERE strategy_id IN ('ETF_HK_Balanced_Trend', 'HK_Quality_BlueChips');
""")
for r in cur.fetchall():
    print(r)
conn.close()
