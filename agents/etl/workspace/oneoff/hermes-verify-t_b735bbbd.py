#!/usr/bin/env python3
"""Ad-hoc verification for kanban t_b735bbbd fix."""
import sys, os
os.chdir(os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl'))
sys.path.insert(0, 'shared/scripts')
from db import get_connection

STALE = ['0001.HK','0002.HK','0003.HK','0005.HK','0006.HK','0016.HK','0027.HK',
         '0388.HK','0700.HK','0836.HK','0939.HK','0941.HK','1038.HK','1299.HK',
         '1398.HK','1928.HK','2318.HK','2388.HK','2628.HK','0088.HK','0197.HK',
         '0228.HK','0506.HK','0838.HK','0978.HK','1044.HK','3868.HK','6190.HK','9616.HK']

conn = get_connection()
cur = conn.cursor()
fails = []

# 1. no nonstandard labels remain
cur.execute("SELECT COUNT(*) FROM gold.asset_registry WHERE asset_class NOT IN "
            "('STOCK','ETF','INDEX','FX','CRYPTO','COMMODITY','VOLATILITY','CASH','CURRENCY')")
n = cur.fetchone()[0]
print(f"1. nonstandard asset_class rows: {n}")
if n:
    fails.append(f"{n} nonstandard rows")

# 2. constraint exists and rejects
cur.execute("SELECT COUNT(*) FROM pg_constraint WHERE conname='chk_asset_registry_asset_class'")
ok = cur.fetchone()[0] == 1
print(f"2. constraint present: {ok}")
if not ok:
    fails.append("constraint missing")
try:
    cur.execute("INSERT INTO gold.asset_registry (ticker, asset_class, market) "
                "VALUES ('VERIFYTEST.HK','HK Stock','HK')")
    fails.append("constraint did NOT reject")
    print("   reject test: FAILED")
except Exception as e:
    print(f"   reject test: OK ({type(e).__name__})")
conn.rollback()

# 3. bronze freshness for all 29
cur.execute("SELECT ticker, MAX(date) FROM bronze.yf_prices WHERE ticker = ANY(%s) GROUP BY ticker", (STALE,))
rows = dict(cur.fetchall())
stale = {t: str(d) for t, d in rows.items() if str(d) < '2026-08-05'}
missing = [t for t in STALE if t not in rows]
print(f"3. bronze: {len(rows)}/29, stale={stale or 'none'}, missing={missing or 'none'}")
if stale or missing:
    fails.append(f"bronze stale={stale} missing={missing}")

# 4. silver closes for 10 open positions
cur.execute("""
SELECT p.ticker, u.close, u.volume
FROM gold.paper_trades_synthetic p
LEFT JOIN silver.unified_prices u ON u.ticker=p.ticker AND u.date='2026-08-05'
WHERE p.strategy_id='hk_stk_52wh_mom_04' AND p.status='open' ORDER BY p.ticker""")
pos = cur.fetchall()
bad = [(t, str(c), v) for t, c, v in pos if c is None or not v or v <= 0]
print(f"4. silver 2026-08-05 closes: {len(pos)} positions, bad={bad or 'none'}")
if len(pos) != 10 or bad:
    fails.append(f"positions bad={bad} count={len(pos)}")

# 5. ingest filter coverage
cur.execute("SELECT COUNT(*) FROM gold.asset_registry "
            "WHERE market='HK' AND is_active AND asset_class IN ('STOCK','ETF','INDEX')")
print(f"5. active HK tickers in ingest filter: {cur.fetchone()[0]} (was 63)")

conn.close()
print("VERDICT:", "FAIL - " + "; ".join(fails) if fails else "PASS (ad-hoc verification, not a test suite)")
sys.exit(1 if fails else 0)
