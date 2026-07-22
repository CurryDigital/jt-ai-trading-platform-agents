"""Compute annual PNL from backtest trades for strategies missing annual_pnl."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== Annual PNL from backtest trades ===")
cur.execute("""
    SELECT strategy_id,
           SUM(CASE WHEN EXTRACT(YEAR FROM exit_date) = 2024 THEN pnl_pct ELSE 0 END) AS pnl_2024,
           SUM(CASE WHEN EXTRACT(YEAR FROM exit_date) = 2025 THEN pnl_pct ELSE 0 END) AS pnl_2025,
           SUM(CASE WHEN EXTRACT(YEAR FROM exit_date) = 2026 THEN pnl_pct ELSE 0 END) AS pnl_2026,
           COUNT(*) AS n_trades
    FROM gold.strategy_backtest_trades
    GROUP BY strategy_id
    ORDER BY strategy_id;
""")
for row in cur.fetchall():
    sid, p24, p25, p26, n = row
    print(f"{sid}: 2024={p24}, 2025={p25}, 2026={p26}, trades={n}")

conn.close()
