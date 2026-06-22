# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
S9_MACD_Momentum_V2 — Daily Signal Generation
===============================================
1. Reads gold.regime_label for today
2. If regime = TREND, runs MACD signal on the 35-ticker universe
3. Entry: macd_hist >= 0.1 AND prev_macd_hist <= -0.2 AND volume_ratio >= 1.2
4. Upserts new signals to gold.s9_macd_signals
5. Upserts paper trades to gold.s9_paper_trades
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

STRATEGY_ID = 'S9_MACD_Momentum_V2'
UNIVERSE = [
    'AAPL', 'ABBV', 'ACN', 'ADBE', 'AMAT', 'AMD', 'AMZN', 'BA', 'COST',
    'CRM', 'DHR', 'DOCU', 'GOOGL', 'HD', 'INTU', 'LIN', 'LLY', 'MA',
    'META', 'MSFT', 'NFLX', 'NKE', 'NVDA', 'PYPL', 'QCOM', 'ROKU',
    'SHOP', 'SNOW', 'TMO', 'TMUS', 'TSLA', 'TXN', 'UNH', 'V', 'ZM'
]

# Entry/exit parameters
ENTRY_HIST_THRESH = 0.1
PREV_HIST_THRESH = -0.2
VOLUME_RATIO_MIN = 1.2
TP_PCT = 0.03
SL_PCT = -0.02
MAX_HOLD_DAYS = 5


def get_today_regime(conn):
    cur = conn.cursor()
    cur.execute("SELECT regime FROM gold.regime_label WHERE date = (SELECT MAX(date) FROM gold.regime_label)")
    row = cur.fetchone()
    cur.close()
    return row[0] if row else 'UNKNOWN'


def has_open_trade(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM gold.s9_paper_trades
        WHERE strategy_id = %s AND status = 'OPEN'
    """, (STRATEGY_ID,))
    count = cur.fetchone()[0]
    cur.close()
    return count > 0


def find_signals(conn):
    """Find tickers meeting MACD histogram entry criteria today."""
    cur = conn.cursor()
    tickers_str = ','.join(f"'{t}'" for t in UNIVERSE)
    cur.execute(f"""
        WITH macd_calc AS (
            SELECT
                ticker,
                date,
                close,
                volume,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS ema_12,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 25 PRECEDING AND CURRENT ROW) AS ema_26,
                AVG(volume) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS vol_sma_20,
                LAG(close, 1) OVER (PARTITION BY ticker ORDER BY date) AS prev_close
            FROM silver.unified_prices
            WHERE ticker IN ({tickers_str})
        ),
        macd_hist AS (
            SELECT
                ticker, date, close, volume, prev_close, vol_sma_20,
                ema_12 - ema_26 AS macd_line,
                AVG(ema_12 - ema_26) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 8 PRECEDING AND CURRENT ROW) AS macd_signal
            FROM macd_calc
        ),
        macd_lagged AS (
            SELECT
                ticker, date, close, volume, prev_close, vol_sma_20,
                macd_line - macd_signal AS macd_hist,
                LAG(macd_line - macd_signal) OVER (PARTITION BY ticker ORDER BY date) AS prev_macd_hist
            FROM macd_hist
        ),
        signals AS (
            SELECT
                ticker,
                date,
                close,
                volume,
                prev_close,
                macd_hist,
                prev_macd_hist,
                CASE WHEN vol_sma_20 > 0 THEN volume / vol_sma_20 ELSE NULL END AS volume_ratio
            FROM macd_lagged
            WHERE date = (SELECT MAX(date) FROM silver.unified_prices WHERE ticker IN ({tickers_str}))
        )
        SELECT
            ticker,
            date,
            close,
            volume,
            prev_close,
            macd_hist,
            prev_macd_hist,
            volume_ratio
        FROM signals
        WHERE macd_hist >= {ENTRY_HIST_THRESH}
          AND prev_macd_hist <= {PREV_HIST_THRESH}
          AND volume_ratio >= {VOLUME_RATIO_MIN}
        ORDER BY ticker
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


