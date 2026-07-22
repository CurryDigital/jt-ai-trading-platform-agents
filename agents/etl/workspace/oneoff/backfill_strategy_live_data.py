#!/usr/bin/env python3
"""Backfill live trade executions, signals, and monthly returns for PAPER strategies.

Reads from:
- gold.strategy_registry (PAPER strategies)
- gold.paper_trades_synthetic (existing synthetic trades)
- consumption.signal_logs (for strategies missing synthetic trades)
- Live signal files at ~/.hermes/profiles/qr_research/home/signal/ (for HK strategies with no signal logs)
- silver.unified_prices (for current prices)

Writes to:
- gold.trade_executions (idempotent: deletes existing PAPER strategy rows first)
- consumption.Performance_Monthly_Returns (view created/replaced)
- consumption.Strategies_Signals_Current (refreshed for PAPER strategies)
"""
import glob
import json
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

SIGNAL_BASE_DIR = Path('/home/ubuntu/.hermes/profiles/qr_research/workspace')
CLOSE_TIME = time(16, 0, 0)


def parse_signal_file(path: Path):
    """Parse a live signal JSON file. Returns (generated_at, signals dict)."""
    data = json.loads(path.read_text())
    generated_at = datetime.fromisoformat(data['generated_at'].replace('Z', '+00:00'))
    # Signals are nested under a display-name key: {"signals": {"Display Name": {"TICKER": weight}}}
    signals = {}
    for display_name, ticker_map in data.get('signals', {}).items():
        if isinstance(ticker_map, dict):
            signals.update(ticker_map)
    return generated_at, signals


def ensure_synthetic_for_missing(cur, strategy_ids):
    """For strategies without paper_trades_synthetic rows, generate synthetic trades from signal_logs.

    Canonical CASH handling: CASH is a portfolio cash-bucket placeholder, not a
    tradeable ticker. It is excluded from ticker-level tables; 100% cash is
    represented implicitly by the absence of security positions.
    """
    # Find strategies missing from synthetic
    cur.execute("""
        SELECT s.strategy_id
        FROM gold.strategy_registry s
        WHERE s.strategy_id = ANY(%s)
          AND s.execution_mode = 'PAPER'
          AND s.status = 'paper'
          AND NOT EXISTS (
              SELECT 1 FROM gold.paper_trades_synthetic pts
              WHERE pts.strategy_id = s.strategy_id
          )
    """, (strategy_ids,))
    missing = [r[0] for r in cur.fetchall()]
    if not missing:
        return []

    print(f"Generating synthetic trades for missing strategies: {missing}")

    # Build signal pairs from signal_logs with next signal date per ticker.
    # CASH is filtered out: it is not a tradeable ticker.
    cur.execute("""
        WITH signals AS (
            SELECT DISTINCT ON (strategy_id, signal_date, ticker)
                strategy_id, signal_date, ticker, signal_type,
                CASE
                    WHEN signal_criteria LIKE '%%{%%' THEN (signal_criteria::jsonb->>'weight')::numeric
                    WHEN signal_criteria LIKE 'weight=%%' THEN split_part(split_part(signal_criteria, ';', 1), '=', 2)::numeric
                    ELSE NULL::numeric
                END AS weight
            FROM consumption.signal_logs
            WHERE strategy_id = ANY(%s)
              AND ticker != 'CASH'
            ORDER BY strategy_id, signal_date, ticker, logged_at DESC
        ),
        strategy_capital AS (
            SELECT strategy_id, assigned_capital FROM gold.strategy_registry
            WHERE strategy_id = ANY(%s)
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
                sp.strategy_id, sp.ticker, sp.entry_date, p.close AS entry_price
            FROM signal_pairs sp
            JOIN silver.unified_prices p ON p.ticker = sp.ticker AND p.date <= sp.entry_date
            ORDER BY sp.strategy_id, sp.ticker, sp.entry_date, p.date DESC
        ),
        exit_prices AS (
            SELECT DISTINCT ON (sp.strategy_id, sp.ticker, sp.next_signal_date)
                sp.strategy_id, sp.ticker, sp.next_signal_date AS exit_date, p.close AS exit_price
            FROM signal_pairs sp
            JOIN silver.unified_prices p ON p.ticker = sp.ticker AND p.date <= sp.next_signal_date
            WHERE sp.next_signal_date IS NOT NULL
            ORDER BY sp.strategy_id, sp.ticker, sp.next_signal_date, p.date DESC
        )
        SELECT
            sp.strategy_id,
            sp.ticker,
            CASE WHEN sp.signal_type = 'BUY' THEN 'long' ELSE 'short' END AS direction,
            sp.entry_date,
            sp.next_signal_date AS exit_date,
            ep.entry_price,
            xp.exit_price,
            CASE WHEN ep.entry_price > 0 AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
                 THEN (sp.weight * sp.assigned_capital) / ep.entry_price ELSE NULL END AS n_shares,
            CASE WHEN ep.entry_price IS NOT NULL AND xp.exit_price IS NOT NULL AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
                 THEN (xp.exit_price - ep.entry_price) * ((sp.weight * sp.assigned_capital) / ep.entry_price)
                      * CASE WHEN sp.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END AS pnl,
            CASE WHEN ep.entry_price > 0 AND xp.exit_price IS NOT NULL
                 THEN ((xp.exit_price - ep.entry_price) / ep.entry_price) * 100
                      * CASE WHEN sp.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END AS pnl_pct,
            'closed' AS status,
            sp.weight AS signal_weight,
            sp.assigned_capital
        FROM signal_pairs sp
        LEFT JOIN entry_prices ep ON ep.strategy_id = sp.strategy_id AND ep.ticker = sp.ticker AND ep.entry_date = sp.entry_date
        LEFT JOIN exit_prices xp ON xp.strategy_id = sp.strategy_id AND xp.ticker = sp.ticker AND xp.exit_date = sp.next_signal_date
        WHERE ep.entry_price IS NOT NULL AND xp.exit_price IS NOT NULL
    """, (missing, missing))
    return cur.fetchall()


