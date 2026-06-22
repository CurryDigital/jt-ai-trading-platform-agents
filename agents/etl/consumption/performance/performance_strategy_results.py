#!/usr/bin/env python3
"""
Consumption: Performance Tab — Backtest Results, Monthly Returns, Attribution
Reads from: gold.strategy_backtests, gold.strategy_definitions,
            gold.strategy_metrics_summary, gold.trade_executions
Writes to:  consumption.strategies_backtest_results,
            consumption.performance_monthly_returns,
            consumption.performance_strategy_attribution
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_BACKTEST = """
INSERT INTO consumption.strategies_backtest_results
  (strategy_id, asset_class,
   sharpe_ratio, max_drawdown_pct, total_trades, win_rate,
   sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
   updated_at)
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
  b.run_date AS updated_at
FROM gold.strategy_backtests b
ON CONFLICT (id) DO UPDATE SET
  asset_class        = EXCLUDED.asset_class,
  sharpe_ratio       = EXCLUDED.sharpe_ratio,
  max_drawdown_pct   = EXCLUDED.max_drawdown_pct,
  total_trades       = EXCLUDED.total_trades,
  win_rate           = EXCLUDED.win_rate,
  updated_at         = EXCLUDED.updated_at;
"""

SQL_MONTHLY = """
INSERT INTO consumption.performance_monthly_returns
  (portfolio_type, year, month, return_pct)
SELECT
  'paper' AS portfolio_type,
  EXTRACT(YEAR  FROM DATE_TRUNC('month', ps.snapshot_date))::int,
  EXTRACT(MONTH FROM DATE_TRUNC('month', ps.snapshot_date))::int,
  SUM(ps.daily_pnl_pct) AS return_pct
FROM gold.portfolio_snapshots ps
WHERE ps.portfolio_type = 'paper'
GROUP BY DATE_TRUNC('month', ps.snapshot_date)
ON CONFLICT (portfolio_type, year, month) DO UPDATE SET
  return_pct = EXCLUDED.return_pct;
"""

SQL_ATTRIBUTION = """
INSERT INTO consumption.performance_strategy_attribution
  (strategy_id, strategy_name, portfolio_type,
   allocated_capital_pct, return_pct, num_trades,
   win_rate, avg_trade_return_pct, max_drawdown_pct, sharpe_ratio,
   calculated_at)
SELECT
  sd.strategy_id,
  sd.strategy_name,
  'paper' AS portfolio_type,
  100.0 / NULLIF((SELECT COUNT(*) FROM gold.strategy_definitions WHERE status = 'ACTIVE'), 0)
    AS allocated_capital_pct,
  NULL AS return_pct,
  b.n_trades,
  b.win_rate,
  NULL AS avg_trade_return_pct,
  ABS(b.max_dd) * 100 AS max_drawdown_pct,
  b.sharpe,
  NOW()
FROM gold.strategy_definitions sd
LEFT JOIN (
  SELECT DISTINCT ON (strategy_id) *
  FROM gold.strategy_backtests
  ORDER BY strategy_id, run_date DESC
) b ON b.strategy_id::text = sd.strategy_id
WHERE sd.status = 'ACTIVE'
ON CONFLICT (strategy_id, portfolio_type) DO UPDATE SET
  win_rate          = EXCLUDED.win_rate,
  sharpe_ratio      = EXCLUDED.sharpe_ratio,
  max_drawdown_pct  = EXCLUDED.max_drawdown_pct,
  calculated_at     = NOW();
"""

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
    cur.execute(SQL_BACKTEST)
    print(f"✅ consumption.strategies_backtest_results: {cur.rowcount} rows upserted")
    cur.execute(SQL_MONTHLY)
    print(f"✅ consumption.performance_monthly_returns: {cur.rowcount} rows upserted")
    cur.execute(SQL_ATTRIBUTION)
    print(f"✅ consumption.performance_strategy_attribution: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
