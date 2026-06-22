# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Silver: Asset Registry Sync
Reads from: gold.asset_registry (master), bronze.yf_prices (ticker discovery)
Writes to:  silver.asset_registry

Ensures silver has a complete, deduplicated list of all active assets
with asset_class, market, sector tags.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
INSERT INTO silver.asset_registry
  (ticker, name, asset_class, market, sector, industry, currency,
   is_active, is_tradeable, exchange, source, updated_at)
SELECT
  g.ticker,
  g.name,
  g.asset_class,
  g.market,
  g.sector,
  NULL AS industry,
  'USD'::varchar AS currency,
  g.is_active,
  TRUE AS is_tradeable,
  NULL AS exchange,
  'gold_registry' AS source,
  NOW()
FROM gold.asset_registry g
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
    cur.execute(SQL)
    print(f"✅ silver.asset_registry synced: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
