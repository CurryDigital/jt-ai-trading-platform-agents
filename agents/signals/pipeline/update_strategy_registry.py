#!/usr/bin/env python3
"""
Gold Strategy: Registry Update
Reads from: gold.strategy_backtest_runs (canonical qr_research OOS runs)
Writes to:  gold.strategy_registry

Syncs win_rate_oos, sharpe_oos, max_drawdown_oos, trade_count_oos from the
latest OOS backtest run into the live registry record.

2026-07-17: source of truth switched from gold.strategy_backtests to
gold.strategy_backtest_runs, based on the diagnose_backtest_id_mapping.py
evidence run against prod:
  - strategy_backtest_runs is semantic-keyed (same varchar ids as
    strategy_registry), has a proper IS/OOS split, risk gates, run_number,
    and holds 59 strategies' runs including every frontend strategy — it is
    unambiguously qr_research's real output table.
  - strategy_backtests (smallint ids 1,2,3) turned out to be SIGNAL-AGENT
    numeric-space artifacts (1=Dual EMA, 2=52wk-high, 3=RSI(2), confirmed
    via gold.strategy_signals.strategy_name + registry.json), with NO
    semantic counterpart. Their registry_strategy_id stays NULL by design;
    the migration-006 bridge remains as a secondary pass for any legacy row
    an operator explicitly maps in the future.

Usage:
  python3 update_strategy_registry.py                  # sync all
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

# Latest OOS run per strategy = most recent oos_end, then highest run_number
# (re-runs of the same window), then created_at as the final tiebreak.
# max_drawdown_oos is stored negative in backtest_runs (risk gate checks
# `> -0.20`); the registry stores it as a positive magnitude (previous sync
# convention, ABS()) — kept for continuity with existing registry rows.
SQL_SYNC_FROM_RUNS = """
UPDATE gold.strategy_registry sr
SET
  win_rate_oos      = r.win_rate_oos,
  sharpe_oos        = r.sharpe_oos,
  max_drawdown_oos  = ABS(r.max_drawdown_oos),
  trade_count_oos   = r.trade_count_oos,
  updated_at        = NOW()
FROM (
  SELECT DISTINCT ON (strategy_id)
    strategy_id, sharpe_oos, max_drawdown_oos, win_rate_oos, trade_count_oos
  FROM gold.strategy_backtest_runs
  WHERE sharpe_oos IS NOT NULL
  ORDER BY strategy_id, oos_end DESC, run_number DESC, created_at DESC
) r
WHERE sr.strategy_id = r.strategy_id;
"""

# Registry strategies with no backtest run at all — their OOS fields stay
# NULL, which the frontend correctly renders as "—". Reported, not hidden.
SQL_NO_RUNS = """
SELECT sr.strategy_id
FROM gold.strategy_registry sr
WHERE sr.retired_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM gold.strategy_backtest_runs r
    WHERE r.strategy_id = sr.strategy_id AND r.sharpe_oos IS NOT NULL
  )
ORDER BY sr.strategy_id;
"""

# Secondary pass: legacy gold.strategy_backtests rows an operator has
# explicitly mapped via migration 006's registry_strategy_id. Confirmed
# 2026-07-17: the 3 existing rows are signal-agent artifacts and stay
# unmapped (NULL) — this pass currently matches nothing, by design.
SQL_SYNC_BRIDGED_LEGACY = """
UPDATE gold.strategy_registry sr
SET
  win_rate_oos      = b.win_rate,
  sharpe_oos        = b.sharpe,
  max_drawdown_oos  = ABS(b.max_dd),
  trade_count_oos   = b.n_trades,
  updated_at        = NOW()
FROM (
  SELECT DISTINCT ON (registry_strategy_id)
    registry_strategy_id, win_rate, sharpe, max_dd, n_trades
  FROM gold.strategy_backtests
  WHERE registry_strategy_id IS NOT NULL
  ORDER BY registry_strategy_id, run_date DESC
) b
WHERE sr.strategy_id = b.registry_strategy_id
  AND NOT EXISTS (
    SELECT 1 FROM gold.strategy_backtest_runs r
    WHERE r.strategy_id = sr.strategy_id AND r.sharpe_oos IS NOT NULL
  );
"""


def sync_all(conn):
    cur = conn.cursor()

    cur.execute("SELECT to_regclass('gold.strategy_backtest_runs')")
    if cur.fetchone()[0] is None:
        print("❌ gold.strategy_backtest_runs does not exist — cannot sync OOS stats.")
        conn.rollback()
        return

    cur.execute(SQL_SYNC_FROM_RUNS)
    print(f"✅ gold.strategy_registry synced from strategy_backtest_runs: "
          f"{cur.rowcount} rows updated")

    cur.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'gold' AND table_name = 'strategy_backtests'
          AND column_name = 'registry_strategy_id'
    """)
    if cur.fetchone() is not None:
        cur.execute(SQL_SYNC_BRIDGED_LEGACY)
        if cur.rowcount:
            print(f"✅ plus {cur.rowcount} rows from operator-mapped legacy "
                  f"strategy_backtests (migration 006 bridge)")

    cur.execute(SQL_NO_RUNS)
    missing = [r[0] for r in cur.fetchall()]
    if missing:
        print(f"ℹ️  {len(missing)} active registry strategies have no OOS backtest "
              f"run — their stats stay NULL (frontend shows '—') until qr_research "
              f"delivers runs: {missing}")

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
