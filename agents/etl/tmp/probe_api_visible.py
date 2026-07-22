"""Probe API-visible strategies and their annual_pnl coverage."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

# Mimic the /api/strategies/researcher publication gate logic
print("=== API-visible strategies (pass publication gates) ===")
cur.execute("""
    SELECT r.strategy_id, r.name, r.asset_class, r.priority,
           b.sharpe_oos, b.max_drawdown_oos, b.trade_count_oos, b.returns_oos,
           b.annual_pnl_2024, b.annual_pnl_2025, b.annual_pnl_2026
    FROM gold.strategy_registry r
    JOIN gold.strategy_research res ON res.strategy_id = r.strategy_id
    LEFT JOIN (
        SELECT DISTINCT ON (strategy_id) strategy_id, sharpe_oos, max_drawdown_oos, trade_count_oos, returns_oos,
               annual_pnl_2024, annual_pnl_2025, annual_pnl_2026
        FROM gold.strategy_backtest_runs
        ORDER BY strategy_id, created_at DESC
    ) b ON b.strategy_id = r.strategy_id
    WHERE r.status != 'DEPRECATED'
      AND r.status NOT IN ('retired', 'paused')
      AND res.status NOT IN ('rejected', 'retired')
      AND r.priority IN ('EXPERIMENTAL', 'NEAR_GOLDEN', 'GOLDEN')
    ORDER BY r.sharpe_oos DESC NULLS LAST;
""")
rows = cur.fetchall()
for row in rows:
    sid, name, asset, priority, sharpe, dd, trades, ret, p24, p25, p26 = row
    has_24 = p24 is not None
    has_25 = p25 is not None
    has_26 = p26 is not None
    passes_gate = sharpe is not None and sharpe >= 0.5 and abs(dd or 0) <= 0.20 and (trades or 0) >= 30 and ret is not None
    print(f"{sid} ({asset}): sharpe={sharpe}, dd={dd}, trades={trades}, ret={ret} | 2024={has_24}, 2025={has_25}, 2026={has_26} | passes_gate={passes_gate}")

print(f"\nTotal registry rows: {len(rows)}")

conn.close()
