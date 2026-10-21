# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Consumption: Portfolio Tab — Positions, Allocation, Risk Metrics
Reads from: gold.positions, gold.ibkr_positions_live, gold.manual_orders,
            gold.asset_registry, gold.paper_strategies
Writes to:  consumption.portfolio_positions_current
            consumption.portfolio_positions_paper
            consumption.portfolio_allocation_breakdown
            consumption.portfolio_risk_metrics

2026-07-19: split live IBKR + manual positions (portfolio_positions_current)
from paper-strategy positions (portfolio_positions_paper). Short positions are
stored with negative market_value in the consumption tables so gross and net
exposure diverge correctly.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS consumption.portfolio_positions_paper (
    id SERIAL PRIMARY KEY,
    strategy_id VARCHAR(64),
    ticker VARCHAR(32) NOT NULL,
    side VARCHAR(10) DEFAULT 'LONG',
    entry_date DATE,
    entry_price NUMERIC,
    current_price NUMERIC,
    quantity NUMERIC,
    market_value NUMERIC,
    weight_pct NUMERIC,
    unrealized_pnl NUMERIC,
    realized_pnl NUMERIC,
    status VARCHAR(20) DEFAULT 'OPEN',
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    source VARCHAR(32),
    capital NUMERIC,
    invested_capital NUMERIC,
    trades_count INTEGER DEFAULT 0,
    execution_mode VARCHAR(32),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    available_capital NUMERIC,
    CONSTRAINT portfolio_positions_paper_strategy_ticker UNIQUE (strategy_id, ticker)
);

CREATE TABLE IF NOT EXISTS consumption.portfolio_allocation_breakdown (
    portfolio_type VARCHAR(32) NOT NULL,
    dimension VARCHAR(32) NOT NULL,
    category VARCHAR(64) NOT NULL,
    market_value NUMERIC,
    weight_pct NUMERIC,
    target_weight_pct NUMERIC,
    deviation_pct NUMERIC,
    contribution_pct NUMERIC,
    mtd_return_pct NUMERIC,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (portfolio_type, dimension, category)
);
"""

# ── Live positions (IBKR + manual orders) ─────────────────────────────────────
POSITIONS_LIVE_SQL = """
-- 2026-07-29 (t_749e13f0): was TRUNCATE. The table now also carries
-- PAPER_TRADING rows synced from gold.paper_trades_synthetic
-- (sync_paper_positions_current.py); only clear the live/manual rows this
-- statement owns.
DELETE FROM consumption.portfolio_positions_current
WHERE execution_mode IN ('LIVE_TRADING', 'MANUAL')
   OR source IN ('ibkr', 'manual');

