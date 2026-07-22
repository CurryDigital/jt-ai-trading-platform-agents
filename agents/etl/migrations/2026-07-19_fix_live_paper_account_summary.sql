-- Migration: 2026-07-19
-- Fixes live equity overwrite, separates live/paper positions in consumption,
-- and rebuilds consumption.account_summary with correct cash_pct, buying_power
-- and signed market-value conventions.

-- The live table has a legacy check constraint that only allowed algo/manual.
-- Live positions now come from IBKR, so we must allow that source as well.
ALTER TABLE consumption.portfolio_positions_current
DROP CONSTRAINT IF EXISTS portfolio_positions_current_source_chk;

ALTER TABLE consumption.portfolio_positions_current
ADD CONSTRAINT portfolio_positions_current_source_chk
CHECK (source IS NULL OR source IN ('algo','manual','ibkr')) NOT VALID;

-- 1. Backfill gold.positions from paper rows currently stranded in the live
--    consumption table. These were previously mixed with live positions and
--    need a source-of-truth home before we split the tables.
INSERT INTO gold.positions
    (strategy_id, ticker, side, quantity, entry_price, current_price, market_value,
     unrealized_pnl, realized_pnl, status, opened_at, updated_at)
SELECT
    strategy_id,
    ticker,
    side,
    quantity,
    entry_price,
    current_price,
    market_value,
    unrealized_pnl,
    realized_pnl,
    status,
    created_at AS opened_at,
    NOW() AS updated_at
FROM consumption.portfolio_positions_current
WHERE execution_mode = 'PAPER_TRADING'
  AND strategy_id <> 'LIVE_IBKR_CASH'
ON CONFLICT DO NOTHING;

-- 2. Create the paper-only consumption table (mirrors current_positions but
--    keys on strategy+ticker, not just ticker, because multiple paper strategies
--    can hold the same symbol).
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

-- 3. Allocation table may not exist yet; the risk script depends on it.
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

-- 4. Seed the paper table with the same rows we just promoted to gold.positions.
INSERT INTO consumption.portfolio_positions_paper
    (strategy_id, ticker, side, entry_date, entry_price, current_price, quantity,
     market_value, weight_pct, unrealized_pnl, realized_pnl, status, updated_at,
     source, capital, invested_capital, trades_count, execution_mode, created_at, available_capital)
SELECT
    strategy_id,
    ticker,
    side,
    entry_date,
    entry_price,
    current_price,
    quantity,
    CASE WHEN side = 'SHORT' THEN -ABS(market_value) ELSE market_value END AS market_value,
    weight_pct,
    unrealized_pnl,
    realized_pnl,
    status,
    NOW() AS updated_at,
    source,
    capital,
    invested_capital,
    trades_count,
    execution_mode,
    created_at,
    available_capital
FROM consumption.portfolio_positions_current
WHERE execution_mode = 'PAPER_TRADING'
  AND strategy_id <> 'LIVE_IBKR_CASH'
ON CONFLICT (strategy_id, ticker) DO NOTHING;

-- 5. Backfill live gold.account_nav_daily from the authoritative account-level
--    snapshots (portfolio_type = account number). Forward-fill from the most
--    recent snapshot so the curve is not polluted by the positions-only
--    overwrite that build_account_nav_daily was doing.
WITH dup_fill AS (
    SELECT
        snapshot_date,
        total_value,
        LEAD(snapshot_date) OVER (ORDER BY snapshot_date) AS next_date
    FROM gold.portfolio_snapshots
    WHERE portfolio_type = 'DUP825942'
)
UPDATE gold.account_nav_daily n
SET equity = d.total_value
FROM dup_fill d
WHERE n.book = 'live'
  AND n.as_of_date >= d.snapshot_date
  AND (d.next_date IS NULL OR n.as_of_date < d.next_date);

