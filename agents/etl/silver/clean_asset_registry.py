# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Silver Transform: Asset Registry
Syncs gold.asset_registry → silver.asset_registry
Ensures all active tickers have a canonical record.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

UPSERT_SQL = """
INSERT INTO silver.asset_registry
    (ticker, name, asset_class, market, sector, industry, currency,
     is_active, is_tradeable, exchange, source, updated_at)
SELECT
    ticker, name, asset_class, market, sector,
    NULL AS industry,
    'USD' AS currency,
    is_active,
    TRUE AS is_tradeable,
    NULL AS exchange,
    'gold_registry' AS source,
    NOW()
FROM gold.asset_registry
ON CONFLICT (ticker) DO UPDATE SET
    name        = EXCLUDED.name,
    asset_class = EXCLUDED.asset_class,
    market      = EXCLUDED.market,
    sector      = EXCLUDED.sector,
    is_active   = EXCLUDED.is_active,
    updated_at  = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(UPSERT_SQL)
    print(f"✅ silver.asset_registry — {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
