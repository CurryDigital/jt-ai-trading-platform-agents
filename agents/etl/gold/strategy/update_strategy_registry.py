#!/usr/bin/env python3
"""
Gold Strategy: Registry Update
Reads from: gold.strategy_backtests (latest backtest results)
Writes to:  gold.strategy_registry

Syncs win_rate_oos, sharpe_oos, max_drawdown_oos, trade_count_oos from
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
  win_rate_oos      = b.win_rate,
  sharpe_oos        = b.sharpe,
  max_drawdown_oos  = ABS(b.max_dd),
  trade_count_oos   = b.n_trades,
  updated_at        = NOW()
FROM (
  SELECT DISTINCT ON (strategy_id)
    strategy_id,
    win_rate,
    sharpe,
    max_dd,
    n_trades
  FROM gold.strategy_backtests
  ORDER BY strategy_id, run_date DESC
) b
WHERE sr.strategy_id = b.strategy_id::varchar;
"""

def sync_all(conn):
    cur = conn.cursor()
    cur.execute(SQL_SYNC_ALL)
    print(f"✅ gold.strategy_registry synced from backtests: {cur.rowcount} rows updated")
    conn.commit()

def patch_one(conn, strategy_id: str, **kwargs):
    """Manually update a specific strategy's registry entry."""
    allowed = {'asset_class', 'universe_tickers', 'frequency', 'execution_mode',
               'status', 'sharpe_oos', 'max_drawdown_oos', 'trade_count_oos',
               'win_rate_oos', 'conviction_score', 'assigned_capital',
               'in_market_capital', 'approved_by', 'signal_logic', 'exit_logic'}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        print("No valid fields to update.")
        return
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [strategy_id]
    cur = conn.cursor()
    cur.execute(
        f"UPDATE gold.strategy_registry SET {set_clause}, updated_at = NOW() WHERE strategy_id = %s",
        values
    )
    print(f"✅ {strategy_id} patched: {cur.rowcount} row(s) updated")
    conn.commit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', help='Strategy ID to patch (e.g. S015)')
    parser.add_argument('--asset-class')
    parser.add_argument('--universe-tickers')
    parser.add_argument('--frequency')
    parser.add_argument('--execution-mode')
    parser.add_argument('--status')
    parser.add_argument('--win-rate-oos', type=float)
    parser.add_argument('--sharpe-oos',   type=float)
    parser.add_argument('--max-dd-oos',   type=float)
    parser.add_argument('--trade-count',  type=int)
    parser.add_argument('--conviction',   type=float)
    parser.add_argument('--assigned-capital', type=float)
    parser.add_argument('--in-market-capital', type=float)
    parser.add_argument('--approved-by')
    parser.add_argument('--signal-logic')
    parser.add_argument('--exit-logic')
    args = parser.parse_args()

    conn = get_connection()
    if args.strategy:
        patch_one(conn, args.strategy,
                  asset_class=args.asset_class,
                  universe_tickers=args.universe_tickers,
                  frequency=args.frequency,
                  execution_mode=args.execution_mode,
                  status=args.status,
                  win_rate_oos=args.win_rate_oos,
                  sharpe_oos=args.sharpe_oos,
                  max_drawdown_oos=args.max_dd_oos,
                  trade_count_oos=args.trade_count,
                  conviction_score=args.conviction,
                  assigned_capital=args.assigned_capital,
                  in_market_capital=args.in_market_capital,
                  approved_by=args.approved_by,
                  signal_logic=args.signal_logic,
                  exit_logic=args.exit_logic)
    else:
        sync_all(conn)
    conn.close()
