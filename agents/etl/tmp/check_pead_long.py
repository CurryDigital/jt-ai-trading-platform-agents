"""Check pead_long status and annual_pnl source."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute("""
    SELECT r.strategy_id, r.status, r.priority, res.status as research_status
    FROM gold.strategy_registry r
    JOIN gold.strategy_research res ON res.strategy_id = r.strategy_id
    WHERE r.strategy_id = 'pead_long';
""")
print("pead_long registry:", cur.fetchone())

cur.execute("""
    SELECT run_id, run_number, created_at, annual_pnl_2024, annual_pnl_2025, annual_pnl_2026
    FROM gold.strategy_backtest_runs
    WHERE strategy_id = 'pead_long'
    ORDER BY run_number DESC, created_at DESC
    LIMIT 1;
""")
print("pead_long latest run:", cur.fetchone())

conn.close()