def backfill_trade_executions(cur):
    """Idempotent backfill of gold.trade_executions from synthetic sources."""
    # Get all real PAPER strategies
    cur.execute("""
        SELECT strategy_id, assigned_capital
        FROM gold.strategy_registry
        WHERE execution_mode = 'PAPER' AND status = 'paper'
    """)
    paper_strategies = {r[0]: r[1] for r in cur.fetchall()}
    if not paper_strategies:
        print("No PAPER strategies found.")
        return 0

    print(f"Found {len(paper_strategies)} PAPER strategies: {list(paper_strategies.keys())}")

    # Delete existing trade executions for these strategies (idempotent)
    cur.execute("""
        DELETE FROM gold.trade_executions
        WHERE strategy_id = ANY(%s)
    """, (list(paper_strategies.keys()),))
    print(f"Deleted {cur.rowcount} existing trade_executions rows for PAPER strategies")

    # Load existing synthetic trades
    cur.execute("""
        SELECT strategy_id, ticker, direction, entry_date, exit_date, entry_price,
               exit_price, n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital
        FROM gold.paper_trades_synthetic
        WHERE strategy_id = ANY(%s)
    """, (list(paper_strategies.keys()),))
    synthetic_rows = cur.fetchall()
    print(f"Loaded {len(synthetic_rows)} existing synthetic trades")

    # Generate missing synthetic trades
    missing_rows = ensure_synthetic_for_missing(cur, list(paper_strategies.keys()))
    print(f"Generated {len(missing_rows)} synthetic trades from signal_logs")

    all_rows = list(synthetic_rows) + list(missing_rows)

    inserted = 0
    for row in all_rows:
        (strategy_id, ticker, direction, entry_date, exit_date, entry_price,
         exit_price, n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital) = row

        if ticker == 'CASH':
            # CASH is a cash-bucket placeholder, not a tradeable ticker.
            continue
        if not exit_date or pnl is None:
            # Skip open/missing trades; keep only closed trades with PnL
            continue

        side = 'SELL' if direction == 'long' else 'BUY' if direction == 'short' else 'SELL'
        qty = int(round(n_shares)) if n_shares is not None else None
        executed_at = datetime.combine(exit_date, CLOSE_TIME)

        cur.execute("""
            INSERT INTO gold.trade_executions
                (strategy_id, ticker, execution_mode, order_type, side, quantity, price,
                 status, executed_at, entry_price, exit_price, pnl, pnl_pct)
            VALUES (%s, %s, 'PAPER_TRADING', 'MARKET', %s, %s, %s,
                    'CLOSED', %s, %s, %s, %s, %s)
        """, (strategy_id, ticker, side, qty, exit_price,
              executed_at, entry_price, exit_price, pnl, pnl_pct))
        inserted += 1

    # Handle strategies with no signal_logs at all (HK weekly) using live signal files as open entry trades
    cur.execute("""
        SELECT s.strategy_id, s.assigned_capital
        FROM gold.strategy_registry s
        WHERE s.execution_mode = 'PAPER' AND s.status = 'paper'
          AND NOT EXISTS (SELECT 1 FROM gold.trade_executions t WHERE t.strategy_id = s.strategy_id)
    """)
    still_missing = {r[0]: r[1] for r in cur.fetchall()}
    if still_missing:
        print(f"Strategies still without trades after synthetic backfill: {list(still_missing.keys())}")
        for sid, assigned_capital in still_missing.items():
            signal_path = SIGNAL_BASE_DIR / f"{sid}_live_signals.json"
            if not signal_path.exists():
                print(f"  No signal file for {sid}, skipping")
                continue
            try:
                generated_at, signals = parse_signal_file(signal_path)
            except Exception as e:
                print(f"  Failed to parse {signal_path}: {e}")
                continue
            for ticker, weight in signals.items():
                if ticker == 'CASH':
                    # CASH is a portfolio cash-bucket placeholder, not a tradeable ticker.
                    continue
                cur.execute("SELECT close FROM silver.unified_prices WHERE ticker = %s AND close IS NOT NULL ORDER BY date DESC LIMIT 1", (ticker,))
                price_row = cur.fetchone()
                if not price_row or price_row[0] is None:
                    print(f"  No price for {ticker}, skipping")
                    continue
                price = float(price_row[0])
                w = float(weight)
                side = 'BUY' if w > 0 else 'SELL' if w < 0 else 'HOLD'
                if side == 'HOLD':
                    continue
                qty = int(round((abs(w) * float(assigned_capital or 0)) / price)) if assigned_capital and price > 0 else 0
                # Insert as open entry trade (pnl NULL) so it shows in recent_trades without distorting live metrics
                cur.execute("""
                    INSERT INTO gold.trade_executions
                        (strategy_id, ticker, execution_mode, order_type, side, quantity, price,
                         status, executed_at, entry_price, exit_price, pnl, pnl_pct)
                    VALUES (%s, %s, 'PAPER_TRADING', 'MARKET', %s, %s, %s,
                            'EXECUTED', %s, %s, NULL, NULL, NULL)
                """, (sid, ticker, side, qty, price, generated_at.replace(tzinfo=None), price))
                inserted += 1
                print(f"  Inserted open entry for {sid} {ticker} {side} qty={qty} @ {price}")

    print(f"Inserted {inserted} trade_executions rows")
    return inserted


