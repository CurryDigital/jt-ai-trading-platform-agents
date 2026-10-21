#!/usr/bin/env python3
"""One-off: post-update verification for COMM_GoldSilver_Ratio_MeanRev_VolTarget capital raise.
Kanban t_0a520c52. Read-only.
"""
import sys, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path:
    sys.path.insert(0, _ETL_SHARED)

from db import get_connection

SID = 'COMM_GoldSilver_Ratio_MeanRev_VolTarget'

conn = get_connection()
cur = conn.cursor()

print("=== registry ===")
cur.execute("SELECT assigned_capital FROM gold.strategy_registry WHERE strategy_id=%s", (SID,))
print("assigned_capital:", cur.fetchone()[0])

print("\n=== open positions ===")
cur.execute("""
    SELECT ticker, direction, entry_date, entry_price, n_shares,
           signal_weight, assigned_capital,
           ROUND(entry_price * n_shares, 2) AS notional
    FROM gold.paper_trades_synthetic
    WHERE strategy_id=%s AND status='open'
""", (SID,))
for r in cur.fetchall():
    print(r)

print("\n=== strategies_signals_current ===")
cur.execute("""
    SELECT ticker, signal, signal_strength, current_price, updated_at
    FROM consumption.strategies_signals_current
    WHERE strategy_id=%s ORDER BY ticker
""", (SID,))
for r in cur.fetchall():
    print(r)

print("\n=== closed rows today (should be 0) ===")
cur.execute("""
    SELECT COUNT(*) FROM gold.paper_trades_synthetic
    WHERE strategy_id=%s AND status='closed' AND exit_date=CURRENT_DATE
""", (SID,))
print(cur.fetchone()[0])

cur.close()
conn.close()
