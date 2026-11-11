#!/usr/bin/env python3
"""Phase 1 — t_84fa974a: registry root-cause fix + pre-change snapshot.

- XLY: gold.asset_registry.is_active false -> true (root cause of stale series:
  daily ingest universe gates on is_active=TRUE; row seeded inactive 2026-08-24
  by manual_t_0ad7522c bulk registration).
- XLC: insert missing gold.asset_registry row (ETF/US, active). XLC never
  registered -> never ingested.
- Mirror to silver.asset_registry via the canonical sync SQL.
- Snapshot pre-change silver.unified_prices rows for XLY/XLC to
  silver.unified_prices__xlc_xly_bak_20261102 and log to gold.etl_snapshot_log.
"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SNAP = 't84fa974a_xlc_xly_repair_20261102'

conn = get_connection()
cur = conn.cursor()

# --- registry fixes (gold master) ---
cur.execute("""
    UPDATE gold.asset_registry
    SET is_active = TRUE, updated_at = NOW()
    WHERE ticker = 'XLY' AND is_active = FALSE
""")
print('XLY is_active flips:', cur.rowcount)

cur.execute("""
    INSERT INTO gold.asset_registry
        (ticker, name, asset_class, market, is_active, description, created_at, updated_at)
    VALUES
        ('XLC', 'SPDR Communication Services Select Sector ETF', 'ETF', 'US', TRUE,
         'well-known US sector ETF; registered t_84fa974a (IMPROVE-1 G0 coverage repair); inception 2018-06-18 per SSGA',
         NOW(), NOW())
    ON CONFLICT (ticker) DO UPDATE SET
        is_active = TRUE, updated_at = NOW()
""")
print('XLC gold registry upsert:', cur.rowcount)

# --- mirror to silver (canonical sync SQL from silver/sync_asset_registry.py) ---
cur.execute("""
INSERT INTO silver.asset_registry
  (ticker, name, asset_class, market, sector, industry, currency,
   is_active, is_tradeable, exchange, source, updated_at)
SELECT g.ticker, g.name, g.asset_class, g.market, g.sector, NULL, 'USD'::varchar,
       g.is_active, TRUE, NULL, 'gold_registry', NOW()
FROM gold.asset_registry g
WHERE g.ticker IN ('XLY','XLC')
ON CONFLICT (ticker) DO UPDATE SET
  name = EXCLUDED.name, asset_class = EXCLUDED.asset_class, market = EXCLUDED.market,
  sector = EXCLUDED.sector, is_active = EXCLUDED.is_active, updated_at = NOW()
""")
print('silver.asset_registry mirror upsert:', cur.rowcount)

# --- pre-change snapshot of silver rows for the two tickers ---
cur.execute("DROP TABLE IF EXISTS silver.unified_prices__xlc_xly_bak_20261102")
cur.execute("""
    CREATE TABLE silver.unified_prices__xlc_xly_bak_20261102 AS
    SELECT * FROM silver.unified_prices WHERE ticker IN ('XLY','XLC')
""")
cur.execute("SELECT count(*) FROM silver.unified_prices__xlc_xly_bak_20261102")
bak_rows = cur.fetchone()[0]
print('snapshot bak rows:', bak_rows)

cur.execute("""
    INSERT INTO gold.etl_snapshot_log
        (snapshot_id, scope, script, pre_rows, pre_max_date, post_rows, post_max_date, note)
    VALUES (%s, %s, %s, %s, %s, NULL, NULL, %s)
    ON CONFLICT (snapshot_id, scope) DO NOTHING
""", (SNAP, 'backup silver.unified_prices XLY/XLC',
      'workspace/oneoff/xlc_xly_repair_t84fa974a_phase1.py',
      bak_rows, None,
      'pre-repair snapshot table silver.unified_prices__xlc_xly_bak_20261102 (XLY 2105 rows to 2026-05-18; XLC absent)'))
print('snapshot log backup row inserted')

# --- verify registry state ---
cur.execute("SELECT ticker, asset_class, market, is_active FROM gold.asset_registry WHERE ticker IN ('XLY','XLC') ORDER BY ticker")
print('gold registry now:', cur.fetchall())
cur.execute("SELECT ticker, asset_class, market, is_active FROM silver.asset_registry WHERE ticker IN ('XLY','XLC') ORDER BY ticker")
print('silver registry now:', cur.fetchall())

# --- confirm both now enter the daily ingest universe ---
cur.execute("""
    SELECT ticker FROM gold.asset_registry
    WHERE is_active = TRUE
      AND asset_class IN ('STOCK','ETF','INDEX','FX','CURRENCY','CRYPTO')
      AND ticker IN ('XLY','XLC')
    ORDER BY ticker
""")
print('in daily ingest universe after fix:', cur.fetchall())

conn.commit()
conn.close()
print('PHASE1 OK')
