# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
sync_ibkr_to_gold.py
====================
Sync IBKR data from bronze to gold layer.
"""

import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection


def sync_positions(conn, dry_run=False):
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (ticker)
            id, account, ticker, quantity, avg_cost, market_price,
            market_value, unrealized_pnl, unrealized_pnl_pct,
            CASE WHEN quantity > 0 THEN 'LONG' ELSE 'SHORT' END,
            asset_class, currency, fetched_at
        FROM bronze.ibkr_positions_live
        ORDER BY ticker, fetched_at DESC;
    """)
    rows = cur.fetchall()
    
    if dry_run:
        print(f"[DRY-RUN] Would sync {len(rows)} positions")
        for r in rows:
            print(f"  {r[2]}: qty={r[3]} avg={r[4]} price={r[5]} pnl={r[7]}")
        return len(rows)
    
    cur.execute("TRUNCATE gold.ibkr_positions_live;")
    for row in rows:
        cur.execute("""
            INSERT INTO gold.ibkr_positions_live 
                (id, account, ticker, quantity, avg_cost, market_price,
                 market_value, unrealized_pnl, unrealized_pnl_pct,
                 side, asset_class, currency, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, row)
    conn.commit()
    print(f"Synced {len(rows)} positions")
    return len(rows)


def sync_account_summary(conn, dry_run=False):
    cur = conn.cursor()
    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd,
               available_funds, buying_power, position_count, fetched_at
        FROM bronze.ibkr_account_summary
        ORDER BY fetched_at DESC LIMIT 1;
    """)
    row = cur.fetchone()
    if not row:
        print("No account summary found")
        return 0
    if dry_run:
        print(f"[DRY-RUN] Would sync account: net_liq={row[1]}")
        return 1
    cur.execute("TRUNCATE gold.ibkr_account_summary;")
    cur.execute("""
        INSERT INTO gold.ibkr_account_summary 
            (account, net_liquidation, cash_hkd, cash_usd,
             available_funds, buying_power, position_count, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
    """, row)
    conn.commit()
    print(f"Synced account summary")
    return 1


def sync_orders(conn, dry_run=False):
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            bo.id,
            bo.account,
            COALESCE(NULLIF(bo.order_id::text, '0'), bo.perm_id::text) as order_id,
            bo.perm_id::text,
            bo.ticker,
            bo.action,
            bo.quantity::int,
            bo.order_type,
            COALESCE(bo.limit_price, bo.aux_price, 0),
            bo.status,
            bo.filled::int,
            bo.remaining::int,
            bo.avg_fill_price,
            bo.last_fill_price,
            bo.commission,
            bo.realized_pnl,
            bo.submit_time,
            bo.execution_time,
            bo.gtc,
            bo.notes,
            bo.fetched_at
        FROM bronze.ibkr_orders bo
        WHERE bo.fetched_at >= NOW() - INTERVAL '7 days'
        ORDER BY bo.fetched_at DESC;
    """)
    rows = cur.fetchall()
    
    if dry_run:
        print(f"[DRY-RUN] Would sync {len(rows)} orders")
        return len(rows)
    
    cur.execute("DELETE FROM gold.ibkr_orders WHERE order_date < CURRENT_DATE - INTERVAL '14 days';")
    
    inserted = 0
    skipped = 0
    for row in rows:
        try:
            cur.execute("""
                INSERT INTO gold.ibkr_orders 
                    (id, account, order_id, perm_id, ticker,
                     action, quantity, order_type, price,
                     status, filled, remaining, avg_fill_price,
                     last_fill_price, commission, realized_pnl,
                     submit_time, execution_time, gtc,
                     notes, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    filled = EXCLUDED.filled,
                    remaining = EXCLUDED.remaining,
                    avg_fill_price = EXCLUDED.avg_fill_price,
                    last_fill_price = EXCLUDED.last_fill_price,
                    commission = EXCLUDED.commission,
                    realized_pnl = EXCLUDED.realized_pnl,
                    execution_time = EXCLUDED.execution_time,
                    updated_at = NOW();
            """, row)
            inserted += 1
        except Exception as e:
            skipped += 1
            if skipped <= 3:
                print(f"  Skip order {row[0]} {row[5]} {row[4]}: {e}")
    
    conn.commit()
    print(f"Synced {inserted} orders ({skipped} skipped)")
    return inserted


def main():
    parser = argparse.ArgumentParser(description='Sync IBKR bronze to gold')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be done')
    args = parser.parse_args()
    
    print(f"{'='*60}")
    print(f"IBKR Bronze -> Gold Sync")
    print(f"{'='*60}")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()
    
    conn = get_connection()
    try:
        n_pos = sync_positions(conn, args.dry_run)
        n_acct = sync_account_summary(conn, args.dry_run)
        n_ord = sync_orders(conn, args.dry_run)
        
        print()
        print(f"{'='*60}")
        print(f"Summary: {n_pos} positions, {n_acct} accounts, {n_ord} orders")
        print(f"{'='*60}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