def create_monthly_returns_view(cur):
    """Create or replace monthly returns view from trade_executions."""
    # Existing table has portfolio_type instead of strategy_id; drop and create a proper view.
    cur.execute("""
        DROP VIEW IF EXISTS consumption."Performance_Monthly_Returns" CASCADE;
        DROP VIEW IF EXISTS consumption.performance_monthly_returns CASCADE;
        CREATE OR REPLACE VIEW consumption.performance_monthly_returns AS
        SELECT
            te.strategy_id,
            'PAPER'::text AS portfolio_type,
            EXTRACT(YEAR FROM te.executed_at)::int AS year,
            EXTRACT(MONTH FROM te.executed_at)::int AS month,
            COALESCE(SUM(te.pnl), 0) AS total_pnl,
            CASE
                WHEN MAX(r.assigned_capital) IS NOT NULL AND MAX(r.assigned_capital) > 0
                THEN (COALESCE(SUM(te.pnl), 0) / MAX(r.assigned_capital)) * 100
                ELSE NULL
            END AS return_pct
        FROM gold.trade_executions te
        LEFT JOIN gold.strategy_registry r ON r.strategy_id = te.strategy_id
        WHERE te.pnl IS NOT NULL
        GROUP BY te.strategy_id, EXTRACT(YEAR FROM te.executed_at), EXTRACT(MONTH FROM te.executed_at)
    """)
    print("Created/replaced consumption.performance_monthly_returns view")


def refresh_signals_current(cur):
    """Refresh consumption.Strategies_Signals_Current from live signal files for PAPER strategies."""
    cur.execute("""
        SELECT strategy_id FROM gold.strategy_registry
        WHERE execution_mode = 'PAPER' AND status = 'paper'
    """)
    paper_strategies = [r[0] for r in cur.fetchall()]

    # Delete stale rows for PAPER strategies and old template rows (keep non-paper if any)
    cur.execute("""
        DELETE FROM consumption.strategies_signals_current
        WHERE strategy_id = ANY(%s)
    """, (paper_strategies,))
    print(f"Deleted {cur.rowcount} old signal rows for PAPER strategies")

    inserted = 0
    for sid in paper_strategies:
        signal_path = SIGNAL_BASE_DIR / f"{sid}_live_signals.json"
        if not signal_path.exists():
            print(f"No signal file for {sid}")
            continue
        try:
            generated_at, signals = parse_signal_file(signal_path)
        except Exception as e:
            print(f"Failed to parse {signal_path}: {e}")
            continue

        for ticker, weight in signals.items():
            if ticker == 'CASH':
                # CASH is a portfolio cash-bucket placeholder, not a tradeable ticker.
                continue
            w = float(weight)
            if abs(w) < 1e-9:
                signal = 'HOLD'
            elif w > 0:
                signal = 'BUY'
            else:
                signal = 'SELL'
            # Look up latest price
            cur.execute("""
                SELECT close FROM silver.unified_prices
                WHERE ticker = %s AND close IS NOT NULL ORDER BY date DESC LIMIT 1
            """, (ticker,))
            price_row = cur.fetchone()
            current_price = float(price_row[0]) if price_row and price_row[0] is not None else None

            cur.execute("""
                INSERT INTO consumption.strategies_signals_current
                    (strategy_id, ticker, signal, signal_strength, confidence_score, current_price, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (sid, ticker, signal, abs(w), 0.95, current_price, generated_at.replace(tzinfo=None)))
            inserted += 1

    print(f"Inserted {inserted} rows into consumption.strategies_signals_current")
    return inserted


def main():
    conn = get_connection()
    cur = conn.cursor()
    try:
        n_trades = backfill_trade_executions(cur)
        create_monthly_returns_view(cur)
        n_signals = refresh_signals_current(cur)
        conn.commit()
        print(f"\nBackfill complete: {n_trades} trades, {n_signals} signals")
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
