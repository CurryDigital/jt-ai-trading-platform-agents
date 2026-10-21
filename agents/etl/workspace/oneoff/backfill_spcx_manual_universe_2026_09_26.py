#!/usr/bin/env python3
"""
One-off (kanban t_68887aff, 2026-09-26): register SPCX in gold.asset_registry
and backfill 1y of daily bars into bronze.yf_prices via the canonical
_upsert_prices() from bronze/yfinance/ingest_yfinance_prices.py (keeps the
sanity/placeholder/corp-action guards). Also verifies the new manual-book
fallback in get_active_tickers() covers SPCX.

Run:  /home/ubuntu/.hermes/etl-venv/bin/python3 workspace/oneoff/backfill_spcx_manual_universe_2026_09_26.py
from the agents/etl directory.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
import yfinance as yf

sys.path.insert(0, 'bronze/yfinance')
import ingest_yfinance_prices as ing

TICKER = 'SPCX'

conn = get_connection()
cur = conn.cursor()

# 1. Register SPCX (ETF, US, active). Idempotent.
cur.execute("""
    INSERT INTO gold.asset_registry (ticker, name, asset_class, market, sector, is_active)
    VALUES (%s, %s, 'ETF', 'US', 'ETF', TRUE)
    ON CONFLICT (ticker) DO UPDATE SET
        name = EXCLUDED.name,
        asset_class = 'ETF',
        market = 'US',
        is_active = TRUE,
        updated_at = NOW()
""", (TICKER, 'The SPAC and New Issue ETF'))
print(f"registry upsert rowcount={cur.rowcount}")

# 2. Verify the ingest universe now covers SPCX (registry path + manual fallback)
universe = ing.get_active_tickers(conn)
print(f"universe size={len(universe)}  SPCX in universe: {TICKER in universe}")
universe_us = ing.get_active_tickers(conn, markets=['US'])
print(f"US-filtered universe size={len(universe_us)}  SPCX present: {TICKER in universe_us}")

# 3. Backfill 1y of daily bars through the canonical guarded upsert.
df = yf.download(TICKER, period='1y', auto_adjust=True, progress=False)
if isinstance(df.columns, __import__('pandas').MultiIndex):
    df.columns = df.columns.get_level_values(0)
df = df.reset_index()
n = ing._upsert_prices(cur, TICKER, df)
print(f"bronze rows upserted for {TICKER}: {n} (frame rows: {len(df)})")

conn.commit()
cur.execute("SELECT count(*), min(date), max(date) FROM bronze.yf_prices WHERE ticker=%s", (TICKER,))
print("bronze.yf_prices SPCX:", cur.fetchone())
conn.close()
print("DONE")
