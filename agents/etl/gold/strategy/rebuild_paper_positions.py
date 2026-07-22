#!/usr/bin/env python3
"""
Generic position-aware paper rebalancer.

Reads:
- gold.strategy_registry (active PAPER/SIMULATION strategies + universe + capital)
- gold.strategy_ticker_scores (latest BUY/HOLD signals per ticker)
- silver.unified_prices (latest close prices)

Writes:
- consumption.strategies_signals_current (latest signal, strength, confidence, price)
- gold.paper_trades_synthetic (open positions, no more than one open row per ticker per strategy)

Behaviour:
- One open position per (strategy_id, ticker).
- Sells (closes) a position when the ticker drops out of the current BUY set.
- Buys (opens) a position when a ticker enters the current BUY set and none exists.
- Does nothing for a ticker already held that is still a BUY signal.
- PnL is calculated on close using real exit price vs entry price.
- Signals are published from strategy_ticker_scores; signal_strength and confidence are derived from the score.

Modes:
- default: incremental update (preserves history, only trades deltas).
- --backfill: truncates stale data and rebuilds a clean current state.

All paths live under the Hermes ETL workspace: agents/etl/gold/strategy/.
"""
import sys, os, argparse, math
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path: sys.path.insert(0, _ETL_SHARED)

from db import get_connection


SQL_DROP_SIGNAL_CONSTRAINTS = """
SELECT conname
FROM pg_constraint
JOIN pg_class t ON t.oid = conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'consumption' AND t.relname = 'strategies_signals_current'
  AND contype = 'u'
  AND conname LIKE 'uniq_strategies_signals_current%';
"""

SQL_ADD_SIGNAL_CONSTRAINT = """
ALTER TABLE consumption.strategies_signals_current
ADD CONSTRAINT uniq_strategies_signals_current_strategy_ticker
UNIQUE (strategy_id, ticker);
"""

SQL_DROP_OPEN_POSITION_INDEX = """
SELECT indexname
FROM pg_indexes
WHERE schemaname = 'gold' AND tablename = 'paper_trades_synthetic'
  AND indexname = 'uniq_paper_trades_synthetic_open_strategy_ticker';
"""

SQL_ADD_OPEN_POSITION_INDEX = """
CREATE UNIQUE INDEX uniq_paper_trades_synthetic_open_strategy_ticker
ON gold.paper_trades_synthetic (strategy_id, ticker)
WHERE status = 'open';
"""

SQL_FETCH_ACTIVE_STRATEGIES = """
SELECT
  strategy_id,
  name,
  execution_mode,
  assigned_capital,
  universe_tickers
FROM gold.strategy_registry
WHERE retired_at IS NULL
  AND execution_mode IN ('PAPER', 'SIMULATION')
  AND universe_tickers IS NOT NULL
  AND array_length(universe_tickers, 1) > 0
ORDER BY strategy_id;
"""

SQL_FETCH_LATEST_SCORES = """
SELECT strategy_id, ticker, score, signal_action
FROM gold.strategy_ticker_scores
WHERE strategy_id = ANY(%s);
"""

SQL_FETCH_LATEST_PRICES = """
SELECT DISTINCT ON (ticker)
  ticker,
  close AS price
FROM silver.unified_prices
WHERE ticker = ANY(%s)
ORDER BY ticker, date DESC;
"""

SQL_FETCH_OPEN_POSITIONS = """
SELECT id, strategy_id, ticker, direction, entry_date, entry_price, n_shares, status
FROM gold.paper_trades_synthetic
WHERE strategy_id = ANY(%s)
  AND status = 'open';
"""

SQL_TRUNCATE_STALE = """
TRUNCATE TABLE gold.paper_trades_synthetic, consumption.strategies_signals_current;
"""

