# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""Gold promotion: bronze.ibkr_account_summary → gold.ibkr_account_summary (refresh)"""
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
    """Refresh gold.ibkr_account_summary from bronze"""
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
        print("No bronze data found")
        conn.close()
        return 0
    
    account, net_liq, cash_hkd, cash_usd, avail, bp, pos_count, fetched_at = row
    
    try:
        cur.execute("""
            INSERT INTO gold.ibkr_account_summary
                (account, net_liquidation, cash_hkd, cash_usd, available_funds, 
                 buying_power, position_count, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account) DO UPDATE SET
                net_liquidation = EXCLUDED.net_liquidation,
                cash_hkd = EXCLUDED.cash_hkd,
                cash_usd = EXCLUDED.cash_usd,
                available_funds = EXCLUDED.available_funds,
                buying_power = EXCLUDED.buying_power,
                position_count = EXCLUDED.position_count,
                fetched_at = EXCLUDED.fetched_at
        """, (account, net_liq, cash_hkd, cash_usd, avail, bp, pos_count, fetched_at))
        conn.commit()
        print(f"gold.ibkr_account_summary: upserted for account {account}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

def promote_portfolio_snapshots():
    """Create portfolio snapshot from bronze positions + account summary"""
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd, fetched_at
        FROM bronze.ibkr_account_summary
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM bronze.ibkr_account_summary)
    """)
    account_row = cur.fetchone()
    if not account_row:
        print("No account summary data")
        conn.close()
        return 0
    
    account, net_liq, cash_hkd, cash_usd, fetched_at = account_row
    
    cur.execute("""
        SELECT ticker, quantity, market_price, market_value, unrealized_pnl, currency
        FROM bronze.ibkr_positions_live
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM bronze.ibkr_positions_live)
    """)
    positions = cur.fetchall()
    
    total_value = float(net_liq) if net_liq else 0
    cash_value = (float(cash_hkd) if cash_hkd else 0) + (float(cash_usd) if cash_usd else 0)
    positions_value = sum(float(p[3]) if p[3] else 0 for p in positions)
    total_pnl = sum(float(p[4]) if p[4] else 0 for p in positions)
    
    volatility = 0.15
    var_95 = total_value * volatility * 1.645
    
    try:
        cur.execute("""
            INSERT INTO gold.portfolio_snapshots
                (snapshot_date, portfolio_type, total_value, cash_value, positions_value,
                 daily_pnl, daily_pnl_pct, mtd_pnl, ytd_pnl, total_pnl,
                 gross_exposure, net_exposure, beta_adjusted_exposure, var_95, calculated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (snapshot_date, portfolio_type) DO UPDATE SET
                total_value = EXCLUDED.total_value,
                cash_value = EXCLUDED.cash_value,
                positions_value = EXCLUDED.positions_value,
                daily_pnl = EXCLUDED.daily_pnl,
                total_pnl = EXCLUDED.total_pnl,
                var_95 = EXCLUDED.var_95,
                calculated_at = NOW()
        """, (
            fetched_at.date() if fetched_at else datetime.now(timezone.utc).date(),
            account,
            total_value,
            cash_value,
            positions_value,
            0,  # daily_pnl
            0,  # daily_pnl_pct
            0,  # mtd_pnl
            0,  # ytd_pnl
            total_pnl,
            abs(positions_value),  # gross_exposure
            positions_value,  # net_exposure
            positions_value,  # beta_adjusted_exposure
            var_95
        ))
        conn.commit()
        print(f"gold.portfolio_snapshots: upserted for {account}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    promote_ibkr_account_summary()
    promote_portfolio_snapshots()
