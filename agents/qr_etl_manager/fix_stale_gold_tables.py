#!/usr/bin/env python3
"""
Fix critical stale gold tables using direct DB connection
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
print("FIXING CRITICAL STALE GOLD TABLES")
print("=" * 80)

# Fix 1: stock_metrics from kpis_metrics
print("\n[1] Refreshing gold.stock_metrics from kpis_metrics...")
try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO gold.stock_metrics (
            ticker, date, close, volume, change_pct,
            rsi_14, pe_ratio, pb_ratio,
            sma_50, sma_200, above_sma_50, above_sma_200,
            created_at
        )
        SELECT 
            k.ticker,
            k.date,
            k.close,
            k.volume,
            k.change_1d as change_pct,
            k.rsi_14,
            k.pe_ratio,
            k.pb_ratio,
            k.sma_50,
            k.sma_200,
            k.close > k.sma_50 as above_sma_50,
            k.close > k.sma_200 as above_sma_200,
            NOW()
        FROM gold.kpis_metrics k
        WHERE k.date = (SELECT MAX(date) FROM gold.kpis_metrics)
        ON CONFLICT (ticker, date) DO UPDATE SET
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            change_pct = EXCLUDED.change_pct,
            rsi_14 = EXCLUDED.rsi_14,
            pe_ratio = EXCLUDED.pe_ratio,
            pb_ratio = EXCLUDED.pb_ratio,
            sma_50 = EXCLUDED.sma_50,
            sma_200 = EXCLUDED.sma_200,
            above_sma_50 = EXCLUDED.above_sma_50,
            above_sma_200 = EXCLUDED.above_sma_200,
            created_at = NOW();
    """)
    print(f"   ✅ {cur.rowcount} rows upserted")
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    print(f"   ❌ Error: {e}")

# Fix 2: stock_metrics_history
print("\n[2] Refreshing gold.stock_metrics_history...")
try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO gold.stock_metrics_history (
            ticker, date, close, volume, change_pct,
            rsi_14, pe_ratio, pb_ratio, created_at
        )
        SELECT 
            ticker,
            date,
            close,
            volume,
            change_1d as change_pct,
            rsi_14,
            pe_ratio,
            pb_ratio,
            NOW()
        FROM gold.kpis_metrics
        WHERE date > COALESCE((SELECT MAX(date) FROM gold.stock_metrics_history), '2025-01-01')
        ON CONFLICT (ticker, date) DO UPDATE SET
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            change_pct = EXCLUDED.change_pct,
            rsi_14 = EXCLUDED.rsi_14,
            pe_ratio = EXCLUDED.pe_ratio,
            pb_ratio = EXCLUDED.pb_ratio,
            created_at = NOW();
    """)
    print(f"   ✅ {cur.rowcount} rows upserted")
    conn.commit()
    cur.close()
    conn.close()
except Exception as e:
    print(f"   ❌ Error: {e}")

# Fix 3: market_sentiment_daily
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

# Fix 4: commodity_futures - check if we have commodity data
print("\n[4] Checking commodity_futures...")
try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Check for commodity tickers in unified_prices
    cur.execute("""
        SELECT DISTINCT ticker, asset_class 
        FROM silver.unified_prices 
        WHERE asset_class = 'commodity' 
           OR ticker LIKE 'GC=%' 
           OR ticker LIKE 'CL=%'
           OR ticker LIKE 'SI=%'
           OR ticker LIKE '%. commodity%'
        LIMIT 10
    """)
    commodities = cur.fetchall()
    if commodities:
        print(f"   Found commodity tickers: {[c[0] for c in commodities]}")
        # Refresh commodity_futures from unified_prices
        cur.execute("""
            INSERT INTO gold.commodity_futures (
                ticker, date, close_price, volume, returns, created_at
            )
            SELECT 
                ticker,
                date,
                close as close_price,
                volume,
                returns_1d as returns,
                NOW()
            FROM silver.unified_prices
            WHERE asset_class = 'commodity'
              AND close IS NOT NULL
              AND date > COALESCE((SELECT MAX(date) FROM gold.commodity_futures), '2025-01-01')
            ON CONFLICT (ticker, date) DO UPDATE SET
                close_price = EXCLUDED.close_price,
                volume = EXCLUDED.volume,
                returns = EXCLUDED.returns,
                created_at = NOW();
        """)
        print(f"   ✅ {cur.rowcount} rows upserted from unified_prices")
        conn.commit()
    else:
        print("   ⚠️ No commodity tickers found in unified_prices")
        print("   💡 Need to add commodity ingestion to bronze layer")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"   ❌ Error: {e}")

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
        ('gold.kpis_metrics', 'date'),
        ('gold.index_metrics', 'date'),
    ]
    
    for table, date_col in tables_to_check:
        try:
            cur.execute(f"SELECT COUNT(*), MAX({date_col}) FROM {table}")
            count, max_date = cur.fetchone()
            if max_date:
                days_old = (datetime.now().date() - max_date).days
                status = "✅" if days_old < 3 else "⚠️"
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
print("DONE!")
print("=" * 80)
