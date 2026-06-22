#!/usr/bin/env python3
"""
Consumption: Portfolio Tab — PnL History & Performance Attribution
Reads from: gold.paper_strategies, gold.trade_executions, gold.strategy_definitions
Writes to:  consumption.performance_monthly_returns
            consumption.performance_strategy_attribution
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# ── Monthly Returns ───────────────────────────────────────────────────────────

MONTHLY_RETURNS_SQL = """
INSERT INTO consumption.performance_monthly_returns
    (portfolio_type, year, month, return_pct, benchmark_return_pct, excess_return_pct)
SELECT
    'PAPER'                     AS portfolio_type,
    EXTRACT(YEAR  FROM te.executed_at)::int AS year,
    EXTRACT(MONTH FROM te.executed_at)::int AS month,
    ROUND(SUM(te.pnl_pct), 4)  AS return_pct,
    NULL::numeric               AS benchmark_return_pct,
    NULL::numeric               AS excess_return_pct
FROM gold.trade_executions te
WHERE te.executed_at IS NOT NULL
GROUP BY year, month
ON CONFLICT (portfolio_type, year, month) DO UPDATE SET
    return_pct = EXCLUDED.return_pct,
    excess_return_pct = EXCLUDED.excess_return_pct;
"""

# ── Strategy Attribution ──────────────────────────────────────────────────────

ATTRIBUTION_SQL = """
INSERT INTO consumption.performance_strategy_attribution
    (strategy_id, strategy_name, portfolio_type,
     allocated_capital_pct, contribution_pct,
     return_pct, num_trades, win_rate,
     avg_trade_return_pct, max_drawdown_pct, sharpe_ratio, calculated_at)
WITH strat_perf AS (
    SELECT
        te.strategy_id,
        COUNT(*)                                           AS num_trades,
        ROUND(AVG(te.pnl_pct), 4)                         AS avg_trade_return_pct,
        ROUND(SUM(te.pnl_pct), 4)                         AS total_return_pct,
        ROUND(
            SUM(CASE WHEN te.pnl_pct > 0 THEN 1.0 ELSE 0 END)
            / NULLIF(COUNT(*), 0)
        , 4)                                               AS win_rate
    FROM gold.trade_executions te
    WHERE te.executed_at IS NOT NULL
    GROUP BY te.strategy_id
)
SELECT
    sp.strategy_id,
    sp.strategy_id   AS strategy_name,
    'PAPER'                    AS portfolio_type,
    NULL::numeric              AS allocated_capital_pct,
    NULL::numeric              AS contribution_pct,
    sp.total_return_pct        AS return_pct,
    sp.num_trades,
    sp.win_rate,
    sp.avg_trade_return_pct,
    sb.max_dd * 100      AS max_drawdown_pct,
    sb.sharpe AS sharpe_ratio,
    NOW()
FROM strat_perf sp
LEFT JOIN (
    SELECT DISTINCT ON (strategy_id)
        strategy_id::varchar, max_dd, sharpe
    FROM gold.strategy_backtests
    ORDER BY strategy_id, run_date DESC
) sb ON sb.strategy_id = sp.strategy_id
ON CONFLICT (strategy_id, portfolio_type) DO UPDATE SET
    return_pct            = EXCLUDED.return_pct,
    num_trades            = EXCLUDED.num_trades,
    win_rate              = EXCLUDED.win_rate,
    avg_trade_return_pct  = EXCLUDED.avg_trade_return_pct,
    sharpe_ratio          = EXCLUDED.sharpe_ratio,
    calculated_at         = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('gold.trade_executions')")
    if cur.fetchone()[0] is None:
        print("⚠️ gold.trade_executions does not exist — skipping")
        conn.close()
        return
    cur.execute("SELECT COUNT(*) FROM gold.trade_executions")
    if cur.fetchone()[0] == 0:
        print("⚠️ gold.trade_executions empty — skipping")
        conn.close()
        return

    cur.execute(MONTHLY_RETURNS_SQL)
    print(f"✅ consumption.performance_monthly_returns — {cur.rowcount} rows upserted")

    cur.execute(ATTRIBUTION_SQL)
    print(f"✅ consumption.performance_strategy_attribution — {cur.rowcount} rows upserted")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
