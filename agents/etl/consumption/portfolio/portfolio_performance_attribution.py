#!/usr/bin/env python3
"""
Consumption: Portfolio Tab — PnL History & Performance Attribution
Reads from: gold.strategy_registry, gold.paper_trades_synthetic (forward-paper attribution),
            gold.trade_executions (monthly returns; legacy source, may no-op)
Writes to:  consumption.performance_monthly_returns
            consumption.performance_strategy_attribution
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection, require_table

# ── Monthly Returns ───────────────────────────────────────────────────────────

MONTHLY_RETURNS_SQL = """
INSERT INTO consumption.performance_monthly_returns
    (portfolio_type, year, month, return_pct, benchmark_return_pct, excess_return_pct)
SELECT
    'paper'                     AS portfolio_type,
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
# 2026-08-24 (t_1cfb20c2): rebuilt to source from the CANONICAL paper stack
# (gold.strategy_registry execution_mode='PAPER' + gold.paper_trades_synthetic)
# instead of the empty legacy gold.trade_executions table. Full-rebuild sync:
# upserts the registry PAPER set, then deletes any 'paper' row not in that set
# (sweeps TEST_*/manual_close/legacy S00x placeholders and prevents recurrence).
# Semantics:
#   num_trades/win_rate/avg_trade_return_pct/return_pct: realized CLOSED
#     forward_paper trades from gold.paper_trades_synthetic (NULL when a
#     strategy has no closed forward evidence yet — never replay/legacy rows).
#   return_pct = 100 * realized_pnl$ / assigned_capital.
#   contribution_pct = 100 * strategy realized pnl / total realized paper pnl
#     (NULL when the total is zero/NULL — ledger is mostly open positions).
#   allocated_capital_pct = assigned_capital share of the PAPER set.
#   sharpe_ratio/max_drawdown_pct = OOS research metrics from strategy_registry.

# 2026-09-12 (t_0a9e99af): guard strategy_name against the consumption
# column width at write time. Root cause of the CHRONIC
# StringDataRightTruncation: gold.strategy_registry.name is varchar(200) but
# consumption.performance_strategy_attribution.strategy_name is varchar(100)
# (hk_ipo_postlisting_drift_p2 name = 121 chars). The LEFT() bound is read
# from information_schema so the guard auto-adapts if the column is widened
# (varchar(200) ALTER handed to scrum_master as a follow-up card).
ATTRIBUTION_SQL = """
INSERT INTO consumption.performance_strategy_attribution
    (strategy_id, strategy_name, portfolio_type,
     allocated_capital_pct, contribution_pct,
     return_pct, num_trades, win_rate,
     avg_trade_return_pct, max_drawdown_pct, sharpe_ratio, calculated_at)
WITH paper_strats AS (
    SELECT strategy_id, name, assigned_capital, sharpe_oos, max_drawdown_oos
    FROM gold.strategy_registry
    WHERE execution_mode = 'PAPER'
),
tot AS (
    SELECT SUM(assigned_capital) AS cap_total FROM paper_strats
),
led AS (
    SELECT
        strategy_id,
        COUNT(*) FILTER (WHERE status = 'closed')                    AS closed_n,
        SUM(pnl) FILTER (WHERE status = 'closed')                    AS pnl_sum,
        AVG(pnl_pct) FILTER (WHERE status = 'closed')                AS avg_pct,
        AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END)
            FILTER (WHERE status = 'closed')                         AS wr
    FROM gold.paper_trades_synthetic
    WHERE evidence_class = 'forward_paper'
    GROUP BY strategy_id
),
pnl_tot AS (
    SELECT SUM(l.pnl_sum) AS pnl_total
    FROM led l
    JOIN paper_strats ps ON ps.strategy_id = l.strategy_id
)
SELECT
    ps.strategy_id,
    LEFT(ps.name, (
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'consumption'
          AND table_name = 'performance_strategy_attribution'
          AND column_name = 'strategy_name'
    ))                             AS strategy_name,
    'paper'                        AS portfolio_type,
    ROUND(100 * ps.assigned_capital / NULLIF(tot.cap_total, 0), 2)
                                   AS allocated_capital_pct,
    ROUND(100 * led.pnl_sum / NULLIF(pnl_tot.pnl_total, 0), 4)
                                   AS contribution_pct,
    CASE WHEN led.closed_n > 0 AND ps.assigned_capital > 0
         THEN ROUND(100 * led.pnl_sum / ps.assigned_capital, 4)
    END                            AS return_pct,
    COALESCE(led.closed_n, 0)      AS num_trades,
    ROUND(led.wr, 4)               AS win_rate,
    ROUND(led.avg_pct, 4)          AS avg_trade_return_pct,
    ROUND(ps.max_drawdown_oos * 100, 2) AS max_drawdown_pct,
    ps.sharpe_oos                  AS sharpe_ratio,
    NOW()
FROM paper_strats ps
CROSS JOIN tot
CROSS JOIN pnl_tot
LEFT JOIN led ON led.strategy_id = ps.strategy_id
ON CONFLICT (strategy_id, portfolio_type) DO UPDATE SET
    strategy_name         = EXCLUDED.strategy_name,
    allocated_capital_pct = EXCLUDED.allocated_capital_pct,
    contribution_pct      = EXCLUDED.contribution_pct,
    return_pct            = EXCLUDED.return_pct,
    num_trades            = EXCLUDED.num_trades,
    win_rate              = EXCLUDED.win_rate,
    avg_trade_return_pct  = EXCLUDED.avg_trade_return_pct,
    max_drawdown_pct      = EXCLUDED.max_drawdown_pct,
    sharpe_ratio          = EXCLUDED.sharpe_ratio,
    calculated_at         = NOW();
"""

# Sweep rows not backed by the live PAPER registry set (test/manual/legacy).
ATTRIBUTION_SWEEP_SQL = """
DELETE FROM consumption.performance_strategy_attribution
WHERE portfolio_type = 'paper'
  AND strategy_id NOT IN (
      SELECT strategy_id FROM gold.strategy_registry
      WHERE execution_mode = 'PAPER'
  );
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    require_table(conn, 'consumption', 'performance_monthly_returns')

    cur.execute(MONTHLY_RETURNS_SQL)
    print(f"✅ consumption.performance_monthly_returns — {cur.rowcount} rows upserted")

    cur.execute(ATTRIBUTION_SQL)
    print(f"✅ consumption.performance_strategy_attribution — {cur.rowcount} rows upserted")

    cur.execute(ATTRIBUTION_SWEEP_SQL)
    print(f"🧹 consumption.performance_strategy_attribution — {cur.rowcount} stale/test rows swept")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