WITH live_equity AS (
    -- t_65d96f4a: market_value is USD (contract ccy); the denominator must
    -- be USD too. Was net_liquidation (HKD base) -> weights understated 7.85x.
    SELECT COALESCE(net_liquidation_usd, 0) AS equity
    FROM gold.ibkr_account_summary
    ORDER BY fetched_at DESC
    LIMIT 1
),
live_ibkr AS (
    SELECT
        'LIVE_IBKR' AS strategy_id,
        SPLIT_PART(ticker, '.', 1) AS ticker,
        side,
        avg_cost AS entry_price,
        market_price AS current_price,
        quantity,
        CASE WHEN side = 'SHORT' THEN -ABS(market_value) ELSE market_value END AS market_value,
        unrealized_pnl,
        0 AS realized_pnl,
        'ACTIVE' AS status,
        fetched_at::date AS entry_date,
        'ibkr' AS source,
        'LIVE_TRADING' AS execution_mode,
        fetched_at AS created_at
    FROM gold.ibkr_positions_live
    WHERE quantity IS NOT NULL AND market_value IS NOT NULL
),
manual_agg AS (
    -- 2026-09-12 (t_bb898628): was GROUP BY ticker, side — a second filled
    -- order for the same ticker (GLD buy+sell from the paper_uat reconciler)
    -- produced duplicate (strategy_id, ticker) keys -> CardinalityViolation.
    -- Net to ONE row per ticker (BUY + / SELL -); skip flat tickers.
    SELECT
        'MANUAL' AS strategy_id,
        ticker,
        CASE WHEN net_qty < 0 THEN 'SHORT' ELSE 'LONG' END AS side,
        wavg_entry AS entry_price,
        wavg_entry AS current_price,
        ABS(net_qty) AS quantity,
        CASE WHEN net_qty < 0
             THEN -ABS(net_qty * wavg_entry)
             ELSE ABS(net_qty * wavg_entry)
        END AS market_value,
        0 AS unrealized_pnl,
        0 AS realized_pnl,
        'OPEN' AS status,
        entry_date,
        'manual' AS source,
        'MANUAL' AS execution_mode,
        created_at
    FROM (
        SELECT
            ticker,
            SUM(CASE WHEN side = 'SELL' THEN -qty ELSE qty END) AS net_qty,
            COALESCE(
                SUM(CASE WHEN side <> 'SELL' THEN qty * COALESCE(entry_price, 0) END)
                / NULLIF(SUM(CASE WHEN side <> 'SELL' THEN qty END), 0),
                AVG(COALESCE(entry_price, 0)),
                0
            ) AS wavg_entry,
            MIN(DATE(created_at)) AS entry_date,
            MIN(created_at) AS created_at
        FROM gold.manual_orders
        WHERE status IN ('accepted', 'open', 'filled')
        GROUP BY ticker
        HAVING SUM(CASE WHEN side = 'SELL' THEN -qty ELSE qty END) <> 0
    ) n
),
combined AS (
    SELECT * FROM live_ibkr
    UNION ALL
    SELECT * FROM manual_agg
),
total_val AS (
    SELECT COALESCE(SUM(ABS(market_value)), 0) AS portfolio_total FROM combined
)
INSERT INTO consumption.portfolio_positions_current
    (strategy_id, ticker, side, entry_date, entry_price, current_price,
     quantity, market_value, weight_pct, unrealized_pnl, realized_pnl,
     status, updated_at, source, execution_mode, created_at)
SELECT
    strategy_id,
    ticker,
    side,
    entry_date,
    entry_price,
    current_price,
    quantity,
    market_value,
    CASE
        WHEN le.equity > 0 THEN ROUND(ABS(market_value) / le.equity * 100, 4)
        WHEN t.portfolio_total > 0 THEN ROUND(ABS(market_value) / t.portfolio_total * 100, 4)
        ELSE NULL
    END AS weight_pct,
    unrealized_pnl,
    realized_pnl,
    status,
    NOW(),
    source,
    execution_mode,
    created_at
FROM combined, total_val t, live_equity le
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
    strategy_id    = EXCLUDED.strategy_id,
    side           = EXCLUDED.side,
    entry_date     = EXCLUDED.entry_date,
    entry_price    = EXCLUDED.entry_price,
    current_price  = EXCLUDED.current_price,
    quantity       = EXCLUDED.quantity,
    market_value   = EXCLUDED.market_value,
    weight_pct     = EXCLUDED.weight_pct,
    unrealized_pnl = EXCLUDED.unrealized_pnl,
    realized_pnl   = EXCLUDED.realized_pnl,
    status         = EXCLUDED.status,
    source         = EXCLUDED.source,
    execution_mode = EXCLUDED.execution_mode,
    updated_at     = NOW(),
    created_at     = EXCLUDED.created_at;
"""

# ── Paper positions (from gold.positions) ─────────────────────────────────────
POSITIONS_PAPER_SQL = """
TRUNCATE consumption.portfolio_positions_paper;

WITH paper_total AS (
    SELECT COALESCE(SUM(ABS(market_value)), 0) AS portfolio_total
    FROM gold.positions
    WHERE status IN ('ACTIVE', 'OPEN')
      AND quantity IS NOT NULL
      AND market_value IS NOT NULL
)
INSERT INTO consumption.portfolio_positions_paper
    (strategy_id, ticker, side, entry_date, entry_price, current_price,
     quantity, market_value, weight_pct, unrealized_pnl, realized_pnl,
     status, updated_at, source, execution_mode, created_at)
