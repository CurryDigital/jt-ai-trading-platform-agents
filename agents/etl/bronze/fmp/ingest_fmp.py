# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Bronze Ingestion: Financial Modeling Prep (FMP)
Tables:
  bronze.fmp_prices                — historical daily OHLCV
  bronze.fmp_quotes                — live/latest quote snapshots
  bronze.fmp_earnings              — earnings calendar (estimates + actuals)
  bronze.fmp_earnings_surprises    — EPS surprise records
  bronze.fmp_analyst_ratings       — analyst upgrades/downgrades
  bronze.fmp_institutional_holdings — institutional ownership data
Source: FMP REST API  (https://financialmodelingprep.com/developer/docs)
Env:   FMP_API_KEY
"""
import sys, os, json
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

# Load Hermes env file
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'))

from db import get_connection
from datetime import date, timedelta

try:
    import requests
except ImportError:
    print("⚠️  requests not installed — run: pip install requests")
    sys.exit(0)

# FMP API disabled — paid plan required
print("⚠️  FMP ingestion skipped: paid plan required (403 Forbidden)")
sys.exit(0)

API_KEY = os.getenv('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com/api/v3'

if not API_KEY:
    print("⚠️  FMP_API_KEY not set — skipping FMP ingestion")
    sys.exit(0)


def fmp_get(endpoint: str, params: dict = None) -> list:
    """GET from FMP API, return parsed JSON list."""
    url = f"{BASE_URL}/{endpoint}"
    p   = {'apikey': API_KEY}
    if params:
        p.update(params)
    r = requests.get(url, params=p, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else [data]

def get_active_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE is_active = TRUE AND asset_class IN ('STOCK', 'ETF')
        ORDER BY ticker
    """)
    return [r[0] for r in cur.fetchall()]

# ── Historical Prices ─────────────────────────────────────────────────────────

