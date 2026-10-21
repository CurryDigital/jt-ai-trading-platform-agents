#!/usr/bin/env python3
"""
Refresh gold.paper_trades for actively-monitored paper-trading strategies.

Lifecycle contract:
- Only strategies with gold.strategy_paper_monitoring.is_active = true are
  refreshed here. The monitoring flag is kept in sync with
  strategy_registry.execution_mode by the trigger in
  2026-07-25_v_pipeline_ui_feed_current_year_wr_paper_monitoring.sql.
- When monitoring stops, the flag flips to false, this script skips the
  strategy, and the platform Stop endpoint is expected to purge the existing
  non-rehearsal rows from gold.paper_trades.
- This script is idempotent per run: it deletes the rows it owns for each
  monitored strategy and re-derives closed/open trades from the latest
  consumption.signal_logs + silver.unified_prices.

This intentionally does NOT touch strategies managed by dynamic-scoring
rebalancers (rows in gold.strategy_ticker_scores) or strategies that are not
being monitored; those are handled by other parts of the pipeline.

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


def refresh():
    conn = get_conn()
    c = conn.cursor()

    # Idempotent: remove rows for monitored strategies before re-deriving them.
    # If the platform Stop endpoint has already purged the strategy, this is a
    # no-op and the INSERT below will insert nothing because is_active=false.
    c.execute("""
        DELETE FROM gold.paper_trades
        WHERE rehearsal = false
          AND strategy_id IN (
              SELECT strategy_id FROM gold.strategy_paper_monitoring WHERE is_active = true
          )
    """)
    deleted = c.rowcount
    print(f"Deleted {deleted} existing non-rehearsal paper-trade rows for monitored strategies")

    # Closed trades: pair consecutive signals per (strategy, ticker).
    # CASH is excluded: it is a portfolio cash-bucket placeholder, not a ticker.
    c.execute("""
    WITH monitored AS (
        SELECT strategy_id FROM gold.strategy_paper_monitoring WHERE is_active = true
    ),
    signals AS (
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
        WHERE strategy_id IN (SELECT strategy_id FROM monitored)
          AND ticker != 'CASH'
        ORDER BY strategy_id, signal_date, ticker, logged_at DESC
    ),
    strategy_capital AS (
        SELECT strategy_id, assigned_capital FROM gold.strategy_registry
        WHERE strategy_id IN (SELECT strategy_id FROM monitored)
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
    INSERT INTO gold.paper_trades
        (ts, strategy_id, instrument, direction, size, entry_price, exit_price, pnl,
         signal_value, confidence_at_entry, status, rehearsal, ticker, n_shares)
    SELECT
        COALESCE(sp.next_signal_date::timestamp, sp.entry_date::timestamp) AS ts,
        sp.strategy_id,
        sp.ticker AS instrument,
        CASE WHEN sp.signal_type = 'BUY' THEN 'long' ELSE 'short' END,
        CASE WHEN ep.entry_price > 0 AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
             THEN (sp.weight * sp.assigned_capital) / ep.entry_price ELSE NULL END AS size,
        ep.entry_price,
        xp.exit_price,
        CASE WHEN ep.entry_price IS NOT NULL AND xp.exit_price IS NOT NULL AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
             THEN (xp.exit_price - ep.entry_price) * ((sp.weight * sp.assigned_capital) / ep.entry_price)
                  * CASE WHEN sp.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END,
        sp.weight AS signal_value,
        sp.weight AS confidence_at_entry,
        'closed',
        false,
        sp.ticker,
        CASE WHEN ep.entry_price > 0 AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
             THEN ((sp.weight * sp.assigned_capital) / ep.entry_price)::integer ELSE NULL END
    FROM signal_pairs sp
    LEFT JOIN entry_prices ep ON ep.strategy_id = sp.strategy_id AND ep.ticker = sp.ticker AND ep.entry_date = sp.entry_date
    LEFT JOIN exit_prices xp ON xp.strategy_id = sp.strategy_id AND xp.ticker = sp.ticker AND xp.exit_date = sp.next_signal_date
    WHERE ep.entry_price IS NOT NULL AND xp.exit_price IS NOT NULL
    """)
    closed_inserted = c.rowcount
    print(f"Inserted {closed_inserted} closed paper trades")

    # Open trades: the latest unclosed signal per (strategy, ticker).
    # CASH is excluded: it is a portfolio cash-bucket placeholder, not a ticker.
    c.execute("""
    WITH monitored AS (
        SELECT strategy_id FROM gold.strategy_paper_monitoring WHERE is_active = true
    ),
    signals AS (
        SELECT DISTINCT ON (strategy_id, signal_date, ticker)
            strategy_id, signal_date, ticker, signal_type,
            CASE
                WHEN signal_criteria LIKE '{%}' THEN (signal_criteria::jsonb->>'weight')::numeric
                WHEN signal_criteria LIKE 'weight=%' THEN split_part(split_part(signal_criteria, ';', 1), '=', 2)::numeric
                ELSE NULL::numeric
            END AS weight
        FROM consumption.signal_logs
        WHERE strategy_id IN (SELECT strategy_id FROM monitored)
          AND ticker != 'CASH'
        ORDER BY strategy_id, signal_date, ticker, logged_at DESC
    ),
    last_signals AS (
        SELECT DISTINCT ON (strategy_id, ticker) strategy_id, ticker, signal_date AS entry_date, signal_type, weight
        FROM signals ORDER BY strategy_id, ticker, signal_date DESC
    ),
    strategy_capital AS (
        SELECT strategy_id, assigned_capital FROM gold.strategy_registry
        WHERE strategy_id IN (SELECT strategy_id FROM monitored)
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
    INSERT INTO gold.paper_trades
        (ts, strategy_id, instrument, direction, size, entry_price, exit_price, pnl,
         signal_value, confidence_at_entry, status, rehearsal, ticker, n_shares)
    SELECT
        lp.price_date::timestamp AS ts,
        ls.strategy_id,
        ls.ticker AS instrument,
        CASE WHEN ls.signal_type = 'BUY' THEN 'long' ELSE 'short' END,
        CASE WHEN ep.entry_price > 0 AND ls.weight IS NOT NULL AND sc.assigned_capital IS NOT NULL
             THEN (ls.weight * sc.assigned_capital) / ep.entry_price ELSE NULL END AS size,
        ep.entry_price,
        lp.latest_price,
        CASE WHEN ep.entry_price IS NOT NULL AND lp.latest_price IS NOT NULL AND ls.weight IS NOT NULL AND sc.assigned_capital IS NOT NULL
             THEN (lp.latest_price - ep.entry_price) * ((ls.weight * sc.assigned_capital) / ep.entry_price)
                  * CASE WHEN ls.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END,
        ls.weight AS signal_value,
        ls.weight AS confidence_at_entry,
        'open',
        false,
        ls.ticker,
        CASE WHEN ep.entry_price > 0 AND ls.weight IS NOT NULL AND sc.assigned_capital IS NOT NULL
             THEN ((ls.weight * sc.assigned_capital) / ep.entry_price)::integer ELSE NULL END
    FROM last_signals ls
    JOIN strategy_capital sc ON sc.strategy_id = ls.strategy_id
    LEFT JOIN entry_prices ep ON ep.strategy_id = ls.strategy_id AND ep.ticker = ls.ticker AND ep.entry_date = ls.entry_date
    LEFT JOIN latest_prices lp ON lp.ticker = ls.ticker
    WHERE ep.entry_price IS NOT NULL
    """)
    open_inserted = c.rowcount
    print(f"Inserted {open_inserted} open paper trades")

    conn.commit()
    c.close()
    conn.close()
    print("gold.paper_trades refreshed for monitored strategies")


if __name__ == "__main__":
    refresh()
