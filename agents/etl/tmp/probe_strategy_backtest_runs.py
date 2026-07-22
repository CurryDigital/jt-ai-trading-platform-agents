"""Probe gold.strategy_backtest_runs for annual backtest ranges."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== Columns in gold.strategy_backtest_runs ===")
cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'gold' AND table_name = 'strategy_backtest_runs'
    ORDER BY ordinal_position;
""")
for c in cur.fetchall():
    print(f"  {c[0]}: {c[1]}")

print("\n=== strategy_backtest_runs overview ===")
cur.execute("""
    SELECT COUNT(*) AS total_rows,
           COUNT(DISTINCT strategy_id) AS distinct_strategies,
           MIN(created_at) AS min_created,
           MAX(created_at) AS max_created
    FROM gold.strategy_backtest_runs;
""")
print(cur.fetchone())

print("\n=== Sample rows ===")
cur.execute("""
    SELECT strategy_id, run_number, run_id, oos_start, oos_end, returns_oos, sharpe_oos, max_drawdown_oos, win_rate_oos, trade_count_oos, profit_factor_oos, created_at
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_id, run_number DESC, created_at DESC
    LIMIT 30;
""")
for row in cur.fetchall():
    print(row)

conn.close()
