"""Probe strategy_backtest_trades for annual PNL computation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== strategy_backtest_trades columns ===")
cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'gold' AND table_name = 'strategy_backtest_trades'
    ORDER BY ordinal_position;
""")
for c in cur.fetchall():
    print(f"  {c[0]}: {c[1]}")

print("\n=== trade counts per strategy ===")
cur.execute("""
    SELECT strategy_id, COUNT(*) as n_trades,
           MIN(exit_date) as min_exit, MAX(exit_date) as max_exit
    FROM gold.strategy_backtest_trades
    GROUP BY strategy_id
    ORDER BY strategy_id;
""")
for row in cur.fetchall():
    print(row)

print("\n=== sample trades ===")
cur.execute("""
    SELECT strategy_id, entry_date, exit_date, pnl_pct
    FROM gold.strategy_backtest_trades
    ORDER BY strategy_id, exit_date
    LIMIT 20;
""")
for row in cur.fetchall():
    print(row)

conn.close()