SQL_CLOSE_POSITIONS = """
UPDATE gold.paper_trades_synthetic
SET status = 'closed',
    exit_date = %s,
    exit_price = %s,
    pnl = (%s - entry_price) * n_shares,
    pnl_pct = CASE WHEN entry_price = 0 OR entry_price IS NULL THEN 0
                   ELSE ((%s - entry_price) / entry_price) * 100 END,
    updated_at = NOW()
WHERE id = ANY(%s)
  AND status = 'open';
"""

SQL_OPEN_POSITIONS = """
INSERT INTO gold.paper_trades_synthetic
  (strategy_id, ticker, direction, entry_date, entry_price, n_shares, status,
   signal_weight, assigned_capital, pnl, pnl_pct, created_at, updated_at)
VALUES %s;
"""

SQL_UPSERT_SIGNALS = """
INSERT INTO consumption.strategies_signals_current
  (strategy_id, ticker, signal, signal_strength, confidence_score, current_price, updated_at)
VALUES %s
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
  signal = EXCLUDED.signal,
  signal_strength = EXCLUDED.signal_strength,
  confidence_score = EXCLUDED.confidence_score,
  current_price = EXCLUDED.current_price,
  updated_at = EXCLUDED.updated_at;
"""


def ensure_constraints(cur):
    """Add idempotency constraints if not already present."""
    cur.execute(SQL_DROP_SIGNAL_CONSTRAINTS)
    exists = cur.fetchone()
    if not exists:
        cur.execute(SQL_ADD_SIGNAL_CONSTRAINT)
        print("  Added unique constraint on consumption.strategies_signals_current(strategy_id, ticker)")

    cur.execute(SQL_DROP_OPEN_POSITION_INDEX)
    exists = cur.fetchone()
    if not exists:
        cur.execute(SQL_ADD_OPEN_POSITION_INDEX)
        print("  Added partial unique index on gold.paper_trades_synthetic open positions")


def fetch_active_strategies(cur, strategy_id=None):
    params = ()
    strategy_filter = ""
    if strategy_id:
        strategy_filter = "AND strategy_id = %s"
        params = (strategy_id,)
    cur.execute(f"""
        SELECT
          strategy_id,
          name,
          execution_mode,
          assigned_capital,
          universe_tickers
        FROM gold.strategy_registry
        WHERE retired_at IS NULL
          AND execution_mode IN ('PAPER', 'SIMULATION')
          AND universe_tickers IS NOT NULL
          AND array_length(universe_tickers, 1) > 0
          {strategy_filter}
        ORDER BY strategy_id;
    """, params)
    rows = cur.fetchall()
    return [
        {
            'strategy_id': r[0],
            'name': r[1],
            'mode': r[2],
            'capital': r[3] or 0,
            'universe': r[4] or [],
        }
        for r in rows
    ]


def fetch_prices(cur, tickers):
    if not tickers:
        return {}
    cur.execute(SQL_FETCH_LATEST_PRICES, (tickers,))
    return {r[0]: r[1] for r in cur.fetchall()}


def fetch_scores(cur, strategy_ids):
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_LATEST_SCORES, (strategy_ids,))
    rows = cur.fetchall()
    # grouped by strategy_id
    scores = {}
    for r in rows:
        sid = r[0]
        scores.setdefault(sid, []).append({
            'ticker': r[1],
            'score': r[2] or 0,
            'action': r[3],
        })
    return scores


def fetch_open_positions(cur, strategy_ids):
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_OPEN_POSITIONS, (strategy_ids,))
    rows = cur.fetchall()
    positions = {}
    for r in rows:
        sid = r[1]
        positions.setdefault(sid, {})[r[2]] = {
            'id': r[0],
            'direction': r[3],
            'entry_date': r[4],
            'entry_price': r[5] or 0,
            'n_shares': r[6] or 0,
            'status': r[7],
        }
    return positions