-- 6. Replace the consumption.account_summary view with one that:
--    * reads live equity, buying_power and cash from gold.ibkr_account_summary
--    * uses signed market values in consumption.portfolio_positions_current
--    * separates paper positions into consumption.portfolio_positions_paper
--    * computes gross vs net exposure correctly (shorts subtract from net)
CREATE OR REPLACE VIEW consumption.account_summary AS
WITH books AS (
    SELECT 'live'::character varying(10) AS book
    UNION ALL
    SELECT 'paper'::character varying(10)
),
live_account AS (
    SELECT
        account,
        net_liquidation,
        buying_power,
        COALESCE(cash_hkd, 0) + COALESCE(cash_usd, 0) AS cash_value
    FROM gold.ibkr_account_summary
    ORDER BY fetched_at DESC
    LIMIT 1
),
live_nav AS (
    SELECT book, as_of_date, equity, pnl,
           LAG(equity) OVER (PARTITION BY book ORDER BY as_of_date) AS prev_equity
    FROM gold.account_nav_daily
    WHERE book = 'live'
),
latest_live_nav AS (
    SELECT book, as_of_date, equity, pnl, prev_equity,
           ROW_NUMBER() OVER (PARTITION BY book ORDER BY as_of_date DESC) AS rn
    FROM live_nav
),
paper_nav AS (
    SELECT book, as_of_date, equity, pnl,
           LAG(equity) OVER (PARTITION BY book ORDER BY as_of_date) AS prev_equity
    FROM gold.account_nav_daily
    WHERE book = 'paper'
),
latest_paper_nav AS (
    SELECT book, as_of_date, equity, pnl, prev_equity,
           ROW_NUMBER() OVER (PARTITION BY book ORDER BY as_of_date DESC) AS rn
    FROM paper_nav
),
live_positions AS (
    SELECT
        COALESCE(SUM(ABS(market_value)), 0) AS gross_invested,
        COALESCE(SUM(market_value), 0) AS net_invested,
        COALESCE(SUM(unrealized_pnl), 0) AS total_unrealized_pnl,
        COUNT(*)::integer AS open_positions
    FROM consumption.portfolio_positions_current
    WHERE status IN ('OPEN', 'ACTIVE')
),
paper_positions AS (
    SELECT
        COALESCE(SUM(ABS(market_value)), 0) AS gross_invested,
        COALESCE(SUM(market_value), 0) AS net_invested,
        COALESCE(SUM(unrealized_pnl), 0) AS total_unrealized_pnl,
        COUNT(*)::integer AS open_positions
    FROM consumption.portfolio_positions_paper
    WHERE status IN ('OPEN', 'ACTIVE')
)
SELECT
    b.book,
    CASE
        WHEN b.book = 'live' THEN COALESCE(la.net_liquidation, 0)
        ELSE COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0)
    END AS equity,
    COALESCE(
        CASE WHEN b.book = 'live' THEN ln.equity - ln.prev_equity
             ELSE NULLIF(pn.equity, 0) - pn.prev_equity END,
        CASE WHEN b.book = 'live' THEN ln.pnl ELSE pn.pnl END,
        0
    ) AS day_pnl,
    CASE
        WHEN b.book = 'live' AND ln.prev_equity > 0
            THEN (ln.equity - ln.prev_equity) / ln.prev_equity * 100
        WHEN b.book = 'paper' AND NULLIF(pn.prev_equity, 0) > 0
            THEN (NULLIF(pn.equity, 0) - pn.prev_equity) / pn.prev_equity * 100
        ELSE 0
    END AS day_pnl_pct,
    CASE
        WHEN b.book = 'live' THEN lp.total_unrealized_pnl
        ELSE pp.total_unrealized_pnl
    END AS open_pnl,
    CASE
        WHEN b.book = 'live' THEN COALESCE(la.buying_power, la.net_liquidation, 0)
        ELSE COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0)
    END AS buying_power,
    CASE
        WHEN b.book = 'live' THEN
            CASE WHEN la.net_liquidation > 0 THEN la.cash_value / la.net_liquidation * 100 ELSE 0 END
        ELSE
            CASE
                WHEN COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0) > 0
                THEN (COALESCE(NULLIF(pn.equity, 0), pp.gross_invested) - pp.gross_invested)
                     / COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0) * 100
                ELSE 0
            END
    END AS cash_pct,
    CASE
        WHEN b.book = 'live' THEN
            CASE WHEN la.net_liquidation > 0 THEN lp.gross_invested / la.net_liquidation * 100 ELSE 0 END
        ELSE
            CASE WHEN COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0) > 0
                 THEN pp.gross_invested / COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0) * 100
                 ELSE 0 END
    END AS gross_exp_pct,
    CASE
        WHEN b.book = 'live' THEN
            CASE WHEN la.net_liquidation > 0 THEN lp.net_invested / la.net_liquidation * 100 ELSE 0 END
        ELSE
            CASE WHEN COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0) > 0
                 THEN pp.net_invested / COALESCE(NULLIF(pn.equity, 0), pp.gross_invested, 0) * 100
                 ELSE 0 END
    END AS net_exp_pct,
    CASE WHEN b.book = 'live' THEN lp.open_positions ELSE pp.open_positions END AS positions,
    NOW()::timestamp without time zone AS updated_at
FROM books b
LEFT JOIN live_account la ON b.book = 'live'
LEFT JOIN latest_live_nav ln ON b.book = ln.book AND ln.rn = 1
LEFT JOIN latest_paper_nav pn ON b.book = pn.book AND pn.rn = 1
LEFT JOIN live_positions lp ON b.book = 'live'
LEFT JOIN paper_positions pp ON b.book = 'paper';
