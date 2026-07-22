#!/usr/bin/env python3
"""Investigate existing paper trade/signal/monthly sources."""
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()

for table in [
    'gold.paper_trades', 'gold.paper_trades_synthetic', 'gold.s9_paper_trades',
    'gold.ib_orders', 'gold.ibkr_orders', 'gold.ib_orders', 'gold.agent_events',
    'gold.strategy_backtest_trades', 'gold.strategy_backtest_runs',
    'consumption.strategies_signals_current', 'consumption.signal_logs',
    'consumption.portfolio_positions_paper', 'consumption.portfolio_positions_current'
]:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"{table}: {count}")
    except Exception as e:
        print(f"{table}: ERROR {e}")

print("\n=== gold.paper_trades_synthetic sample ===")
try:
    cur.execute("SELECT * FROM gold.paper_trades_synthetic LIMIT 5")
    for row in cur.fetchall():
        print(f"  {row}")
except Exception as e:
    print(f"  ERROR {e}")

print("\n=== gold.paper_trades sample ===")
try:
    cur.execute("SELECT * FROM gold.paper_trades LIMIT 5")
    for row in cur.fetchall():
        print(f"  {row}")
except Exception as e:
    print(f"  ERROR {e}")

print("\n=== gold.s9_paper_trades sample ===")
try:
    cur.execute("SELECT * FROM gold.s9_paper_trades LIMIT 5")
    for row in cur.fetchall():
        print(f"  {row}")
except Exception as e:
    print(f"  ERROR {e}")

print("\n=== gold.strategy_backtest_trades sample ===")
try:
    cur.execute("SELECT * FROM gold.strategy_backtest_trades LIMIT 5")
    for row in cur.fetchall():
        print(f"  {row}")
except Exception as e:
    print(f"  ERROR {e}")

print("\n=== gold.strategy_backtest_runs columns for real strategies ===")
try:
    cur.execute("""
        SELECT strategy_id, COUNT(*) as n
        FROM gold.strategy_backtest_runs
        WHERE strategy_id IN (
            SELECT strategy_id FROM gold.strategy_registry
            WHERE execution_mode='PAPER' AND status='paper'
        )
        GROUP BY strategy_id
    """)
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} runs")
except Exception as e:
    print(f"  ERROR {e}")

print("\n=== consumption.strategies_signals_current sample ===")
try:
    cur.execute("SELECT * FROM consumption.strategies_signals_current LIMIT 5")
    for row in cur.fetchall():
        print(f"  {row}")
except Exception as e:
    print(f"  ERROR {e}")

conn.close()
