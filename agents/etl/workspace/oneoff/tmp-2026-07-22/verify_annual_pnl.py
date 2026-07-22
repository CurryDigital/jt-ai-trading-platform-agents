"""Verify annual_pnl coverage after backfill."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

print("=== Annual PnL coverage in latest run per strategy ===")
cur.execute("""
    SELECT strategy_id, run_number, created_at,
           annual_pnl_2024, annual_pnl_2025, annual_pnl_2026
    FROM (
        SELECT DISTINCT ON (strategy_id) strategy_id, run_number, created_at,
               annual_pnl_2024, annual_pnl_2025, annual_pnl_2026
        FROM gold.strategy_backtest_runs
        ORDER BY strategy_id, run_number DESC, created_at DESC
    ) t
    WHERE strategy_id IN (
        SELECT DISTINCT r.strategy_id
        FROM gold.strategy_registry r
        JOIN gold.strategy_research s ON s.strategy_id = r.strategy_id
        WHERE r.status NOT IN ('DEPRECATED', 'retired', 'paused')
          AND s.status NOT IN ('rejected', 'retired')
    )
    ORDER BY strategy_id;
""")
for row in cur.fetchall():
    sid, run_number, created_at, p24, p25, p26 = row
    print(f"{sid}: run={run_number}, 2024={p24}, 2025={p25}, 2026={p26}")

print("\n=== API yearly_backtest payload for /api/strategies/researcher ===")
cur.execute("""
    SELECT r.strategy_id,
           b.annual_pnl_2024, b.annual_pnl_2025, b.annual_pnl_2026
    FROM gold.strategy_registry r
    JOIN gold.strategy_research res ON res.strategy_id = r.strategy_id
    LEFT JOIN (
        SELECT DISTINCT ON (strategy_id) strategy_id,
               annual_pnl_2024, annual_pnl_2025, annual_pnl_2026
        FROM gold.strategy_backtest_runs
        ORDER BY strategy_id, run_number DESC, created_at DESC
    ) b ON b.strategy_id = r.strategy_id
    WHERE r.status NOT IN ('DEPRECATED', 'retired', 'paused')
      AND res.status NOT IN ('rejected', 'retired')
      AND r.priority IN ('EXPERIMENTAL', 'NEAR_GOLDEN', 'GOLDEN')
    ORDER BY r.strategy_id;
""")
for row in cur.fetchall():
    sid, p24, p25, p26 = row
    years = []
    if p24 is not None: years.append(f"2024:{p24:.2%}")
    if p25 is not None: years.append(f"2025:{p25:.2%}")
    if p26 is not None: years.append(f"2026:{p26:.2%}")
    print(f"{sid}: {' | '.join(years) if years else 'No annual backtest data'}")

conn.close()