def ingest_prices(tickers: list = None, days_back: int = 10):
    if not API_KEY:
        print("⚠️  FMP_API_KEY not set — skipping fmp_prices")
        return
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
    cur     = conn.cursor()
    start   = (date.today() - timedelta(days=days_back)).isoformat()
    inserted = 0

    for ticker in tickers:
        try:
            rows = fmp_get(f'historical-price-full/{ticker}', {'from': start})
            history = rows[0].get('historical', []) if rows else []
            for row in history:
                try:
                    cur.execute("""
                        INSERT INTO bronze.fmp_prices
                            (ticker, date, open, high, low, close, volume,
                             adjusted_close, raw_data, ingested_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (ticker, date) DO UPDATE SET
                            close          = EXCLUDED.close,
                            adjusted_close = EXCLUDED.adjusted_close
                    """, (
                        ticker, row.get('date'),
                        row.get('open'), row.get('high'),
                        row.get('low'),  row.get('close'),
                        row.get('volume'), row.get('adjClose'),
                        json.dumps(row),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.fmp_prices — {inserted} rows upserted")


# ── Live Quotes ───────────────────────────────────────────────────────────────

def ingest_quotes(tickers: list = None):
    if not API_KEY:
        print("⚠️  FMP_API_KEY not set — skipping fmp_quotes")
        return
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
    cur      = conn.cursor()
    inserted = 0

    # FMP accepts comma-separated tickers in bulk
    batch_size = 50
    for i in range(0, len(tickers), batch_size):
        batch = ','.join(tickers[i:i+batch_size])
        try:
            rows = fmp_get(f'quote/{batch}')
            for row in rows:
                try:
                    cur.execute("""
                        INSERT INTO bronze.fmp_quotes
                            (ticker, price, change, change_pct, volume, market_cap,
                             pe_ratio, eps, day_high, day_low, year_high, year_low,
                             sma_50, sma_200, raw_data, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, timestamp) DO NOTHING
                    """, (
                        row.get('symbol'), row.get('price'),
                        row.get('change'), row.get('changesPercentage'),
                        row.get('volume'), row.get('marketCap'),
                        row.get('pe'),     row.get('eps'),
                        row.get('dayHigh'), row.get('dayLow'),
                        row.get('yearHigh'), row.get('yearLow'),
                        row.get('priceAvg50'), row.get('priceAvg200'),
                        json.dumps(row),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Quote error: {e}")
        except Exception as e:
            print(f"  Batch error: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.fmp_quotes — {inserted} rows upserted")


# ── Earnings Calendar ─────────────────────────────────────────────────────────

def ingest_earnings(tickers: list = None):
    if not API_KEY:
        print("⚠️  FMP_API_KEY not set — skipping fmp_earnings")
        return
    conn     = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
    cur      = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            rows = fmp_get(f'historical/earning_calendar/{ticker}', {'limit': 20})
            for row in rows:
                try:
                    cur.execute("""
                        INSERT INTO bronze.fmp_earnings
                            (ticker, report_date, fiscal_date_ending,
                             eps_estimate, eps_actual, revenue_estimate, revenue_actual,
                             time_of_day, raw_data, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, report_date) DO UPDATE SET
                            eps_actual      = EXCLUDED.eps_actual,
                            revenue_actual  = EXCLUDED.revenue_actual
                    """, (
                        ticker,
                        row.get('date'),
                        row.get('fiscalDateEnding'),
                        row.get('epsEstimated'),
                        row.get('eps'),
                        row.get('revenueEstimated'),
                        row.get('revenue'),
                        row.get('time'),
                        json.dumps(row),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.fmp_earnings — {inserted} rows upserted")


# ── Earnings Surprises ────────────────────────────────────────────────────────

def ingest_earnings_surprises(tickers: list = None):
    if not API_KEY:
        print("⚠️  FMP_API_KEY not set — skipping fmp_earnings_surprises")
        return
    conn     = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
    cur      = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            rows = fmp_get(f'earnings-surprises/{ticker}')
            for row in rows:
                try:
                    cur.execute("""
                        INSERT INTO bronze.fmp_earnings_surprises
                            (ticker, report_date, actual_eps, estimated_eps,
                             surprise_pct, surprise_dollar, raw_data, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, report_date) DO UPDATE SET
                            actual_eps   = EXCLUDED.actual_eps,
                            surprise_pct = EXCLUDED.surprise_pct
                    """, (
                        ticker,
                        row.get('date'),
                        row.get('actualEarningResult'),
                        row.get('estimatedEarning'),
                        row.get('surprisePercent'),
                        row.get('earningsDifference'),
                        json.dumps(row),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.fmp_earnings_surprises — {inserted} rows upserted")


# ── Analyst Ratings ───────────────────────────────────────────────────────────

def ingest_analyst_ratings(tickers: list = None):
    if not API_KEY:
        print("⚠️  FMP_API_KEY not set — skipping fmp_analyst_ratings")
        return
    conn     = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
    cur      = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            rows = fmp_get(f'upgrades-downgrades/{ticker}', {'limit': 20})
            for row in rows:
                try:
                    cur.execute("""
                        INSERT INTO bronze.fmp_analyst_ratings
                            (ticker, firm, rating, prev_rating,
                             target_price, prev_target, action,
                             report_date, raw_data, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, firm, report_date) DO UPDATE SET
                            rating       = EXCLUDED.rating,
                            target_price = EXCLUDED.target_price
                    """, (
                        ticker,
                        row.get('gradingCompany'),
                        row.get('newGrade'),
                        row.get('previousGrade'),
                        row.get('priceTarget'),
                        row.get('previousPriceTarget'),
                        row.get('action'),
                        row.get('publishedDate', '')[:10],
                        json.dumps(row),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.fmp_analyst_ratings — {inserted} rows upserted")


# ── Institutional Holdings ────────────────────────────────────────────────────

def ingest_institutional_holdings(tickers: list = None, max_tickers: int = None):
    if not API_KEY:
        print("⚠️  FMP_API_KEY not set — skipping fmp_institutional_holdings")
        return
    conn     = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
        if max_tickers:
            tickers = tickers[:max_tickers]
    elif max_tickers:
        tickers = tickers[:max_tickers]
    cur      = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            rows = fmp_get(f'institutional-holder/{ticker}')
            for row in rows:
                try:
                    cur.execute("""
                        INSERT INTO bronze.fmp_institutional_holdings
                            (ticker, holder_name, shares, shares_change,
                             pct_out, pct_held, value,
                             report_date, raw_data, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, holder_name, report_date) DO UPDATE SET
                            shares       = EXCLUDED.shares,
                            shares_change = EXCLUDED.shares_change
                    """, (
                        ticker,
                        row.get('holder'),
                        row.get('shares'),
                        row.get('change'),
                        row.get('weightPercent'),
                        row.get('percentHeld'),
                        row.get('value'),
                        row.get('dateReported', '')[:10] or None,
                        json.dumps(row),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    limit_note = f" (limited to {max_tickers} tickers)" if max_tickers else ""
    print(f"✅ bronze.fmp_institutional_holdings — {inserted} rows upserted{limit_note}")




def _mark_freshness(error=None):
    """Update gold.source_freshness for the operator dashboard. Soft-fails."""
    try:
        from db import get_connection
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='fmp', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")

if __name__ == "__main__":
    try:
        # SKIPPED — tables dropped during DB cleanup (API 403 on most endpoints)
        # ingest_prices()
        # ingest_quotes()
        # ingest_earnings()
        # ingest_earnings_surprises()
        # ingest_analyst_ratings()
        # Only institutional holdings still active
        ingest_institutional_holdings()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
