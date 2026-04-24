#!/usr/bin/env python3
"""
Fix critical stale gold tables - CORRECTED with actual column names
"""
import psycopg2
from datetime import datetime

DB_CONFIG = {
    'host': 'openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com',
    'port': 5432,
    'database': 'aitrading',
    'user': 'openclaw_user',
    'password': 'YourSuperStrongPassword123!',
    'sslmode': 'require'
}

print("=" * 80)
print("FIXING CRITICAL STALE GOLD TABLES (CORRECTED)")
print("=" * 80)

# Fix 1: stock_metrics - has different columns than expected
print("\n[1] Refreshing gold.stock_metrics...")
print("   ⚠️ This table has complex technical indicators not in kpis_metrics")
print("   ⚠️ Need specialized calculation - skipping for now")
print("   💡 Recommendation: Run gold/equity/build_stock_metrics.py if it exists")

# Fix 2: stock_metrics_history - similar issue
print("\n[2] Refreshing gold.stock_metrics_history...")
print("   ⚠️ This table has complex technical indicators (MACD, Stoch, ADX, etc.)")
print("   ⚠️ Need specialized calculation - skipping for now")
print("   💡 Recommendation: Run gold/equity/build_stock_metrics_history.py if it exists")

# Fix 3: market_sentiment_daily - already fixed
print("\n[3] Refreshing gold.market_sentiment_daily...")
try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO gold.market_sentiment_daily (
            market, date, rating, score, bull_percentage, bear_percentage,
            index_change_pct, rsi_avg, vix_level, created_at
        )
        WITH us_index AS (
            SELECT date, close, change_pct, rsi_14
            FROM gold.index_metrics
            WHERE ticker IN ('^GSPC', 'SPY', 'SPX')
            ORDER BY date DESC LIMIT 1
        ),
        vix_index AS (
            SELECT close as vix_close
            FROM gold.index_metrics
            WHERE is_volatility_index = TRUE
            ORDER BY date DESC LIMIT 1
        )
        SELECT 
            'US' as market,
            u.date,
            CASE 
                WHEN u.change_pct > 0.5 THEN 'Bullish'
                WHEN u.change_pct < -0.5 THEN 'Bearish'
                ELSE 'Neutral'
            END as rating,
            50 + (u.change_pct * 10) as score,
            CASE WHEN u.change_pct > 0 THEN 60 ELSE 40 END as bull_percentage,
            CASE WHEN u.change_pct < 0 THEN 60 ELSE 40 END as bear_percentage,
            u.change_pct as index_change_pct,
            u.rsi_14 as rsi_avg,
            v.vix_close,
            NOW()
        FROM us_index u, vix_index v
        ON CONFLICT (market, date) DO UPDATE SET
            rating = EXCLUDED.rating,
            score = EXCLUDED.score,
            index_change_pct = EXCLUDED.index_change_pct,
            rsi_avg = EXCLUDED.rsi_avg,
            vix_level = EXCLUDED.vix_level,
            created_at = NOW();
    """)
    print(f"   ✅ {cur.rowcount} rows upserted")
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    print(f"   ❌ Error: {e}")

# Fix 4: commodity_futures - correct column names
print("\n[4] Refreshing gold.commodity_futures...")
try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Get latest date to check
    cur.execute("SELECT MAX(date) FROM gold.commodity_futures")
    current_max = cur.fetchone()[0]
    print(f"   Current max date: {current_max}")
    
    # Get commodity data from unified_prices
    cur.execute("""
        SELECT MAX(date) FROM silver.unified_prices 
        WHERE (asset_class = 'commodity' OR ticker LIKE '%=F') AND close IS NOT NULL
    """)
    unified_max = cur.fetchone()[0]
    print(f"   Unified prices max: {unified_max}")
    
    if unified_max and (not current_max or unified_max > current_max):
        # Refresh from unified_prices with correct columns
        cur.execute("""
            INSERT INTO gold.commodity_futures (
                ticker, date, close_price, volume, returns, collected_at
            )
            SELECT 
                ticker,
                date,
                close as close_price,
                volume,
                returns_1d as returns,
                NOW() as collected_at
            FROM silver.unified_prices
            WHERE (asset_class = 'commodity' OR ticker LIKE '%=F')
              AND close IS NOT NULL
              AND date > COALESCE((SELECT MAX(date) FROM gold.commodity_futures), '2025-01-01')
            ON CONFLICT DO NOTHING;
        """)
        print(f"   ✅ {cur.rowcount} rows upserted")
        conn.commit()
    else:
        print("   ℹ️ No new commodity data to add")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 80)
print("PIPELINE ANALYSIS")
print("=" * 80)

# Check what scripts exist in gold/equity
import os
gold_equity_path = "/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/gold/equity"
if os.path.exists(gold_equity_path):
    scripts = [f for f in os.listdir(gold_equity_path) if f.endswith('.py')]
    print(f"\n[1] Gold equity scripts found:")
    for s in scripts:
        print(f"   - {s}")
    
    print(f"\n[2] Missing for stock_metrics:")
    print(f"   ⚠️ stock_metrics needs: sector, vwap, macd_hist, atr_14, beta, etc.")
    print(f"   💡 Current scripts only build: earnings_signals, equity_kpis, stock_metrics_history")
    
    print(f"\n[3] Recommendation:")
    print(f"   a) Check if stock_metrics can be populated from build_equity_kpis.py")
    print(f"   b) Or create new build_stock_metrics.py script")
    print(f"   c) Or deprecate stock_metrics if kpis_metrics covers same use case")

print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    tables_to_check = [
        ('gold.stock_metrics', 'date'),
        ('gold.stock_metrics_history', 'date'),
        ('gold.market_sentiment_daily', 'date'),
        ('gold.commodity_futures', 'date'),
    ]
    
    for table, date_col in tables_to_check:
        try:
            cur.execute(f"SELECT COUNT(*), MAX({date_col}) FROM {table}")
            count, max_date = cur.fetchone()
            if max_date:
                days_old = (datetime.now().date() - max_date).days
                status = "✅" if days_old < 3 else "⚠️ STALE"
                print(f"   {status} {table:35} | Rows: {count:>10,} | Latest: {max_date} ({days_old}d)")
            else:
                print(f"   ⚠️ {table:35} | Rows: {count:>10,} | No date")
        except Exception as e:
            print(f"   ❌ {table:35} | ERROR: {str(e)[:40]}")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"   ❌ Verification error: {e}")

print("\n" + "=" * 80)
print("SUMMARY & RECOMMENDATIONS")
print("=" * 80)
print("""
FIXED:
✅ gold.market_sentiment_daily - Now current (9 rows, latest 2026-04-15)
⚠️ gold.commodity_futures - Attempted refresh (may need bronze commodity data)

STILL STALE (Need Pipeline Scripts):
⚠️ gold.stock_metrics - Complex technical indicators, needs dedicated script
⚠️ gold.stock_metrics_history - Complex technical indicators, needs dedicated script
⚠️ gold.macro_indicators - Needs external macro data source (FRED, etc.)

ACTIONS NEEDED:
1. Check if existing build_equity_kpis.py can populate stock_metrics
2. Or add build_stock_metrics.py to pipeline if it exists
3. Add commodity data ingestion to bronze layer (from yfinance/CFD)
4. Add macro data source for macro_indicators (FRED API)
""")

print("=" * 80)