def insert_signal(conn, ticker, signal_date, entry_date, macd_hist, prev_macd_hist, volume_ratio, entry_price):
    signal_strength = round(macd_hist - ENTRY_HIST_THRESH, 6)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gold.s9_macd_signals
            (strategy_id, ticker, signal_date, entry_date, macd_hist, prev_macd_hist, volume_ratio, signal_strength, entry_price_est, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)
        ON CONFLICT (strategy_id, ticker, signal_date) DO UPDATE SET
            macd_hist = EXCLUDED.macd_hist,
            prev_macd_hist = EXCLUDED.prev_macd_hist,
            volume_ratio = EXCLUDED.volume_ratio,
            signal_strength = EXCLUDED.signal_strength,
            entry_price_est = EXCLUDED.entry_price_est,
            is_active = true,
            processed_at = NOW()
        RETURNING id
    """, (STRATEGY_ID, ticker, signal_date, entry_date, macd_hist, prev_macd_hist, volume_ratio, signal_strength, entry_price))
    signal_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return signal_id


def insert_paper_trade(conn, ticker, entry_date, entry_price, signal_id):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gold.s9_paper_trades
            (strategy_id, ticker, entry_date, direction, entry_price, signal_id, execution_mode, status)
        VALUES (%s, %s, %s, 'LONG', %s, %s, 'PAPER', 'OPEN')
        ON CONFLICT DO NOTHING
    """, (STRATEGY_ID, ticker, entry_date, entry_price, signal_id))
    conn.commit()
    cur.close()


def check_exits(conn):
    """Check OPEN trades for TP/SL/max-hold exit conditions."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, ticker, entry_date, entry_price
        FROM gold.s9_paper_trades
        WHERE strategy_id = %s AND status = 'OPEN'
    """, (STRATEGY_ID,))
    open_trades = cur.fetchall()

    today = None
    cur.execute("SELECT MAX(date) FROM silver.unified_prices")
    row = cur.fetchone()
    if row and row[0]:
        today = row[0]

    exited = 0
    for trade_id, ticker, entry_date, entry_price in open_trades:
        if today is None:
            continue
        hold_days = (today - entry_date).days

        # Get today's close
        cur.execute("SELECT close FROM silver.unified_prices WHERE ticker = %s AND date = %s", (ticker, today))
        price_row = cur.fetchone()
        if not price_row:
            continue
        current_price = price_row[0]
        pnl_pct = round((current_price - entry_price) / entry_price, 6)

        exit_reason = None
        if pnl_pct >= TP_PCT:
            exit_reason = 'TAKE_PROFIT'
        elif pnl_pct <= SL_PCT:
            exit_reason = 'STOP_LOSS'
        elif hold_days >= MAX_HOLD_DAYS:
            exit_reason = 'MAX_HOLD'

        if exit_reason:
            cur.execute("""
                UPDATE gold.s9_paper_trades
                SET status = 'CLOSED',
                    exit_date = %s,
                    exit_price = %s,
                    pnl_pct = %s,
                    hold_days = %s,
                    exit_reason = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (today, current_price, pnl_pct, hold_days, exit_reason, trade_id))
            exited += 1

    conn.commit()
    cur.close()
    return exited


def run():
    conn = get_connection()
    try:
        regime = get_today_regime(conn)
        print(f"  Regime: {regime}")

        # Check exits first
        exited = check_exits(conn)
        if exited:
            print(f"  Closed {exited} trades")

        if regime != 'TREND':
            print(f"  Skipping S9 signal generation — regime is {regime}, not TREND")
            return

        if has_open_trade(conn):
            print("  Skipping S9 signal generation — OPEN trade exists (single-position constraint)")
            return

        signals = find_signals(conn)
        if not signals:
            print("  No S9 signals today")
            return

        # Take first signal alphabetically (backtest tie-break rule)
        row = signals[0]
        ticker, signal_date, close, volume, prev_close, macd_hist, prev_macd_hist, volume_ratio = row
        entry_date = signal_date  # MARKET_ON_OPEN same day for daily bars
        entry_price = close

        signal_id = insert_signal(conn, ticker, signal_date, entry_date, macd_hist, prev_macd_hist, volume_ratio, entry_price)
        insert_paper_trade(conn, ticker, entry_date, entry_price, signal_id)
        print(f"  Signal: {ticker} | hist={macd_hist:.4f} | prev_hist={prev_macd_hist:.4f} | vol_ratio={volume_ratio:.2f} | strength={macd_hist - ENTRY_HIST_THRESH:.4f}")
        print(f"  Paper trade OPEN: {ticker} @ {entry_price:.2f}")

    finally:
        conn.close()


if __name__ == '__main__':
    run()
