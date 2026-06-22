#!/home/ubuntu/.hermes/hermes-agent/venv/bin/python3
"""
earnings_update.py
==================
Fetches eps_actual from yfinance for tickers that have reported earnings
but don't yet have eps_actual in silver.unified_earnings.

Runs: Tuesday-Friday 09:30 ET (before morning_run at 09:45)
Purpose: Populate eps_actual + compute price_reaction_1d for PEAD strategies

Usage:
    python earnings_update.py              # all tickers
    python earnings_update.py --ticker HPE # single ticker
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# Tickers to monitor (expandable)
DEFAULT_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'TSLA',
    'JPM', 'JNJ', 'V', 'HPE', 'PANW', 'DG', 'CRWD', 'AVGO', 'ULTA'
]


def fetch_earnings_actual(ticker: str) -> list:
    """
    Fetch earnings dates + actuals from yfinance.
    Returns list of dicts: [{date, eps_estimate, eps_actual, surprise_pct}, ...]
    """
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is None or ed.empty:
            return []

        results = []
        for idx, row in ed.iterrows():
            date_val = idx.date() if hasattr(idx, 'date') else pd.Timestamp(idx).date()
            eps_est = row['EPS Estimate']
            eps_act = row['Reported EPS']

            # Only include rows with valid data
            # Guard: skip future dates — forward estimates belong in earnings_calendar only
            from datetime import date as _date
            if date_val > _date.today():
                continue
            if pd.notna(eps_est) or pd.notna(eps_act):
                results.append({
                    'date': date_val,
                    'eps_estimate': float(eps_est) if pd.notna(eps_est) else None,
                    'eps_actual': float(eps_act) if pd.notna(eps_act) else None,
                    'surprise_pct': float(row['Surprise(%)']) if pd.notna(row['Surprise(%)']) else None,
                })
        return results
    except Exception as e:
        print(f"  ⚠️ {ticker}: yfinance error — {e}")
        return []


def compute_price_reaction(conn, ticker: str, report_date) -> float:
    """
    Compute price reaction = (close_t+1 - close_t) / close_t * 100
    where t = report_date (after-hours) → t+1 = next trading day open/close

    Falls back to previous trading day if report_date has no price data
    (e.g. earnings reported on a weekend or holiday).
    Logs a warning when price data is missing entirely.
    """
    try:
        cur = conn.cursor()
        # First try: exact report_date as t
        cur.execute("""
            SELECT date, close
            FROM silver.unified_prices
            WHERE ticker = %s AND date >= %s
            ORDER BY date
            LIMIT 2
        """, (ticker, report_date))
        rows = cur.fetchall()

        # Fallback: if report_date itself has no price, use previous trading day
        if len(rows) < 2 or rows[0][0] != report_date:
            cur.execute("""
                SELECT date, close
                FROM silver.unified_prices
                WHERE ticker = %s AND date <= %s
                ORDER BY date DESC
                LIMIT 1
            """, (ticker, report_date))
            prev_row = cur.fetchone()
            if prev_row is None:
                print(f"  ⚠️ {ticker} {report_date}: no price data available")
                return None
            # Get next trading day after the fallback date
            cur.execute("""
                SELECT date, close
                FROM silver.unified_prices
                WHERE ticker = %s AND date > %s
                ORDER BY date
                LIMIT 1
            """, (ticker, prev_row[0]))
            next_row = cur.fetchone()
            if next_row is None:
                print(f"  ⚠️ {ticker} {report_date}: no next-day price after {prev_row[0]}")
                return None
            close_t = prev_row[1]
            close_t1 = next_row[1]
        else:
            close_t = rows[0][1]
            close_t1 = rows[1][1]

        if close_t and close_t1:
            return round((close_t1 - close_t) / close_t * 100, 4)
        return None
    except Exception as e:
        print(f"  ⚠️ {ticker}: price reaction error — {e}")
        return None


def update_earnings(conn, ticker: str, dry_run: bool = False) -> dict:
    """
    Update silver.unified_earnings for a single ticker.
    Returns summary dict.
    """
    cur = conn.cursor()

    # 1. Find pending earnings (eps_actual IS NULL but eps_estimate IS NOT NULL)
    cur.execute("""
        SELECT report_date, eps_estimate
        FROM silver.unified_earnings
        WHERE ticker = %s AND eps_estimate IS NOT NULL AND eps_actual IS NULL
        ORDER BY report_date
    """, (ticker,))
    pending = cur.fetchall()

    if not pending:
        return {'ticker': ticker, 'pending': 0, 'updated': 0, 'skipped': 0}

    print(f"  {ticker}: {len(pending)} pending earnings")

    # 2. Fetch from yfinance
    yf_data = fetch_earnings_actual(ticker)
    yf_by_date = {d['date']: d for d in yf_data}

    updated = 0
    skipped = 0

    for report_date, eps_estimate in pending:
        # Match by date (within 2 days tolerance for weekend/holiday shifts)
        matched = None
        for yf_date, yf_row in yf_by_date.items():
            if abs((yf_date - report_date).days) <= 2:
                matched = yf_row
                break

        if matched and matched['eps_actual'] is not None:
            eps_actual = matched['eps_actual']
            surprise_pct = matched['surprise_pct']
            eps_surprise_dollar = float(eps_actual) - float(eps_estimate) if eps_estimate else None

            # Compute price reaction
            price_reaction = compute_price_reaction(conn, ticker, report_date)

            if not dry_run:
                # Check if price_reaction_1d column exists
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'silver' AND table_name = 'unified_earnings'
                    AND column_name = 'price_reaction_1d'
                """)
                has_price_reaction = cur.fetchone() is not None

                if has_price_reaction:
                    cur.execute("""
                        UPDATE silver.unified_earnings
                        SET eps_actual = %s,
                            eps_surprise_pct = %s,
                            eps_surprise_dollar = %s,
                            price_reaction_1d = %s,
                            updated_at = NOW()
                        WHERE ticker = %s AND report_date = %s
                    """, (eps_actual, surprise_pct, eps_surprise_dollar, price_reaction,
                          ticker, report_date))
                else:
                    cur.execute("""
                        UPDATE silver.unified_earnings
                        SET eps_actual = %s,
                            eps_surprise_pct = %s,
                            eps_surprise_dollar = %s,
                            updated_at = NOW()
                        WHERE ticker = %s AND report_date = %s
                    """, (eps_actual, surprise_pct, eps_surprise_dollar,
                          ticker, report_date))
                conn.commit()

                print(f"    ✓ {report_date}: actual={eps_actual}, surprise={surprise_pct}%, reaction={price_reaction}%")
                updated += 1
            else:
                print(f"    [DRY] {report_date}: actual={eps_actual}, surprise={surprise_pct}%, reaction={price_reaction}%")
                updated += 1
        else:
            print(f"    ⏳ {report_date}: still pending (no actuals from yfinance)")
            skipped += 1

    return {'ticker': ticker, 'pending': len(pending), 'updated': updated, 'skipped': skipped}


def run(tickers=None, dry_run=False):
    """Main entry point."""
    if tickers is None:
        tickers = DEFAULT_TICKERS

    print("=" * 60)
    print(f"Earnings Update — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    conn = get_connection()

    total_pending = 0
    total_updated = 0
    total_skipped = 0

    for ticker in tickers:
        result = update_earnings(conn, ticker, dry_run=dry_run)
        total_pending += result['pending']
        total_updated += result['updated']
        total_skipped += result['skipped']

    conn.close()

    print("\n" + "=" * 60)
    print(f"Summary: {total_pending} pending, {total_updated} updated, {total_skipped} skipped")
    print("=" * 60)

    return {'pending': total_pending, 'updated': total_updated, 'skipped': total_skipped}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', help='Single ticker to update')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing')
    args = parser.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else None
    run(tickers=tickers, dry_run=args.dry_run)
