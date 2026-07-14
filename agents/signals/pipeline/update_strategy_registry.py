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
# Signal-agent layout: agents/signals/pipeline/<this file>;
# canonical DB pool lives in agents/etl/shared/scripts/db.py.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'etl', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path: sys.path.insert(0, _ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# 2026-07-10 (P0-2): join on registry_strategy_id (migration 006 bridge
# column) with a fallback to the old smallint::varchar cast. The cast alone
# can never match real data ("11" != "cl_cot_trend") — that's why OOS stats
# synced 0 rows and the frontend showed "Trades (OOS): —" everywhere.
# Backtest rows with NULL registry_strategy_id are honestly excluded from
# the bridged join; sync_all() reports the unmapped count loudly instead of
# letting them silently vanish.
SQL_SYNC_ALL = """
UPDATE gold.strategy_registry sr
SET
  win_rate_oos      = b.win_rate,
  sharpe_oos        = b.sharpe,
  max_drawdown_oos  = ABS(b.max_dd),
  trade_count_oos   = b.n_trades,
  updated_at        = NOW()
FROM (
  SELECT DISTINCT ON (COALESCE(registry_strategy_id, strategy_id::varchar))
    COALESCE(registry_strategy_id, strategy_id::varchar) AS ref_id,
    win_rate,
    sharpe,
    max_dd,
    n_trades
  FROM gold.strategy_backtests
  ORDER BY COALESCE(registry_strategy_id, strategy_id::varchar), run_date DESC
) b
WHERE sr.strategy_id = b.ref_id;
"""

# Pre-006 fallback: the legacy cast-only join (matches nothing against real
# data, but keeps the script runnable on an unmigrated DB while warning).
SQL_SYNC_ALL_LEGACY = """
UPDATE gold.strategy_registry sr
SET
  win_rate_oos      = b.win_rate,
  sharpe_oos        = b.sharpe,
  max_drawdown_oos  = ABS(b.max_dd),
  trade_count_oos   = b.n_trades,
  updated_at        = NOW()
FROM (
  SELECT DISTINCT ON (strategy_id)
    strategy_id, win_rate, sharpe, max_dd, n_trades
  FROM gold.strategy_backtests
  ORDER BY strategy_id, run_date DESC
) b
WHERE sr.strategy_id = b.strategy_id::varchar;
"""

SQL_UNMAPPED_COUNT = """
SELECT COUNT(DISTINCT strategy_id)
FROM gold.strategy_backtests
WHERE registry_strategy_id IS NULL;
"""

def sync_all(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'gold' AND table_name = 'strategy_backtests'
          AND column_name = 'registry_strategy_id'
    """)
    has_bridge = cur.fetchone() is not None

    if has_bridge:
        cur.execute(SQL_SYNC_ALL)
        print(f"✅ gold.strategy_registry synced from backtests: {cur.rowcount} rows updated")
        cur.execute(SQL_UNMAPPED_COUNT)
        n_unmapped = cur.fetchone()[0]
        if n_unmapped:
            print(f"⚠️  {n_unmapped} backtest strategy id(s) have no registry_strategy_id "
                  f"mapping — their OOS stats cannot reach gold.strategy_registry. "
                  f"Backfill per db_setup/migrations/006_backtest_registry_id_bridge.sql.")
    else:
        cur.execute(SQL_SYNC_ALL_LEGACY)
        print(f"⚠️  migration 006 not applied — legacy cast join matched "
              f"{cur.rowcount} rows (expected 0 against real data). "
              f"Apply db_setup/migrations/006_backtest_registry_id_bridge.sql.")
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
