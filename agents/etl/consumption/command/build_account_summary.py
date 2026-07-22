#!/usr/bin/env python3
"""
Consumption: account_summary view (command-center overview)

Rebuilds consumption.account_summary so that:
  * live book uses gold.ibkr_account_summary for equity, cash and buying_power
  * paper book uses gold.account_nav_daily + consumption.portfolio_positions_paper
  * short positions are reflected with negative market values, so gross and net
    exposure diverge correctly
  * cash_pct is observed cash / equity, not 100 - gross_exp_pct

This script is idempotent; it only creates/replaces the view.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
from db import get_connection

CREATE_VIEW_SQL = """
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
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(CREATE_VIEW_SQL)
    conn.commit()
    conn.close()
    print("✅ consumption.account_summary view refreshed")

if __name__ == "__main__":
    run()