def compute_target(signals, capital, prices):
    """Return list of {ticker, price, weight, shares} for BUY tickers to hold.

    Only BUY signals are traded. A CASH signal (HOLD action) is counted in
    the total score so that the residual cash target is reflected in the
    weights of the BUY names.
    """
    if not signals:
        return []
    buy_signals = [s for s in signals if s['action'] == 'BUY']
    cash_signal = next((s for s in signals if s['ticker'] == 'CASH'), None)
    total_score = sum(max(0, float(s['score'])) for s in buy_signals)
    if cash_signal:
        total_score += max(0, float(cash_signal['score']))
    if total_score <= 0:
        return []
    targets = []
    cap = float(capital)
    for s in buy_signals:
        ticker = s['ticker']
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        price_f = float(price)
        score = max(0, float(s['score']))
        weight = score / total_score
        target_notional = cap * weight
        shares = math.floor(target_notional / price_f)
        if shares > 0:
            targets.append({
                'ticker': ticker,
                'price': price,
                'weight': weight,
                'shares': shares,
                'score': score,
            })
    return targets


def close_positions(cur, today, close_ids, close_price):
    if not close_ids:
        return 0
    cur.execute(SQL_CLOSE_POSITIONS, (
        today, close_price, close_price, close_price, close_ids
    ))
    return cur.rowcount


def open_new_positions(cur, today, open_values):
    if not open_values:
        return 0
    from psycopg2.extras import execute_values
    execute_values(
        cur, SQL_OPEN_POSITIONS,
        open_values,
        template="(%s, %s, 'LONG', %s, %s, %s, 'open', %s, %s, 0, 0, NOW(), NOW())"
    )
    return cur.rowcount


def upsert_signals(cur, signal_values):
    if not signal_values:
        return 0
    from psycopg2.extras import execute_values
    execute_values(
        cur, SQL_UPSERT_SIGNALS,
        signal_values,
        template="(%s, %s, %s, %s, %s, %s, NOW())"
    )
    return cur.rowcount


def rebalance_strategy(cur, today, strategy, prices, signals, open_positions, backfill=False):
    sid = strategy['strategy_id']
    capital = strategy['capital'] or 0
    current_signals = signals.get(sid, [])

    # Map all tickers in universe to current signal state (BUY or HOLD)
    # For signals table, publish every ticker in universe so UI sees HOLD too.
    universe = strategy['universe']
    score_map = {s['ticker']: s['score'] for s in current_signals}
    action_map = {s['ticker']: s['action'] for s in current_signals}

    # Target positions for BUY tickers only
    # Determine target allocations from the full scoring engine output
    # (including CASH/HOLD), then open only the BUY tickers.
    targets = compute_target(current_signals, capital, prices)
    buy_signals = [s for s in current_signals if s['action'] == 'BUY']
    target_tickers = {t['ticker'] for t in targets}

    open_by_ticker = open_positions.get(sid, {})
    open_tickers = set(open_by_ticker.keys())

    if backfill:
        # Close ALL existing positions, then open the target ones fresh
        to_close = open_tickers
        close_ids = [pos['id'] for pos in open_by_ticker.values()]
        # Use current price per ticker
        close_id_prices = {pos['id']: prices.get(ticker, pos['entry_price']) for ticker, pos in open_by_ticker.items()}
    else:
        # Close positions no longer in target
        to_close = open_tickers - target_tickers
        close_ids = [open_by_ticker[t]['id'] for t in to_close]
        close_id_prices = {open_by_ticker[t]['id']: prices.get(t, open_by_ticker[t]['entry_price']) for t in to_close}

    # Skip closing positions that were opened today. Same-day round-trips
    # produce $0 PnL and corrupt the strategy detail trade log when the
    # rebalancer is accidentally run twice (or out of order) on the same day.
    to_close = {t for t in to_close if open_by_ticker[t]['entry_date'] != today}
    close_ids = [open_by_ticker[t]['id'] for t in to_close]
    close_id_prices = {open_by_ticker[t]['id']: prices.get(t, open_by_ticker[t]['entry_price']) for t in to_close}

    close_count = 0
    for cid, cprice in close_id_prices.items():
        close_count += close_positions(cur, today, [cid], cprice)

    # Open positions for targets not currently held
    held_tickers = open_tickers - to_close
    to_open = [t for t in targets if t['ticker'] not in held_tickers]

    open_values = []
    for t in to_open:
        open_values.append((
            sid, t['ticker'], today, t['price'], t['shares'],
            round(t['weight'] * 100, 4), capital
        ))

    open_count = open_new_positions(cur, today, open_values)

    # Publish signals for every universe ticker (BUY or HOLD)
    signal_values = []
    for ticker in universe:
        action = action_map.get(ticker, 'HOLD')
        score = score_map.get(ticker, 0)
        price = prices.get(ticker)
        signal_values.append((
            sid, ticker, action,
            round(float(score) / 100.0, 4),  # signal_strength
            round(float(score) / 100.0, 4),  # confidence_score
            price
        ))

    # Publish CASH explicitly if present in the scoring engine (not in universe).
    if 'CASH' in score_map:
        signal_values.append((
            sid, 'CASH', action_map.get('CASH', 'HOLD'),
            round(float(score_map['CASH']) / 100.0, 4),
            round(float(score_map['CASH']) / 100.0, 4),
            None
        ))

    upsert_signals(cur, signal_values)

    return {
        'strategy_id': sid,
        'closed': close_count,
        'opened': open_count,
        'signals_published': len(signal_values),
    }