SELECT
    p.strategy_id,
    p.ticker,
    p.side,
    p.opened_at::date AS entry_date,
    p.entry_price,
    p.current_price,
    p.quantity,
    CASE WHEN p.side = 'SHORT' THEN -ABS(p.market_value) ELSE p.market_value END AS market_value,
    CASE WHEN pt.portfolio_total > 0
         THEN ROUND(ABS(p.market_value) / pt.portfolio_total * 100, 4)
         ELSE NULL
    END AS weight_pct,
    p.unrealized_pnl,
    COALESCE(p.realized_pnl, 0) AS realized_pnl,
    p.status,
    NOW(),
    'algo' AS source,
    'PAPER_TRADING' AS execution_mode,
    p.opened_at AS created_at
FROM gold.positions p, paper_total pt
WHERE p.status IN ('ACTIVE', 'OPEN')
  AND p.quantity IS NOT NULL
  AND p.market_value IS NOT NULL
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
    side          = EXCLUDED.side,
    entry_date    = EXCLUDED.entry_date,
    entry_price   = EXCLUDED.entry_price,
    current_price = EXCLUDED.current_price,
    quantity      = EXCLUDED.quantity,
    market_value  = EXCLUDED.market_value,
    weight_pct    = EXCLUDED.weight_pct,
    unrealized_pnl= EXCLUDED.unrealized_pnl,
    realized_pnl  = EXCLUDED.realized_pnl,
    status        = EXCLUDED.status,
    source        = EXCLUDED.source,
    execution_mode= EXCLUDED.execution_mode,
    updated_at    = NOW(),
    created_at    = EXCLUDED.created_at;
"""

# ── Allocation Breakdown (paper only) ─────────────────────────────────────────
ALLOCATION_SQL = """
TRUNCATE consumption.portfolio_allocation_breakdown;

INSERT INTO consumption.portfolio_allocation_breakdown
    (portfolio_type, dimension, category, market_value, weight_pct,
     target_weight_pct, deviation_pct, contribution_pct, mtd_return_pct, updated_at)
WITH signed_paper AS (
    SELECT
        strategy_id,
        ticker,
        side,
        CASE WHEN side = 'SHORT' THEN -ABS(market_value) ELSE market_value END AS market_value,
        ABS(market_value) AS abs_market_value
    FROM consumption.portfolio_positions_paper
    WHERE status IN ('OPEN', 'ACTIVE')
),
total AS (
    SELECT COALESCE(SUM(abs_market_value), 0) AS portfolio_total
    FROM signed_paper
),
by_asset AS (
    SELECT
        COALESCE(ar.asset_class, 'UNKNOWN') AS category,
        COALESCE(SUM(market_value), 0) AS market_value,
        CASE WHEN t.portfolio_total > 0
             THEN ROUND(SUM(abs_market_value) / t.portfolio_total * 100, 2)
             ELSE 0 END AS weight_pct
    FROM signed_paper s
    LEFT JOIN gold.asset_registry ar ON ar.ticker = s.ticker
    CROSS JOIN total t
    GROUP BY ar.asset_class, t.portfolio_total
),
by_strategy AS (
    SELECT
        strategy_id AS category,
        COALESCE(SUM(market_value), 0) AS market_value,
        CASE WHEN t.portfolio_total > 0
             THEN ROUND(SUM(abs_market_value) / t.portfolio_total * 100, 2)
             ELSE 0 END AS weight_pct
    FROM signed_paper s
    CROSS JOIN total t
    GROUP BY strategy_id, t.portfolio_total
)
SELECT 'PAPER', 'asset_class', category, market_value, weight_pct, NULL::numeric, NULL::numeric, NULL::numeric, NULL::numeric, NOW()
FROM by_asset
UNION ALL
SELECT 'PAPER', 'strategy', category, market_value, weight_pct, NULL::numeric, NULL::numeric, NULL::numeric, NULL::numeric, NOW()
FROM by_strategy;
"""

# ── Risk Metrics (paper only) ───────────────────────────────────────────────
RISK_SQL = """
INSERT INTO consumption.portfolio_risk_metrics
    (portfolio_type,
     gross_exposure_pct, net_exposure_pct,
     long_exposure_pct, short_exposure_pct,
     cash_pct,
     top_5_concentration_pct, top_10_concentration_pct,
     portfolio_beta, volatility_annual,
     calculated_at)
