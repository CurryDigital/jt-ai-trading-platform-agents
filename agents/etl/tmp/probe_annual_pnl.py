"""Probe annual PNL inconsistency in strategy_backtest_runs."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== Annual PNL per strategy (latest run only) ===")
cur.execute("""
    SELECT DISTINCT ON (strategy_id)
           strategy_id,
           annual_pnl_2024,
           annual_pnl_2025,
           annual_pnl_2026,
           returns_oos,
           oos_start,
           oos_end,
           created_at
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_id, created_at DESC;
""")
for row in cur.fetchall():
    sid, p24, p25, p26, ret, oos_start, oos_end, created_at = row
    years = []
    if p24 is not None: years.append(('2024', float(p24)))
    if p25 is not None: years.append(('2025', float(p25)))
    if p26 is not None: years.append(('2026', float(p26)))
    print(f"{sid}: {years} | returns_oos={ret} | oos={oos_start}..{oos_end} | created_at={created_at}")

print("\n=== Strategies with 2026 = 0 exactly ===")
cur.execute("""
    SELECT DISTINCT ON (strategy_id) strategy_id, annual_pnl_2026, created_at
    FROM gold.strategy_backtest_runs
    WHERE annual_pnl_2026 = 0
    ORDER BY strategy_id, created_at DESC;
""")
for row in cur.fetchall():
    print(row)

print("\n=== Count of latest runs by year coverage ===")
cur.execute("""
    WITH latest AS (
        SELECT DISTINCT ON (strategy_id)
               strategy_id,
               annual_pnl_2024,
               annual_pnl_2025,
               annual_pnl_2026
        FROM gold.strategy_backtest_runs
        ORDER BY strategy_id, created_at DESC
    )
    SELECT
        CASE WHEN annual_pnl_2024 IS NOT NULL THEN 1 ELSE 0 END AS has_2024,
        CASE WHEN annual_pnl_2025 IS NOT NULL THEN 1 ELSE 0 END AS has_2025,
        CASE WHEN annual_pnl_2026 IS NOT NULL THEN 1 ELSE 0 END AS has_2026,
        COUNT(*)
    FROM latest
    GROUP BY 1, 2, 3;
""")
for row in cur.fetchall():
    print(row)

conn.close()
