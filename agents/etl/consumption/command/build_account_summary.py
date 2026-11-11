#!/usr/bin/env python3
"""
Consumption: account_summary view (command-center overview)

Rebuilds consumption.account_summary so that:
  * live book uses gold.ibkr_account_summary for equity, cash and buying_power
  * live book exposure counts ONLY live rows (execution_mode != 'PAPER_TRADING')
    from consumption.portfolio_positions_current — previously it summed the
    aggregate paper book against live equity, producing the bogus 902% gross
    exposure artifact (kanban t_2b2ac824, 2026-08-18)
  * paper book has a CANONICAL aggregate row:
      equity       = SUM(gold.strategy_registry.assigned_capital) over
                     gold.strategy_paper_monitoring is_active PAPER strategies
                     (independent per-strategy pools => assigned capital is the
                     honest equity denominator)
      cash         = equity - deployed (net) market value of paper positions
      buying_power = equity - gross deployed market value (floored at 0)
      exposure     = aggregate paper positions from
                     consumption.portfolio_positions_current
                     (execution_mode = 'PAPER_TRADING')
    Falls back to gold.account_nav_daily paper equity, then gross invested,
    only when no assigned capital is registered.
  * short positions are reflected with negative market values, so gross and net
    exposure diverge correctly
  * cash_pct is observed cash / equity, not 100 - gross_exp_pct

NOTE: consumption.portfolio_positions_paper is a stale legacy table (one dead
strategy, S9_MACD_Momentum_V2) and is no longer referenced by this view.

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
    -- t_65d96f4a: the live book is served in USD. Native columns on
    -- gold.ibkr_account_summary are the account base currency (HKD); the
    -- *_usd columns are converted at ingest via the shared fx layer
    -- (gold.fx_rates). No raw cash_hkd+cash_usd sums, no unlabeled values.
    SELECT
        account,
        net_liquidation_usd AS net_liquidation,
        buying_power_usd AS buying_power,
        cash_total_usd AS cash_value
    FROM gold.ibkr_account_summary
    ORDER BY fetched_at DESC
    LIMIT 1
),
live_nav AS (
    -- USD series (equity_usd); history pre-2026-10-10 is HKD and was tagged
    -- (not rewritten), so equity_usd starts with the first converted row.
    SELECT book, as_of_date, equity_usd AS equity, pnl,
           LAG(equity_usd) OVER (PARTITION BY book ORDER BY as_of_date) AS prev_equity
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
paper_assigned AS (
    -- Canonical paper-book equity base: sum of assigned capital across all
    -- actively monitored PAPER strategies.
    SELECT COALESCE(SUM(r.assigned_capital), 0) AS assigned_capital
    FROM gold.strategy_paper_monitoring m
    JOIN gold.strategy_registry r ON r.strategy_id = m.strategy_id
    WHERE m.is_active
      AND r.execution_mode = 'PAPER'
      AND r.assigned_capital IS NOT NULL
),
live_positions AS (
    -- t_53888693 (2026-11-10): the live book exposure must come from the
    -- broker book ONLY (execution_mode='LIVE_TRADING', synced from
    -- gold.ibkr_positions_live). Previously this filter was
    -- `IS DISTINCT FROM 'PAPER_TRADING'`, which swept in MANUAL rows folded
    -- from gold.manual_orders — and 100% of that table is paper_uat
    -- reconciler fills on the same DUP825942 account. Result: the UAT mirror
    -- was double-counted against the real shorts (gross 400.7% / net +51.0%
    -- served for a book that is actually 3 shorts, gross/net ±164%).
    -- Manual orders on this account are already reflected in the broker
    -- positions, so including 'MANUAL' here would double-count even genuine
    -- manual trades. The NULL-mode legacy row (araso_factor_model) is also
    -- excluded from the live position count.
    SELECT
        COALESCE(SUM(ABS(market_value)), 0) AS gross_invested,
        COALESCE(SUM(market_value), 0) AS net_invested,
        COALESCE(SUM(unrealized_pnl), 0) AS total_unrealized_pnl,
        COUNT(*)::integer AS open_positions
    FROM consumption.portfolio_positions_current
    WHERE status IN ('OPEN', 'ACTIVE')
      AND execution_mode = 'LIVE_TRADING'
),
paper_positions AS (
    SELECT
        COALESCE(SUM(ABS(market_value)), 0) AS gross_invested,
        COALESCE(SUM(market_value), 0) AS net_invested,
        COALESCE(SUM(unrealized_pnl), 0) AS total_unrealized_pnl,
        COUNT(*)::integer AS open_positions
    FROM consumption.portfolio_positions_current
    WHERE status IN ('OPEN', 'ACTIVE')
      AND execution_mode = 'PAPER_TRADING'
),
base AS (
    SELECT
        b.book,
        CASE
            WHEN b.book = 'live' THEN COALESCE(la.net_liquidation, 0)
            ELSE COALESCE(NULLIF(pa.assigned_capital, 0), NULLIF(pn.equity, 0), pp.gross_invested, 0)
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
        CASE WHEN b.book = 'live' THEN lp.gross_invested ELSE pp.gross_invested END AS gross_invested,
        CASE WHEN b.book = 'live' THEN lp.net_invested ELSE pp.net_invested END AS net_invested,
        CASE WHEN b.book = 'live' THEN lp.open_positions ELSE pp.open_positions END AS positions,
        la.net_liquidation AS live_net_liq,
        la.buying_power AS live_buying_power,
        la.cash_value AS live_cash_value
    FROM books b
    LEFT JOIN live_account la ON b.book = 'live'
    LEFT JOIN latest_live_nav ln ON b.book = ln.book AND ln.rn = 1
    LEFT JOIN latest_paper_nav pn ON b.book = pn.book AND pn.rn = 1
    LEFT JOIN live_positions lp ON b.book = 'live'
    LEFT JOIN paper_positions pp ON b.book = 'paper'
    CROSS JOIN paper_assigned pa
)
SELECT
    book,
    equity,
    day_pnl,
    day_pnl_pct,
    open_pnl,
    CASE
        WHEN book = 'live' THEN COALESCE(live_buying_power, live_net_liq, 0)
        ELSE GREATEST(equity - gross_invested, 0)
    END AS buying_power,
    CASE
        WHEN book = 'live' THEN
            CASE WHEN live_net_liq > 0 THEN live_cash_value / live_net_liq * 100 ELSE 0 END
        ELSE
            CASE WHEN equity > 0 THEN (equity - net_invested) / equity * 100 ELSE 0 END
    END AS cash_pct,
    CASE WHEN equity > 0 THEN gross_invested / equity * 100 ELSE 0 END AS gross_exp_pct,
    CASE WHEN equity > 0 THEN net_invested / equity * 100 ELSE 0 END AS net_exp_pct,
    positions,
    NOW()::timestamp without time zone AS updated_at
FROM base;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(CREATE_VIEW_SQL)
    conn.commit()
    conn.close()
    print("✅ consumption.account_summary view refreshed (canonical paper book)")

if __name__ == "__main__":
    run()
