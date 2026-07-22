#!/usr/bin/env python3
"""
Refresh gold.paper_trades_synthetic from consumption.signal_logs.

This backfills synthetic paper trades for approved pipeline strategies
that are not yet wired to the real paper execution agent. Run after the
daily signal ingestion completes.

DESIGN NOTE: Dynamic scoring strategies
Strategies that have a live scoring engine (rows in gold.strategy_ticker_scores)
are managed by rebuild_paper_positions.py. This script skips them so it does
not overwrite the position-aware rebalancer output with stale signal_logs data.

DESIGN NOTE: CASH handling
- CASH is a portfolio cash-bucket placeholder, not a tradeable ticker. It is
  excluded from ticker-level tables; 100% cash is represented implicitly by
  the absence of security positions in this table.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.hermes/profiles/qr_etl/env/etl.env"))


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS gold.paper_trades_synthetic (
    id SERIAL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    ticker TEXT,
    direction TEXT,
    entry_date DATE NOT NULL,
    exit_date DATE,
    entry_price NUMERIC,
    exit_price NUMERIC,
    n_shares NUMERIC,
    pnl NUMERIC,
    pnl_pct NUMERIC,
    status TEXT NOT NULL,
    signal_weight NUMERIC,
    assigned_capital NUMERIC,
    created_at TIMESTAMP DEFAULT NOW()
)
"""


