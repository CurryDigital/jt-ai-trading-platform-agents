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
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_BACKTEST = """
INSERT INTO consumption.strategies_backtest_results
  (strategy_id, ticker, asset_class, direction, time_horizon,
   period_start, period_end, total_days,
   total_return_pct, annualized_return_pct, benchmark_return_pct, alpha_pct,
   volatility_annual, sharpe_ratio, sortino_ratio,
   max_drawdown_pct, calmar_ratio,
   total_trades, win_rate, profit_factor,
   avg_trade_return_pct, avg_win_pct, avg_loss_pct,
   equity_curve_json, calculated_at)
SELECT
  b.strategy_id,
  b.ticker,
  b.asset_class,
  sd.direction,
  sd.time_horizon,
  b.calculated_at::date - INTERVAL '1 year' AS period_start,
  b.calculated_at::date AS period_end,
  365 AS total_days,
  b.total_return * 100 AS total_return_pct,
  b.total_return * 100 AS annualized_return_pct,  -- simplified
  NULL AS benchmark_return_pct,
  NULL AS alpha_pct,
  NULL AS volatility_annual,
  b.sharpe_ratio,
  NULL AS sortino_ratio,
  b.max_drawdown * 100 AS max_drawdown_pct,
  NULL AS calmar_ratio,
  b.num_trades AS total_trades,
  b.win_rate,
  b.profit_factor,
  b.avg_trade_return * 100 AS avg_trade_return_pct,
  NULL AS avg_win_pct,
  NULL AS avg_loss_pct,
  NULL AS equity_curve_json,
  b.calculated_at
FROM gold.strategy_backtests b
JOIN gold.strategy_definitions sd ON sd.strategy_id = b.strategy_id
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
  total_return_pct   = EXCLUDED.total_return_pct,
  sharpe_ratio       = EXCLUDED.sharpe_ratio,
  win_rate           = EXCLUDED.win_rate,
  calculated_at      = EXCLUDED.calculated_at;
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
  sd.name AS strategy_name,
  'paper' AS portfolio_type,
  100.0 / NULLIF((SELECT COUNT(*) FROM gold.strategy_definitions WHERE status = 'ACTIVE'), 0)
    AS allocated_capital_pct,
  -- Latest backtest return as proxy
  b.total_return * 100 AS return_pct,
  b.num_trades,
  b.win_rate,
  b.avg_trade_return * 100 AS avg_trade_return_pct,
  ABS(b.max_drawdown) * 100 AS max_drawdown_pct,
  b.sharpe_ratio,
  NOW()
FROM gold.strategy_definitions sd
LEFT JOIN (
  SELECT DISTINCT ON (strategy_id) *
  FROM gold.strategy_backtests
  ORDER BY strategy_id, calculated_at DESC
) b ON b.strategy_id = sd.strategy_id
WHERE sd.status = 'ACTIVE'
ON CONFLICT (strategy_id, portfolio_type) DO UPDATE SET
  return_pct        = EXCLUDED.return_pct,
  win_rate          = EXCLUDED.win_rate,
  sharpe_ratio      = EXCLUDED.sharpe_ratio,
  calculated_at     = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
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
