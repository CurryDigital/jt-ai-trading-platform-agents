#!/usr/bin/env python3
"""Silver promotion: bronze.ibkr_orders → silver tables (if applicable)"""
import os
import sys
import psycopg2
from datetime import datetime, timezone

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')

# Load Hermes env file
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'))

DB_HOST = os.environ.get('DB_HOST', 'openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com')
DB_PORT = int(os.environ.get('DB_PORT', 5432))
DB_NAME = os.environ.get('DB_NAME', 'aitrading')
DB_USER = os.environ.get('DB_USER', 'openclaw_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD
    )

def promote_ibkr_orders():
    """Promote bronze.ibkr_orders to silver.unified_prices (for filled orders, use avg_fill_price as close)"""
    conn = get_conn()
    cur = conn.cursor()
    
    # Get filled orders with avg_fill_price
    cur.execute("""
        SELECT ticker, action, quantity, avg_fill_price, execution_time, order_id
        FROM bronze.ibkr_orders
        WHERE status = 'Filled' AND avg_fill_price IS NOT NULL
          AND fetched_at > (SELECT MAX(fetched_at) - INTERVAL '1 hour' FROM bronze.ibkr_orders)
    """)
    rows = cur.fetchall()
    
    if not rows:
        print("No new filled orders to promote")
        conn.close()
        return 0
    
    inserted = 0
    for row in rows:
        ticker, action, qty, avg_fill_price, execution_time, order_id = row
        
        try:
            cur.execute("""
                INSERT INTO silver.unified_prices
                    (ticker, date, open, high, low, close, volume, source, adjusted_close, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ticker, date, source) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    adjusted_close = EXCLUDED.adjusted_close
            """, (
                ticker,
                execution_time.date() if execution_time else datetime.now(timezone.utc).date(),
                avg_fill_price, avg_fill_price, avg_fill_price, avg_fill_price,
                abs(qty) if qty else 0,
                'ibkr_execution',
                avg_fill_price
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting {ticker}: {e}")
    
    conn.commit()
    conn.close()
    print(f"silver.unified_prices: {inserted} execution prices upserted")
    return inserted

if __name__ == "__main__":
    promote_ibkr_orders()
