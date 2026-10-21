#!/usr/bin/env python3
"""One-off: pre-update state check for COMM_GoldSilver_Ratio_MeanRev_VolTarget capital raise.
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

print("=== gold.strategy_registry row ===")
cur.execute("""
    SELECT strategy_id, execution_mode, assigned_capital, universe_tickers,
           retired_at, disable_paper_rebuild
    FROM gold.strategy_registry WHERE strategy_id = %s
""", (SID,))
for r in cur.fetchall():
    print(r)

print("\n=== open paper_trades_synthetic positions ===")
cur.execute("""
    SELECT id, ticker, direction, entry_date, entry_price, n_shares,
           signal_weight, assigned_capital
    FROM gold.paper_trades_synthetic
    WHERE strategy_id = %s AND status = 'open'
""", (SID,))
rows = cur.fetchall()
for r in rows:
    print(r)
print(f"open rows: {len(rows)}")

print("\n=== latest scores ===")
cur.execute("""
    SELECT ticker, score, signal_action
    FROM gold.strategy_ticker_scores WHERE strategy_id = %s ORDER BY ticker
""", (SID,))
for r in cur.fetchall():
    print(r)

print("\n=== latest GC=F price ===")
cur.execute("""
    SELECT date, close FROM silver.unified_prices
    WHERE ticker = 'GC=F' ORDER BY date DESC LIMIT 1
""")
print(cur.fetchone())

cur.close()
conn.close()
