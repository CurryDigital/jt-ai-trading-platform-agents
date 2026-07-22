#!/usr/bin/env python3
"""
Backfill gold.paper_trades_synthetic for a single strategy from
gold.strategy_ticker_scores_history.

For each ticker, determine the first BUY date as entry and the first
subsequent HOLD date as exit.  Uses silver.unified_prices for entry/exit
prices and recomputes shares from the entry-date score weight.  This is
intended to repair a corrupt table where the same-day rebalancer opened and
closed positions on the same date, producing $0 PnL trades.
"""
import sys, os, math
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path: sys.path.insert(0, _ETL_SHARED)

from db import get_connection


def latest_price(cur, ticker, on_or_before):
    """Return the latest close price <= on_or_before for ticker."""
    cur.execute("""
        SELECT close FROM silver.unified_prices
        WHERE ticker = %s AND date <= %s
        ORDER BY date DESC LIMIT 1
    """, (ticker, on_or_before))
    row = cur.fetchone()
    return float(row[0]) if row else None


def backfill_strategy(conn, strategy_id):
    cur = conn.cursor()

    cur.execute("""
        SELECT assigned_capital, universe_tickers
        FROM gold.strategy_registry
        WHERE strategy_id = %s
    """, (strategy_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError(f"Strategy {strategy_id} not found in registry")
    capital = float(row[0] or 0)
    universe = row[1] or []

    # Signal history for this strategy, sorted by ticker then date
    cur.execute("""
        SELECT ticker, snapshot_date, signal_action, score
        FROM gold.strategy_ticker_scores_history
        WHERE strategy_id = %s
        ORDER BY ticker, snapshot_date
    """, (strategy_id,))
    hist_rows = cur.fetchall()

    # Group by ticker and find entry/exit dates
    by_ticker = {}
    for ticker, snap_date, action, score in hist_rows:
        by_ticker.setdefault(ticker, []).append((snap_date, action, score))

    # Build signal-run ranges per ticker
    trades = []  # (ticker, entry_date, exit_date, entry_price, exit_price, shares, weight, status)
    for ticker in universe:
        if ticker not in by_ticker:
            continue
        buys = [(d, s) for d, a, s in by_ticker[ticker] if a == 'BUY']
        if not buys:
            continue
        entry_date = buys[0][0]
        entry_score = buys[0][1]
        # Determine if the latest signal is HOLD or BUY
        latest_action = by_ticker[ticker][-1][1]
        if latest_action == 'HOLD':
            # first date after the last BUY that is HOLD
            holds = [(d, a) for d, a, _ in by_ticker[ticker] if a == 'HOLD']
            exit_date = min(d for d, _ in holds)
            status = 'closed'
        else:
            exit_date = None
            status = 'open'

        entry_price = latest_price(cur, ticker, entry_date)
        exit_price = latest_price(cur, ticker, exit_date) if exit_date else latest_price(cur, ticker, datetime.now(timezone.utc).date())
        if entry_price is None:
            print(f"  ⚠️ {ticker}: no price for entry {entry_date}; skipping")
            continue
        if exit_price is None:
            exit_price = entry_price

        # Weight proportional to entry score among BUY tickers on that date
        same_day_buys = [(d, s) for d, a, s in by_ticker[ticker] if a == 'BUY' and d == entry_date]
        # Actually need sum of BUY scores across the whole universe on entry_date
        total_buy_score = 0
        for t, rows in by_ticker.items():
            for d, a, s in rows:
                if d == entry_date and a == 'BUY':
                    total_buy_score += max(0, float(s or 0))
        score_val = max(0, float(entry_score or 0))
        weight = score_val / total_buy_score if total_buy_score > 0 else 0
        notional = capital * weight
        shares = math.floor(notional / entry_price) if entry_price > 0 else 0
        if shares <= 0:
            print(f"  ⚠️ {ticker}: computed 0 shares; skipping")
            continue
        trades.append({
            'ticker': ticker,
            'entry_date': entry_date,
            'exit_date': exit_date,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'shares': shares,
            'weight': round(weight * 100, 4),
            'status': status,
        })

    # Delete existing rows for this strategy, then insert rebuilt trades
    cur.execute("DELETE FROM gold.paper_trades_synthetic WHERE strategy_id = %s", (strategy_id,))
    print(f"  Deleted existing rows for {strategy_id}")

    from psycopg2.extras import execute_values
    values = []
    for t in trades:
        pnl = 0.0
        pnl_pct = 0.0
        if t['status'] == 'closed':
            pnl = (t['exit_price'] - t['entry_price']) * t['shares']
            pnl_pct = ((t['exit_price'] - t['entry_price']) / t['entry_price']) * 100 if t['entry_price'] else 0
        values.append((
            strategy_id, t['ticker'], 'LONG', t['entry_date'], t['entry_price'], t['exit_date'], t['exit_price'], t['shares'],
            t['status'], t['weight'], capital, pnl, pnl_pct
        ))

    if values:
        execute_values(cur, """
            INSERT INTO gold.paper_trades_synthetic
              (strategy_id, ticker, direction, entry_date, entry_price, exit_date, exit_price, n_shares, status,
               signal_weight, assigned_capital, pnl, pnl_pct, created_at, updated_at)
            VALUES %s
        """, values, template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())")

    conn.commit()
    cur.close()
    print(f"  Backfilled {len(values)} trades for {strategy_id}")
    for t in trades:
        print(f"    {t['ticker']}: {t['status']} entry={t['entry_date']}@{t['entry_price']} "
              f"exit={t['exit_date']}@{t['exit_price']} shares={t['shares']} "
              f"pnl={round((t['exit_price']-t['entry_price'])*t['shares'], 2) if t['status']=='closed' else 0}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 backfill_paper_trades_from_history.py <strategy_id>")
        sys.exit(1)
    strategy_id = sys.argv[1]
    conn = get_connection()
    try:
        backfill_strategy(conn, strategy_id)
    finally:
        conn.close()
