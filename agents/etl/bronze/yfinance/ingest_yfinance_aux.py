# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Bronze Ingestion: Yahoo Finance — Auxiliary Data (Weekly Run)
===============================================================
Fetches earnings calendar + institutional holdings.
NOT part of the daily regime pipeline — run separately via cron weekly.
Expected runtime: ~10-15 minutes

Uses ThreadPoolExecutor for parallel yf.Ticker() calls.
Tables:
  bronze.earnings_calendar      — earnings dates, EPS estimates/actuals
  bronze.institutional_holdings — aggregate institutional ownership
"""
import sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date

try:
    import yfinance as yf
except ImportError:
    print("⚠️  yfinance not installed — run: pip install yfinance")
    sys.exit(1)

MAX_WORKERS = 2


def get_active_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE is_active = TRUE
          AND asset_class IN ('STOCK', 'ETF', 'INDEX')
        ORDER BY market = 'US' DESC, ticker
    """)
    return [r[0] for r in cur.fetchall()]


def _fetch_earnings(ticker):
    """Fetch earnings for a single ticker. Returns list of dicts."""
    rows = []
    try:
        t = yf.Ticker(ticker)
        df = t.earnings_dates
        if df is None or df.empty:
            return ticker, rows
        df = df.reset_index()
        for _, row in df.iterrows():
            try:
                earnings_date = row.iloc[0].date() if hasattr(row.iloc[0], 'date') else None
                if earnings_date is None:
                    continue
                eps_est = row.get('EPS Estimate')
                eps_est = float(eps_est) if eps_est is not None and eps_est == eps_est else None
                eps_act = row.get('Reported EPS')
                eps_act = float(eps_act) if eps_act is not None and eps_act == eps_act else None
                eps_sur = row.get('Surprise(%)')
                eps_sur = float(eps_sur) if eps_sur is not None and eps_sur == eps_sur else None
                rows.append({
                    'ticker': ticker,
                    'earnings_date': earnings_date,
                    'eps_estimate': eps_est,
                    'eps_actual': eps_act,
                    'eps_surprise_pct': eps_sur,
                })
            except Exception as e:
                print(f"    Row error {ticker}: {e}")
    except Exception as e:
        print(f"  Ticker error {ticker}: {e}")
    return ticker, rows


def _fetch_holdings(ticker):
    """Fetch institutional holdings for a single ticker. Returns list of dicts."""
    rows = []
    try:
        t = yf.Ticker(ticker)
        df = t.institutional_holders
        if df is None or df.empty:
            return ticker, rows
        today = date.today()
        for _, row in df.iterrows():
            try:
                rows.append({
                    'ticker': ticker,
                    'report_date': today,
                    'institutional_holders': int(len(df)),
                    'institutional_pct': None,
                    'top_holder_name': str(row.get('Holder', '')),
                    'top_holder_pct': float(row.get('% Out', 0)) if row.get('% Out') == row.get('% Out') else None,
                })
                break  # only first row for top holder
            except Exception as e:
                print(f"    Row error {ticker}: {e}")
    except Exception as e:
        print(f"  Ticker error {ticker}: {e}")
    return ticker, rows


# ── Earnings Calendar (parallel) ──────────────────────────────────────────────

def ingest_earnings_calendar(tickers: list = None):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)

    cur = conn.cursor()
    inserted = 0
    failures = []

    print(f"  Fetching earnings for {len(tickers)} tickers with {MAX_WORKERS} workers…")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_earnings, t): t for t in tickers}
        for i, future in enumerate(as_completed(futures)):
            if i % 50 == 0:
                print(f"[earnings_calendar] progress: {i}/{len(tickers)}")
            ticker, rows = future.result(timeout=15)
            for row in rows:
                try:
                    cur.execute("""
                        INSERT INTO bronze.earnings_calendar
                            (ticker, earnings_date,
                             eps_estimate, eps_actual, eps_surprise_pct,
                             source, created_at)
                        VALUES (%s, %s, %s, %s, %s, 'yfinance', NOW())
                        ON CONFLICT (ticker, earnings_date) DO UPDATE SET
                            eps_actual       = EXCLUDED.eps_actual,
                            eps_surprise_pct = EXCLUDED.eps_surprise_pct
                    """, (
                        row['ticker'],
                        row['earnings_date'],
                        row['eps_estimate'],
                        row['eps_actual'],
                        row['eps_surprise_pct'],
                    ))
                    inserted += 1
                except Exception as e:
                    failures.append((ticker, str(e)))
                    print(f"    DB error {ticker}: {e}")

    conn.commit()
    conn.close()
    if failures:
        print(f"  ⚠️  {len(failures)} tickers had DB errors")
    print(f"✅ bronze.earnings_calendar — {inserted} rows upserted")


# ── Institutional Holdings (parallel) ─────────────────────────────────────────

def ingest_institutional_holdings(tickers: list = None):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)

    cur = conn.cursor()
    inserted = 0
    failures = []

    print(f"  Fetching holdings for {len(tickers)} tickers with {MAX_WORKERS} workers…")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_holdings, t): t for t in tickers}
        for i, future in enumerate(as_completed(futures)):
            if i % 50 == 0:
                print(f"[institutional_holdings] progress: {i}/{len(tickers)}")
            ticker, rows = future.result(timeout=15)
            for row in rows:
                try:
                    cur.execute("""
                        INSERT INTO bronze.institutional_holdings
                            (ticker, report_date, institutional_holders,
                             institutional_pct, top_holder_name, top_holder_pct,
                             source, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'yfinance', NOW())
                        ON CONFLICT (ticker, report_date) DO NOTHING
                    """, (
                        row['ticker'],
                        row['report_date'],
                        row['institutional_holders'],
                        row['institutional_pct'],
                        row['top_holder_name'],
                        row['top_holder_pct'],
                    ))
                    inserted += 1
                except Exception as e:
                    failures.append((ticker, str(e)))
                    print(f"    DB error {ticker}: {e}")

    conn.commit()
    conn.close()
    if failures:
        print(f"  ⚠️  {len(failures)} tickers had DB errors")
    print(f"✅ bronze.institutional_holdings — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_earnings_calendar()
    ingest_institutional_holdings()
