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
    (strategy_name, ticker, name, asset_class,
     side, quantity, avg_entry_price, current_price,
     market_value, unrealized_pnl, unrealized_pnl_pct,
     days_held, status, weight_pct, portfolio_weight, entry_date, last_updated)
WITH live_ibkr AS (
    SELECT
        'LIVE_IBKR'            AS strategy_name,
        SPLIT_PART(ticker, '.', 1) AS ticker,
        SPLIT_PART(ticker, '.', 1) AS name,
        COALESCE(asset_class, 'STK') AS asset_class,
        side,
        quantity,
        avg_cost               AS avg_entry_price,
        market_price           AS current_price,
        market_value,
        unrealized_pnl,
        unrealized_pnl_pct,
        DATE_PART('day', NOW() - fetched_at)::int AS days_held,
        'ACTIVE'               AS status,
        fetched_at::date       AS entry_date
    FROM gold.ibkr_positions_live
    WHERE quantity IS NOT NULL AND market_value IS NOT NULL
),
live_paper AS (
    SELECT
        ps.strategy_id         AS strategy_name,
        ps.ticker,
        ar.name,
        ar.asset_class,
        'LONG'                 AS side,
        ps.quantity,
        ps.entry_price         AS avg_entry_price,
        ps.current_price,
        ps.quantity * ps.current_price AS market_value,
        ps.unrealized_pnl,
        ps.unrealized_pnl_pct,
        DATE_PART('day', NOW() - ps.created_at)::int AS days_held,
        ps.status,
        ps.created_at::date    AS entry_date
    FROM gold.paper_strategies ps
    LEFT JOIN gold.asset_registry ar ON ar.ticker = ps.ticker
    WHERE ps.status = 'ACTIVE'
      AND ps.quantity IS NOT NULL
      AND ps.quantity > 0
      AND ps.current_price IS NOT NULL
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
    c.strategy_name,
    c.ticker,
    c.name,
    c.asset_class,
    c.side,
    c.quantity,
    c.avg_entry_price,
    c.current_price,
    c.market_value,
    c.unrealized_pnl,
    c.unrealized_pnl_pct,
    c.days_held,
    c.status,
    ROUND(ABS(c.market_value) / NULLIF(t.portfolio_total, 0) * 100, 4) AS weight_pct,
    ROUND(ABS(c.market_value) / NULLIF(t.portfolio_total, 0) * 100, 4) AS portfolio_weight,
    c.entry_date,
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
