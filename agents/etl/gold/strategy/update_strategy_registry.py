#!/usr/bin/env python3
"""
Gold Strategy: Registry Update
Reads from: gold.strategy_backtests (latest backtest results)
Writes to:  gold.strategy_registry

Syncs win_rate, sharpe_ratio, profit_factor, max_drawdown from
the latest backtest into the live registry record.

Usage:
  python3 update_strategy_registry.py                  # sync all from backtests
  python3 update_strategy_registry.py --strategy S015  # manual patch one strategy
"""
import sys, os, argparse
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_SYNC_ALL = """
UPDATE gold.strategy_registry sr
SET
  win_rate         = b.win_rate,
  profit_factor    = b.profit_factor,
  sharpe_ratio     = b.sharpe_ratio,
  max_drawdown_pct = ABS(b.max_drawdown),
  total_trades     = b.num_trades,
  last_modified    = NOW()
FROM (
  SELECT DISTINCT ON (strategy_id)
    strategy_id,
    win_rate,
    profit_factor,
    sharpe_ratio,
    max_drawdown,
    num_trades
  FROM gold.strategy_backtests
  ORDER BY strategy_id, calculated_at DESC
) b
WHERE sr.strategy_id = b.strategy_id;
"""

def sync_all(conn):
    cur = conn.cursor()
    cur.execute(SQL_SYNC_ALL)
    print(f"✅ gold.strategy_registry synced from backtests: {cur.rowcount} rows updated")
    conn.commit()

def patch_one(conn, strategy_id: str, **kwargs):
    """Manually update a specific strategy's registry entry."""
    allowed = {'target_assets', 'total_trades', 'win_rate', 'profit_factor',
               'sharpe_ratio', 'max_drawdown_pct', 'signal_logic', 'exit_logic'}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        print("No valid fields to update.")
        return
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [strategy_id]
    cur = conn.cursor()
    cur.execute(
        f"UPDATE gold.strategy_registry SET {set_clause}, last_modified = NOW() WHERE strategy_id = %s",
        values
    )
    print(f"✅ {strategy_id} patched: {cur.rowcount} row(s) updated")
    conn.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', help='Strategy ID to patch (e.g. S015)')
    parser.add_argument('--target-assets')
    parser.add_argument('--win-rate',     type=float)
    parser.add_argument('--sharpe',       type=float)
    parser.add_argument('--max-dd',       type=float)
    parser.add_argument('--trades',       type=int)
    args = parser.parse_args()

    conn = get_connection()
    if args.strategy:
        patch_one(conn, args.strategy,
                  target_assets=args.target_assets,
                  win_rate=args.win_rate,
                  sharpe_ratio=args.sharpe,
                  max_drawdown_pct=args.max_dd,
                  total_trades=args.trades)
    else:
        sync_all(conn)
    conn.close()
