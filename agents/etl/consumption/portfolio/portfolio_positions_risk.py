# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Consumption: Portfolio Tab — Positions, Allocation, Risk Metrics
Reads from: gold.positions, gold.ibkr_positions_live, gold.paper_strategies,
            gold.portfolio_snapshots, gold.trade_executions, gold.asset_registry,
            silver.unified_prices
Writes to:  consumption.portfolio_positions_current
            consumption.portfolio_allocation_breakdown
            consumption.portfolio_risk_metrics
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# ── Current Positions ─────────────────────────────────────────────────────────

POSITIONS_SQL = """
TRUNCATE consumption.portfolio_positions_current;

INSERT INTO consumption.portfolio_positions_current
    (strategy_id, ticker, side, entry_date, entry_price, current_price,
     quantity, market_value, weight_pct, unrealized_pnl, realized_pnl,
     status, updated_at)
WITH live_ibkr AS (
    SELECT
        'LIVE_IBKR'            AS strategy_id,
        SPLIT_PART(ticker, '.', 1) AS ticker,
        side,
        avg_cost               AS entry_price,
        market_price           AS current_price,
        quantity,
        market_value,
        unrealized_pnl,
        0                      AS realized_pnl,
        'ACTIVE'               AS status,
        fetched_at::date       AS entry_date
    FROM gold.ibkr_positions_live
    WHERE quantity IS NOT NULL AND market_value IS NOT NULL
),
live_paper AS (
    SELECT
        p.strategy_id         AS strategy_id,
        p.ticker,
        p.side,
        p.entry_price         AS entry_price,
        p.current_price,
        p.quantity,
        p.market_value,
        p.unrealized_pnl,
        COALESCE(p.realized_pnl, 0) AS realized_pnl,
        p.status,
        p.opened_at::date     AS entry_date
    FROM gold.positions p
    WHERE p.status = 'ACTIVE'
      AND p.quantity IS NOT NULL
      AND p.quantity > 0
      AND p.current_price IS NOT NULL
),
combined AS (
    SELECT * FROM live_ibkr
    UNION ALL
    SELECT * FROM live_paper
),
total_val AS (
    SELECT SUM(ABS(market_value)) AS portfolio_total FROM combined
)
SELECT
    c.strategy_id,
    c.ticker,
    c.side,
    c.entry_date,
    c.entry_price,
    c.current_price,
    c.quantity,
    c.market_value,
    ROUND(ABS(c.market_value) / NULLIF(t.portfolio_total, 0) * 100, 4) AS weight_pct,
    c.unrealized_pnl,
    c.realized_pnl,
    c.status,
    NOW()
FROM combined c, total_val t;
"""

# ── Allocation Breakdown ──────────────────────────────────────────────────────

ALLOCATION_SQL = """
TRUNCATE consumption.portfolio_allocation_breakdown;

INSERT INTO consumption.portfolio_allocation_breakdown
    (portfolio_type, dimension, category,
     market_value, weight_pct, target_weight_pct, deviation_pct,
     contribution_pct, mtd_return_pct, updated_at)
-- By asset class
SELECT
    'PAPER'          AS portfolio_type,
    'asset_class'    AS dimension,
    COALESCE(ar.asset_class, 'UNKNOWN') AS category,
    SUM(ps.quantity * ps.current_price) AS market_value,
    ROUND(
        SUM(ps.quantity * ps.current_price)
        / NULLIF(SUM(SUM(ps.quantity * ps.current_price)) OVER (), 0) * 100
    , 2)             AS weight_pct,
    NULL::numeric    AS target_weight_pct,
    NULL::numeric    AS deviation_pct,
    NULL::numeric    AS contribution_pct,
    NULL::numeric    AS mtd_return_pct,
    NOW()
FROM gold.paper_strategies ps
LEFT JOIN gold.asset_registry ar ON ar.ticker = ps.ticker
WHERE ps.status = 'ACTIVE' AND ps.quantity > 0
GROUP BY ar.asset_class

UNION ALL

-- By strategy
SELECT
    'PAPER',
    'strategy',
    ps.strategy_id,
    SUM(ps.quantity * ps.current_price),
    ROUND(
        SUM(ps.quantity * ps.current_price)
        / NULLIF(SUM(SUM(ps.quantity * ps.current_price)) OVER (), 0) * 100
    , 2),
    NULL, NULL, NULL, NULL, NOW()
FROM gold.paper_strategies ps
WHERE ps.status = 'ACTIVE' AND ps.quantity > 0
GROUP BY ps.strategy_id;
"""

