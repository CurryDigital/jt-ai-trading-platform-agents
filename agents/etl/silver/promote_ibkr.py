#!/usr/bin/env python3
"""Silver promotion: bronze.ibkr_account_summary → silver.asset_registry + silver.unified_prices"""
import os
import sys
from datetime import datetime, timezone

# Use the canonical pooled connection. db.py is on PYTHONPATH when invoked
# via daily_refresh.sh; the explicit sys.path insert below makes the script
# also runnable directly for ops.
HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(HERE, '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)

from db import get_connection

# Back-compat alias for the rest of this file.
get_conn = get_connection

def promote_ibkr_account_summary():
    """Promote bronze.ibkr_account_summary to silver.asset_registry (cash positions)"""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd, 
               available_funds, buying_power, position_count, fetched_at
        FROM bronze.ibkr_account_summary
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM bronze.ibkr_account_summary)
    """)
    row = cur.fetchone()
    if not row:
        print("No bronze.ibkr_account_summary data found")
        conn.close()
        return 0
    
    account, net_liq, cash_hkd, cash_usd, avail, bp, pos_count, fetched_at = row
    
    assets = []
    if cash_hkd and float(cash_hkd) != 0:
        assets.append(('CASH_HKD', 'HKD', 'CASH', float(cash_hkd), fetched_at))
    if cash_usd and float(cash_usd) != 0:
        assets.append(('CASH_USD', 'USD', 'CASH', float(cash_usd), fetched_at))
    
    inserted = 0
    for ticker, currency, asset_class, value, ts in assets:
        try:
            cur.execute("""
                INSERT INTO silver.asset_registry 
                    (ticker, name, asset_class, sector, industry, currency, 
                     exchange, is_active, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    asset_class = EXCLUDED.asset_class,
                    currency = EXCLUDED.currency,
                    updated_at = NOW()
            """, (
                ticker, f'{ticker} Cash Balance', asset_class, 'Cash', 'Cash',
                currency, 'IBKR', True
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting {ticker}: {e}")
    
    conn.commit()
    conn.close()
    print(f"silver.asset_registry: {inserted} cash assets upserted")
    return inserted

def promote_ibkr_positions():
    """Promote bronze.ibkr_positions_live to silver.unified_prices"""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT account, ticker, conid, asset_class, quantity, avg_cost,
               market_price, market_value, unrealized_pnl, currency, exchange, fetched_at
        FROM bronze.ibkr_positions_live
    """)
    rows = cur.fetchall()
    
    if not rows:
        print("No bronze.ibkr_positions_live data found")
        conn.close()
        return 0
    
    inserted = 0
    for row in rows:
        account, ticker, conid, asset_class, qty, avg_cost, market_price, market_value, unrealized_pnl, currency, exchange, fetched_at = row
        
        if not market_price or market_price == 0:
            continue
        
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
                fetched_at.date() if fetched_at else datetime.now(timezone.utc).date(),
                market_price, market_price, market_price, market_price,
                abs(qty) if qty else 0,
                'ibkr_position',
                market_price
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting {ticker}: {e}")
    
    conn.commit()
    conn.close()
    print(f"silver.unified_prices: {inserted} position prices upserted")
    return inserted

if __name__ == "__main__":
    promote_ibkr_account_summary()
    promote_ibkr_positions()