def run(backfill=False, strategy_id=None, date_str=None):
    today = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now(timezone.utc).date()
    conn = get_connection()
    cur = None
    try:
        conn.autocommit = False
        cur = conn.cursor()

        ensure_constraints(cur)

        if backfill:
            if strategy_id:
                print(f"Backfill mode: clearing rows for {strategy_id}")
                cur.execute("DELETE FROM gold.paper_trades_synthetic WHERE strategy_id = %s", (strategy_id,))
                cur.execute("DELETE FROM consumption.strategies_signals_current WHERE strategy_id = %s", (strategy_id,))
            else:
                print("Backfill mode: clearing stale paper_trades_synthetic and strategies_signals_current")
                cur.execute(SQL_TRUNCATE_STALE)

        strategies = fetch_active_strategies(cur)
        if strategy_id:
            strategies = [s for s in strategies if s['strategy_id'] == strategy_id]
            if not strategies:
                print(f"Strategy {strategy_id} not found in active PAPER/SIMULATION strategies. Nothing to do.")
                conn.commit()
                return

        strategy_ids = [s['strategy_id'] for s in strategies]

        if not strategies:
            print("No active PAPER/SIMULATION strategies with universe. Nothing to do.")
            conn.commit()
            return

        all_tickers = list({t for s in strategies for t in s['universe']})
        prices = fetch_prices(cur, all_tickers)
        signals = fetch_scores(cur, strategy_ids)
        open_positions = fetch_open_positions(cur, strategy_ids)

        results = []
        for strategy in strategies:
            res = rebalance_strategy(cur, today, strategy, prices, signals, open_positions, backfill=backfill)
            results.append(res)

        conn.commit()

        print("Rebalancer results:")
        for r in results:
            print(f"  {r['strategy_id']}: closed={r['closed']} opened={r['opened']} signals={r['signals_published']}")
        print(f"Total active strategies rebalanced: {len(results)}")

    except Exception as e:
        conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generic paper position rebalancer")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Truncate stale paper/signal tables and rebuild current state from scratch"
    )
    parser.add_argument(
        "--strategy-id",
        type=str,
        default=None,
        help="Only rebalance this strategy_id (default: all active PAPER/SIMULATION strategies)"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Use this date (YYYY-MM-DD) as the rebalance date instead of today"
    )
    args = parser.parse_args()
    run(backfill=args.backfill, strategy_id=args.strategy_id, date_str=args.date)