# ── Risk Metrics ──────────────────────────────────────────────────────────────

RISK_SQL = """
INSERT INTO consumption.portfolio_risk_metrics
    (portfolio_type,
     gross_exposure_pct, net_exposure_pct,
     long_exposure_pct, short_exposure_pct,
     cash_pct,
     top_5_concentration_pct, top_10_concentration_pct,
     portfolio_beta, volatility_annual,
     calculated_at)
WITH pos AS (
    SELECT
        SUM(ps.quantity * ps.current_price) FILTER (WHERE ps.quantity > 0) AS long_val,
        SUM(ABS(ps.quantity * ps.current_price)) FILTER (WHERE ps.quantity < 0) AS short_val,
        SUM(ps.quantity * ps.current_price) AS net_val,
        10000 AS portfolio_capital   -- from strategy assigned_capital
    FROM gold.paper_strategies ps
    WHERE ps.status = 'ACTIVE'
),
top5 AS (
    SELECT
        SUM(market_val) AS top5_val
    FROM (
        SELECT ps.quantity * ps.current_price AS market_val
        FROM gold.paper_strategies ps
        WHERE ps.status = 'ACTIVE' AND ps.quantity > 0
        ORDER BY market_val DESC
        LIMIT 5
    ) t
),
top10 AS (
    SELECT SUM(market_val) AS top10_val
    FROM (
        SELECT ps.quantity * ps.current_price AS market_val
        FROM gold.paper_strategies ps
        WHERE ps.status = 'ACTIVE' AND ps.quantity > 0
        ORDER BY market_val DESC
        LIMIT 10
    ) t
)
SELECT
    'PAPER',
    ROUND((p.long_val + p.short_val) / NULLIF(p.portfolio_capital, 0) * 100, 4),
    ROUND(p.net_val / NULLIF(p.portfolio_capital, 0) * 100, 4),
    ROUND(p.long_val / NULLIF(p.portfolio_capital, 0) * 100, 4),
    ROUND(COALESCE(p.short_val, 0) / NULLIF(p.portfolio_capital, 0) * 100, 4),
    ROUND((p.portfolio_capital - p.long_val + COALESCE(p.short_val,0))
          / NULLIF(p.portfolio_capital, 0) * 100, 4),
    ROUND(t5.top5_val  / NULLIF(p.long_val, 0) * 100, 2),
    ROUND(t10.top10_val / NULLIF(p.long_val, 0) * 100, 2),
    NULL::numeric,   -- beta: requires benchmark series
    NULL::numeric,   -- volatility: requires daily PnL history
    NOW()
FROM pos p, top5 t5, top10 t10
ON CONFLICT (portfolio_type) DO UPDATE SET
    gross_exposure_pct        = EXCLUDED.gross_exposure_pct,
    net_exposure_pct          = EXCLUDED.net_exposure_pct,
    long_exposure_pct         = EXCLUDED.long_exposure_pct,
    short_exposure_pct        = EXCLUDED.short_exposure_pct,
    cash_pct                  = EXCLUDED.cash_pct,
    top_5_concentration_pct   = EXCLUDED.top_5_concentration_pct,
    top_10_concentration_pct  = EXCLUDED.top_10_concentration_pct,
    calculated_at             = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('gold.positions')")
    if cur.fetchone()[0] is None:
        print("⚠️ gold.positions does not exist — skipping")
        conn.close()
        return
    cur.execute("SELECT COUNT(*) FROM gold.positions WHERE status = 'ACTIVE'")
    if cur.fetchone()[0] == 0:
        print("⚠️ gold.positions has no active positions — skipping")
        conn.close()
        return

    cur.execute(POSITIONS_SQL)
    print(f"✅ consumption.portfolio_positions_current — refreshed")

    cur.execute(ALLOCATION_SQL)
    print(f"✅ consumption.portfolio_allocation_breakdown — refreshed")

    cur.execute(RISK_SQL)
    print(f"✅ consumption.portfolio_risk_metrics — {cur.rowcount} rows upserted")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
