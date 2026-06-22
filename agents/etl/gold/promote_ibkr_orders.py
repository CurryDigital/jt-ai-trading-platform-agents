# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""Gold promotion: bronze.ibkr_orders → gold.ibkr_orders (consumption.order_history is a view)"""
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

def promote_to_gold_ibkr_orders():
    """Refresh gold.ibkr_orders from bronze"""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT account, order_id, perm_id, ticker, action, quantity, order_type,
               status, filled, remaining, avg_fill_price, last_fill_price,
               commission, realized_pnl, submit_time, execution_time, gtc,
               notes, limit_price
        FROM bronze.ibkr_orders
        WHERE fetched_at > (SELECT MAX(fetched_at) - INTERVAL '2 hours' FROM bronze.ibkr_orders)
           OR order_id::varchar NOT IN (SELECT order_id FROM gold.ibkr_orders WHERE order_id IS NOT NULL)
    """)
    rows = cur.fetchall()
    
    if not rows:
        print("No new orders to promote to gold")
        conn.close()
        return 0
    
    inserted = 0
    for row in rows:
        (account, order_id, perm_id, ticker, action, quantity, order_type,
         status, filled, remaining, avg_fill_price, last_fill_price,
         commission, realized_pnl, submit_time, execution_time, gtc,
         notes, limit_price) = row
        
        order_date = submit_time.date() if submit_time else datetime.now(timezone.utc).date()
        
        try:
            cur.execute("""
                INSERT INTO gold.ibkr_orders
                    (account, order_id, perm_id, ticker, action, quantity, order_type,
                     status, filled, remaining, avg_fill_price, last_fill_price,
                     commission, realized_pnl, submit_time, execution_time, gtc,
                     notes, price, order_date, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (account, order_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    filled = EXCLUDED.filled,
                    remaining = EXCLUDED.remaining,
                    avg_fill_price = EXCLUDED.avg_fill_price,
                    last_fill_price = EXCLUDED.last_fill_price,
                    execution_time = EXCLUDED.execution_time,
                    updated_at = NOW()
            """, (account, str(order_id), perm_id, ticker, action, quantity, order_type,
                  status, filled, remaining, avg_fill_price, last_fill_price,
                  commission, realized_pnl, submit_time, execution_time, gtc,
                  notes, limit_price, order_date))
            conn.commit()
            inserted += 1
        except Exception as e:
            conn.rollback()
            print(f"SKIP order {order_id}: {e}")
    
    conn.close()
    print(f"gold.ibkr_orders: {inserted} orders upserted")
    return inserted

if __name__ == "__main__":
    promote_to_gold_ibkr_orders()
