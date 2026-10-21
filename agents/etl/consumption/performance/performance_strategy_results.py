#!/usr/bin/env python3
"""
Consumption: Performance Tab — Backtest Results and Monthly Returns
Reads from: gold.strategy_backtests, gold.strategy_definitions,
            gold.strategy_metrics_summary, gold.trade_executions
Writes to:  consumption.strategies_backtest_results,
            consumption.performance_monthly_returns

Evidence contract (2026-10-09, t_835ba3c4):
- gold.strategy_backtests rows with evidence_class='RETRACTED' are quarantined
  and are NEVER fed to the Performance tab (excluded below).
- evidence_class/verification_note are carried into the consumption table so
  the UI can badge UNVERIFIED_NON_PIT rows and exclude them from rankings.
- Rows sourced from gold are DELETE-then-INSERT per refresh (the historical
  ON CONFLICT (id) never fired — id is serial — and caused duplicate growth).
- FLAG: legacy signal-agent signals are sized with hardcoded price=100.0,
  atr14=2.0 (agents/signals/strategies/base_strategy.py BaseStrategy.run()
  stub) — position_size is NOT real. NO P&L may ever be derived from
  gold.strategy_signals / gold.regime_gate_decision_log rows. Any future
  shadow-PnL feature for these strategies must be rejected at review.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection, require_table

SQL_BACKTEST_DELETE = """
-- Re-sync the gold-sourced slice: remove prior copies before re-inserting.
-- (Historical ON CONFLICT (id) never fired because id is serial-generated,
--  causing unbounded duplicate growth — see migration
--  2026-10-09_strategy_backtests_evidence_quarantine.sql.)
DELETE FROM consumption.strategies_backtest_results
WHERE strategy_id IN (SELECT strategy_id::text FROM gold.strategy_backtests);
"""

SQL_BACKTEST = """
INSERT INTO consumption.strategies_backtest_results
  (strategy_id, asset_class,
   sharpe_ratio, max_drawdown_pct, total_trades, win_rate,
   sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
   updated_at, evidence_class, verification_note)
SELECT
  b.strategy_id,
  NULL AS asset_class,
  b.sharpe AS sharpe_ratio,
  ABS(b.max_dd) * 100 AS max_drawdown_pct,
  b.n_trades AS total_trades,
  b.win_rate,
  NULL AS sharpe_oos,
  NULL AS returns_oos,
  NULL AS max_drawdown_oos,
  NULL AS trade_count_oos,
  NULL AS win_rate_oos,
  b.run_date AS updated_at,
  b.evidence_class,
  b.verification_note
FROM gold.strategy_backtests b
WHERE b.evidence_class IS DISTINCT FROM 'RETRACTED'  -- quarantined rows never surface (t_835ba3c4)
ON CONFLICT (id) DO UPDATE SET
  asset_class        = EXCLUDED.asset_class,
  sharpe_ratio       = EXCLUDED.sharpe_ratio,
  max_drawdown_pct   = EXCLUDED.max_drawdown_pct,
  total_trades       = EXCLUDED.total_trades,
  win_rate           = EXCLUDED.win_rate,
  updated_at         = EXCLUDED.updated_at,
  evidence_class     = EXCLUDED.evidence_class,
  verification_note  = EXCLUDED.verification_note;
"""

SQL_MONTHLY = """
INSERT INTO consumption.performance_monthly_returns
  (portfolio_type, year, month, return_pct, benchmark_return_pct, excess_return_pct)
SELECT
  'paper' AS portfolio_type,
  EXTRACT(YEAR  FROM DATE_TRUNC('month', ps.snapshot_date))::int,
  EXTRACT(MONTH FROM DATE_TRUNC('month', ps.snapshot_date))::int,
  SUM(ps.daily_pnl_pct) AS return_pct,
  NULL::numeric AS benchmark_return_pct,
  NULL::numeric AS excess_return_pct
FROM gold.portfolio_snapshots ps
WHERE ps.portfolio_type = 'paper'
GROUP BY DATE_TRUNC('month', ps.snapshot_date)
ON CONFLICT (portfolio_type, year, month) DO UPDATE SET
  return_pct = EXCLUDED.return_pct,
  benchmark_return_pct = EXCLUDED.benchmark_return_pct,
  excess_return_pct = EXCLUDED.excess_return_pct;
"""

# 2026-08-24 (t_1cfb20c2): attribution write REMOVED from this script.
# The portfolio attribution builder is the single owner for that dataset.
def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('gold.strategy_definitions')")
    if cur.fetchone()[0] is None:
        print("⚠️ gold.strategy_definitions does not exist — skipping")
        conn.close()
        return
    cur.execute("SELECT COUNT(*) FROM gold.strategy_definitions")
    if cur.fetchone()[0] == 0:
        print("⚠️ gold.strategy_definitions empty — skipping")
        conn.close()
        return
    cur.execute(SQL_BACKTEST_DELETE)
    print(f"🧹 consumption.strategies_backtest_results: {cur.rowcount} stale gold-sourced rows removed")
    cur.execute(SQL_BACKTEST)
    print(f"✅ consumption.strategies_backtest_results: {cur.rowcount} rows upserted")
    require_table(conn, 'consumption', 'performance_monthly_returns')
    cur.execute(SQL_MONTHLY)
    print(f"✅ consumption.performance_monthly_returns: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
