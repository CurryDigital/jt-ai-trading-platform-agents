#!/usr/bin/env python3
"""Add missing 000001.SZ"""
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

print("Adding 000001.SZ (correct ticker)...")

cur.execute("SELECT ticker, date, close, volume, returns_1d FROM silver.unified_prices WHERE ticker = '000001.SZ' ORDER BY date DESC LIMIT 1")
row = cur.fetchone()
if row:
    print(f"   Found: {row[0]} | {row[1]} | Close: {row[2]} | Change: {row[4]*100:.4f}%")
    
    cur.execute("INSERT INTO silver.asset_registry (ticker, name, market, asset_class, currency, is_active, created_at) VALUES ('000001.SZ', 'Ping An Bank Co Ltd', 'CN', 'equity', 'CNY', TRUE, NOW()) ON CONFLICT (ticker) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()")
    cur.execute("INSERT INTO gold.kpis_metrics (ticker, date, close, volume, change_1d, updated_at) VALUES (%s, %s, %s, %s, %s, NOW()) ON CONFLICT (ticker, date) DO UPDATE SET close = EXCLUDED.close, volume = EXCLUDED.volume, change_1d = EXCLUDED.change_1d, updated_at = NOW()", (row[0], row[1], row[2], row[3], row[4]*100))
    cur.execute("INSERT INTO consumption.markets_stocks_overview (ticker, name, market, price, change_pct, volume, asset_class, updated_at) SELECT ar.ticker, ar.name, ar.market, k.close, k.change_1d, k.volume, ar.asset_class, NOW() FROM gold.kpis_metrics k JOIN silver.asset_registry ar ON ar.ticker = k.ticker WHERE k.ticker = '000001.SZ' AND k.date = %s ON CONFLICT (ticker) DO UPDATE SET price = EXCLUDED.price, change_pct = EXCLUDED.change_pct, volume = EXCLUDED.volume, updated_at = NOW()", (row[1],))
    conn.commit()
    print("   ✅ Added 000001.SZ")
    
    # Verify
    cur.execute("SELECT ticker, price, change_pct, market FROM consumption.markets_stocks_overview WHERE ticker = '000001.SZ'")
    result = cur.fetchone()
    print(f"\n✅ VERIFIED: {result[0]} | Price: {result[1]} | Change: {result[2]}% | Market: {result[3]}")
else:
    print("   ❌ Not found")

cur.close()
conn.close()
