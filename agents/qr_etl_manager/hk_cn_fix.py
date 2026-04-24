#!/usr/bin/env python3
"""HK & CN stocks fix for markets_stocks_overview"""
import psycopg2

conn = psycopg2.connect(
    host='openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com',
    port=5432,
    database='aitrading',
    user='openclaw_user',
    password='YourSuperStrongPassword123!',
    sslmode='require'
)
cur = conn.cursor()

print("=" * 60)
print("HK & CN STOCKS FIX")
print("=" * 60)

print("\n[5b] Adding missing 000001.SS...")
cur.execute("SELECT ticker, date, close, volume, returns_1d FROM silver.unified_prices WHERE ticker = '000001.SS' ORDER BY date DESC LIMIT 1")
row = cur.fetchone()
if row:
    print(f"   Found: {row[0]} | {row[1]} | {row[2]} | Change: {row[4]*100:.4f}%")
    
    cur.execute("INSERT INTO silver.asset_registry (ticker, name, market, asset_class, currency, is_active, created_at) VALUES ('000001.SS', 'Ping An Bank Co Ltd', 'CN', 'equity', 'CNY', TRUE, NOW()) ON CONFLICT (ticker) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()")
    cur.execute("INSERT INTO gold.kpis_metrics (ticker, date, close, volume, change_1d, updated_at) VALUES (%s, %s, %s, %s, %s, NOW()) ON CONFLICT (ticker, date) DO UPDATE SET close = EXCLUDED.close, volume = EXCLUDED.volume, change_1d = EXCLUDED.change_1d, updated_at = NOW()", (row[0], row[1], row[2], row[3], row[4]*100))
    cur.execute("INSERT INTO consumption.markets_stocks_overview (ticker, name, market, price, change_pct, volume, asset_class, updated_at) SELECT ar.ticker, ar.name, ar.market, k.close, k.change_1d, k.volume, ar.asset_class, NOW() FROM gold.kpis_metrics k JOIN silver.asset_registry ar ON ar.ticker = k.ticker WHERE k.ticker = '000001.SS' AND k.date = %s ON CONFLICT (ticker) DO UPDATE SET price = EXCLUDED.price, change_pct = EXCLUDED.change_pct, volume = EXCLUDED.volume, updated_at = NOW()", (row[1],))
    conn.commit()
    print("   ✅ Added 000001.SS")
else:
    print("   ❌ Not found in unified_prices")

print("\n" + "=" * 60)
print("DONE!")
print("=" * 60)

cur.close()
conn.close()