WITH signed_paper AS (
    SELECT
        CASE WHEN side = 'SHORT' THEN -ABS(market_value) ELSE market_value END AS market_value,
        ABS(market_value) AS abs_market_value
    FROM consumption.portfolio_positions_paper
    WHERE status IN ('OPEN', 'ACTIVE')
),
capital AS (
    SELECT COALESCE(SUM(abs_market_value), 0) AS portfolio_capital
    FROM signed_paper
),
pos AS (
    SELECT
        COALESCE(SUM(market_value) FILTER (WHERE market_value > 0), 0) AS long_val,
        COALESCE(SUM(ABS(market_value)) FILTER (WHERE market_value < 0), 0) AS short_val,
        COALESCE(SUM(market_value), 0) AS net_val
    FROM signed_paper
),
top5 AS (
    SELECT COALESCE(SUM(abs_market_value), 0) AS top5_val
    FROM (
        SELECT abs_market_value
        FROM signed_paper
        ORDER BY abs_market_value DESC
        LIMIT 5
    ) t
),
top10 AS (
    SELECT COALESCE(SUM(abs_market_value), 0) AS top10_val
    FROM (
        SELECT abs_market_value
        FROM signed_paper
        ORDER BY abs_market_value DESC
        LIMIT 10
    ) t
)
SELECT
    'PAPER',
    ROUND(100.0, 4),
    ROUND(p.net_val / NULLIF(c.portfolio_capital, 0) * 100, 4),
    ROUND(p.long_val / NULLIF(c.portfolio_capital, 0) * 100, 4),
    ROUND(p.short_val / NULLIF(c.portfolio_capital, 0) * 100, 4),
    0,
    ROUND(t5.top5_val / NULLIF(c.portfolio_capital, 0) * 100, 2),
    ROUND(t10.top10_val / NULLIF(c.portfolio_capital, 0) * 100, 2),
    NULL,
    NULL,
    NOW()
FROM pos p, capital c, top5 t5, top10 t10
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

    cur.execute(CREATE_TABLES_SQL)

    # Live positions
    cur.execute("SELECT to_regclass('gold.ibkr_positions_live')")
    has_ibkr = cur.fetchone()[0] is not None
    cur.execute("SELECT to_regclass('gold.manual_orders')")
    has_manual = cur.fetchone()[0] is not None
    if has_ibkr or has_manual:
        cur.execute(POSITIONS_LIVE_SQL)
        print("✅ consumption.portfolio_positions_current refreshed")
    else:
        print("⚠️  no live position sources available — skipping live refresh")

    # Paper positions
    cur.execute("SELECT to_regclass('gold.positions')")
    has_paper = cur.fetchone()[0] is not None
    if has_paper:
        cur.execute("SELECT COUNT(*) FROM gold.positions WHERE status IN ('ACTIVE','OPEN')")
        if cur.fetchone()[0] > 0:
            cur.execute(POSITIONS_PAPER_SQL)
            print("✅ consumption.portfolio_positions_paper refreshed")
        else:
            print("⚠️  gold.positions has no active positions — skipping paper refresh")
    else:
        print("⚠️  gold.positions does not exist — skipping paper refresh")

    # Allocation & risk
    cur.execute(ALLOCATION_SQL)
    print("✅ consumption.portfolio_allocation_breakdown refreshed")
    cur.execute(RISK_SQL)
    print(f"✅ consumption.portfolio_risk_metrics — {cur.rowcount} rows upserted")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