def refresh():
    conn = get_conn()
    c = conn.cursor()

    # Idempotent setup: keep the table (and any dependent views) intact.
    # Only delete rows for the legacy strategies this script will refresh,
    # so dynamic-scoring strategies managed by rebuild_paper_positions.py
    # are never wiped out.
    c.execute(_CREATE_TABLE_SQL)
    c.execute("""
        DELETE FROM gold.paper_trades_synthetic
        WHERE strategy_id IN (
            SELECT id FROM gold.v_pipeline_ui_feed
            WHERE id NOT IN (SELECT DISTINCT strategy_id FROM gold.strategy_ticker_scores)
        )
    """)
    deleted = c.rowcount
    print(f"Deleted {deleted} legacy paper-trade rows before refresh")

    # Closed trades: pair consecutive signals per (strategy, ticker).
    # CASH is excluded: it is a portfolio cash-bucket placeholder, not a ticker.
    c.execute("""
    WITH signals AS (
        SELECT DISTINCT ON (strategy_id, signal_date, ticker)
            strategy_id,
            signal_date,
            ticker,
            signal_type,
            CASE
                WHEN signal_criteria LIKE '{%}' THEN (signal_criteria::jsonb->>'weight')::numeric
                WHEN signal_criteria LIKE 'weight=%' THEN split_part(split_part(signal_criteria, ';', 1), '=', 2)::numeric
                ELSE NULL::numeric
            END AS weight
        FROM consumption.signal_logs
        WHERE strategy_id IN (SELECT id FROM gold.v_pipeline_ui_feed)
          AND strategy_id NOT IN (SELECT DISTINCT strategy_id FROM gold.strategy_ticker_scores)
          AND ticker != 'CASH'
        ORDER BY strategy_id, signal_date, ticker, logged_at DESC
    ),
    strategy_capital AS (
        SELECT strategy_id, assigned_capital FROM gold.strategy_registry
        WHERE strategy_id IN (SELECT id FROM gold.v_pipeline_ui_feed)
          AND strategy_id NOT IN (SELECT DISTINCT strategy_id FROM gold.strategy_ticker_scores)
    ),
    signal_pairs AS (
        SELECT
            s.strategy_id,
            s.signal_date AS entry_date,
            s.ticker,
            s.signal_type,
            s.weight,
            LEAD(s.signal_date) OVER (PARTITION BY s.strategy_id, s.ticker ORDER BY s.signal_date) AS next_signal_date,
            sc.assigned_capital
        FROM signals s
        JOIN strategy_capital sc ON sc.strategy_id = s.strategy_id
    ),
    entry_prices AS (
        SELECT DISTINCT ON (sp.strategy_id, sp.ticker, sp.entry_date)
            sp.strategy_id, sp.ticker, sp.entry_date,
            p.close AS entry_price
        FROM signal_pairs sp
        LEFT JOIN silver.unified_prices p ON p.ticker = sp.ticker AND p.date <= sp.entry_date
        ORDER BY sp.strategy_id, sp.ticker, sp.entry_date, p.date DESC
    ),
    exit_prices AS (
        SELECT DISTINCT ON (sp.strategy_id, sp.ticker, sp.next_signal_date)
            sp.strategy_id, sp.ticker, sp.next_signal_date AS exit_date,
            p.close AS exit_price
        FROM signal_pairs sp
        LEFT JOIN silver.unified_prices p ON p.ticker = sp.ticker AND p.date <= sp.next_signal_date
        WHERE sp.next_signal_date IS NOT NULL
        ORDER BY sp.strategy_id, sp.ticker, sp.next_signal_date, p.date DESC
    )
    INSERT INTO gold.paper_trades_synthetic
        (strategy_id, ticker, direction, entry_date, exit_date, entry_price, exit_price, n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital)
    SELECT
        sp.strategy_id, sp.ticker,
        CASE WHEN sp.signal_type = 'BUY' THEN 'long' ELSE 'short' END,
        sp.entry_date, sp.next_signal_date, ep.entry_price, xp.exit_price,
        CASE WHEN ep.entry_price > 0 AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
             THEN (sp.weight * sp.assigned_capital) / ep.entry_price ELSE NULL END,
        CASE WHEN ep.entry_price IS NOT NULL AND xp.exit_price IS NOT NULL AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
             THEN (xp.exit_price - ep.entry_price) * ((sp.weight * sp.assigned_capital) / ep.entry_price)
                  * CASE WHEN sp.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END,
        CASE WHEN ep.entry_price > 0 AND xp.exit_price IS NOT NULL
             THEN ((xp.exit_price - ep.entry_price) / ep.entry_price) * 100
                  * CASE WHEN sp.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END,
        'closed', sp.weight, sp.assigned_capital
    FROM signal_pairs sp
    LEFT JOIN entry_prices ep ON ep.strategy_id = sp.strategy_id AND ep.ticker = sp.ticker AND ep.entry_date = sp.entry_date
    LEFT JOIN exit_prices xp ON xp.strategy_id = sp.strategy_id AND xp.ticker = sp.ticker AND xp.exit_date = sp.next_signal_date
    WHERE ep.entry_price IS NOT NULL AND xp.exit_price IS NOT NULL
    """)

    # Open trades: the latest unclosed signal per (strategy, ticker).
    # CASH is excluded: it is a portfolio cash-bucket placeholder, not a ticker.
    c.execute("""
    WITH signals AS (
        SELECT DISTINCT ON (strategy_id, signal_date, ticker)
            strategy_id, signal_date, ticker, signal_type,
            CASE
                WHEN signal_criteria LIKE '{%}' THEN (signal_criteria::jsonb->>'weight')::numeric
                WHEN signal_criteria LIKE 'weight=%' THEN split_part(split_part(signal_criteria, ';', 1), '=', 2)::numeric
                ELSE NULL::numeric
            END AS weight
        FROM consumption.signal_logs
        WHERE strategy_id IN (SELECT id FROM gold.v_pipeline_ui_feed)
          AND strategy_id NOT IN (SELECT DISTINCT strategy_id FROM gold.strategy_ticker_scores)
          AND ticker != 'CASH'
        ORDER BY strategy_id, signal_date, ticker, logged_at DESC
    ),
    last_signals AS (
        SELECT DISTINCT ON (strategy_id, ticker) strategy_id, ticker, signal_date AS entry_date, signal_type, weight
        FROM signals ORDER BY strategy_id, ticker, signal_date DESC
    ),
    strategy_capital AS (
        SELECT strategy_id, assigned_capital FROM gold.strategy_registry
        WHERE strategy_id IN (SELECT id FROM gold.v_pipeline_ui_feed)
          AND strategy_id NOT IN (SELECT DISTINCT strategy_id FROM gold.strategy_ticker_scores)
    ),
    entry_prices AS (
        SELECT DISTINCT ON (ls.strategy_id, ls.ticker, ls.entry_date)
            ls.strategy_id, ls.ticker, ls.entry_date,
            p.close AS entry_price
        FROM last_signals ls
        LEFT JOIN silver.unified_prices p ON p.ticker = ls.ticker AND p.date <= ls.entry_date
        ORDER BY ls.strategy_id, ls.ticker, ls.entry_date, p.date DESC
    ),
    latest_prices AS (
        SELECT ticker, price_date, latest_price FROM (
            SELECT DISTINCT ON (ticker) ticker, date AS price_date, close AS latest_price
            FROM silver.unified_prices WHERE close IS NOT NULL ORDER BY ticker, date DESC
        ) real_prices
    )
    INSERT INTO gold.paper_trades_synthetic
        (strategy_id, ticker, direction, entry_date, exit_date, entry_price, exit_price, n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital)
    SELECT
        ls.strategy_id, ls.ticker,
        CASE WHEN ls.signal_type = 'BUY' THEN 'long' ELSE 'short' END,
        ls.entry_date, lp.price_date, ep.entry_price, lp.latest_price,
        CASE WHEN ep.entry_price > 0 AND ls.weight IS NOT NULL AND sc.assigned_capital IS NOT NULL
             THEN (ls.weight * sc.assigned_capital) / ep.entry_price ELSE NULL END,
        CASE WHEN ep.entry_price IS NOT NULL AND lp.latest_price IS NOT NULL AND ls.weight IS NOT NULL AND sc.assigned_capital IS NOT NULL
             THEN (lp.latest_price - ep.entry_price) * ((ls.weight * sc.assigned_capital) / ep.entry_price)
                  * CASE WHEN ls.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END,
        CASE WHEN ep.entry_price > 0 AND lp.latest_price IS NOT NULL
             THEN ((lp.latest_price - ep.entry_price) / ep.entry_price) * 100
                  * CASE WHEN ls.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END,
        'open', ls.weight, sc.assigned_capital
    FROM last_signals ls
    JOIN strategy_capital sc ON sc.strategy_id = ls.strategy_id
    LEFT JOIN entry_prices ep ON ep.strategy_id = ls.strategy_id AND ep.ticker = ls.ticker AND ep.entry_date = ls.entry_date
    LEFT JOIN latest_prices lp ON lp.ticker = ls.ticker
    WHERE ep.entry_price IS NOT NULL
    """)

    conn.commit()
    c.close()
    conn.close()
    print("paper_trades_synthetic refreshed")


if __name__ == "__main__":
    refresh()
