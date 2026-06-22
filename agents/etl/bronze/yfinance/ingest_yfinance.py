# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Bronze Ingestion: Yahoo Finance (yfinance)
Tables:
  bronze.yf_prices              — daily OHLCV for equities/ETFs/indices
  bronze.yf_commodity_futures   — commodity futures OHLCV
  bronze.earnings_calendar      — earnings dates, EPS estimates/actuals
  bronze.institutional_holdings — aggregate institutional ownership
Source: yfinance Python library
Chunked download for speed.
"""
import sys, os, json, time
try:
    import pandas as pd
except ImportError:
    pass
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta

try:
    import yfinance as yf
except ImportError:
    print("⚠️  yfinance not installed — run: pip install yfinance")
    sys.exit(1)

CHUNK_SIZE = 100
SLEEP_BETWEEN_CHUNKS = 0.5

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_active_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE is_active = TRUE
          AND asset_class IN ('STOCK', 'ETF', 'INDEX')
        ORDER BY market = 'US' DESC, market = 'HK' DESC, market = 'CN' DESC, market = 'SG' DESC, ticker
    """)
    return [r[0] for r in cur.fetchall()]

def get_commodity_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ticker FROM bronze.yf_commodity_futures
        UNION
        SELECT ticker FROM gold.asset_registry
        WHERE asset_class = 'COMMODITY'
    """)
    return [r[0] for r in cur.fetchall()] or [
        'GC=F', 'SI=F', 'CL=F', 'NG=F', 'HG=F',
        'ZW=F', 'ZS=F', 'ZC=F', 'KC=F', 'SB=F'
    ]

def _upsert_prices(cur, ticker, df):
    """Upsert a single ticker's price DataFrame. Returns inserted count."""
    inserted = 0
    for _, row in df.iterrows():
        try:
            cur.execute("""
                INSERT INTO bronze.yf_prices
                    (ticker, date, open, high, low, close, volume,
                     adjusted_close, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    adjusted_close = EXCLUDED.adjusted_close
            """, (
                ticker,
                row['Date'].date() if hasattr(row['Date'], 'date') else row['Date'],
                float(row['Open'])   if row['Open']   == row['Open'] else None,
                float(row['High'])   if row['High']   == row['High'] else None,
                float(row['Low'])    if row['Low']    == row['Low']  else None,
                float(row['Close'])  if row['Close']  == row['Close'] else None,
                int(row['Volume'])   if row['Volume'] == row['Volume'] else None,
                float(row['Close'])  if row['Close']  == row['Close'] else None,
            ))
            inserted += 1
        except Exception as e:
            print(f"    Row error {ticker}: {e}")
    return inserted

# ── Equity / ETF Prices (chunked) ─────────────────────────────────────────────

def ingest_yf_prices(tickers: list = None, days_back: int = 5, max_tickers: int = 300):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
        if max_tickers:
            tickers = tickers[:max_tickers]
    elif max_tickers:
        tickers = tickers[:max_tickers]

    if not tickers:
        print("⚠️  No tickers to ingest")
        conn.close()
        return

    start = (date.today() - timedelta(days=days_back)).isoformat()
    print(f"  Fetching {len(tickers)} tickers from {start} in chunks of {CHUNK_SIZE}…")

    cur = conn.cursor()
    inserted = 0
    failures = []

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        try:
            data = yf.download(chunk, start=start, auto_adjust=True, progress=False)
            if len(chunk) == 1:
                ticker = chunk[0]
                df = data.reset_index()
                inserted += _upsert_prices(cur, ticker, df)
            else:
                for ticker in chunk:
                    try:
                        df = data.xs(ticker, axis=1, level=1).reset_index()
                        inserted += _upsert_prices(cur, ticker, df)
                    except Exception as e:
                        failures.append((ticker, str(e)))
                        print(f"  Ticker error {ticker}: {e}")
        except Exception as e:
            failures.append((chunk[0] if chunk else 'unknown', str(e)))
            print(f"  Chunk error starting {chunk[0]}: {e}")

        if i + CHUNK_SIZE < len(tickers):
            time.sleep(SLEEP_BETWEEN_CHUNKS)

    conn.commit()
    conn.close()

    if failures:
        print(f"  ⚠️  {len(failures)} tickers failed (logged above)")
    limit_note = f" (limited to {max_tickers} tickers)" if max_tickers else ""
    print(f"✅ bronze.yf_prices — {inserted} rows upserted{limit_note}")


# ── Commodity Futures ─────────────────────────────────────────────────────────

COMMODITY_META = {
    'GC=F': ('Gold Futures',       'metals',    'COMEX'),
    'SI=F': ('Silver Futures',     'metals',    'COMEX'),
    'CL=F': ('Crude Oil Futures',  'energy',    'NYMEX'),
    'NG=F': ('Natural Gas Futures','energy',    'NYMEX'),
    'HG=F': ('Copper Futures',     'metals',    'COMEX'),
    'ZW=F': ('Wheat Futures',      'grains',    'CBOT'),
    'ZS=F': ('Soybean Futures',    'grains',    'CBOT'),
    'ZC=F': ('Corn Futures',       'grains',    'CBOT'),
    'KC=F': ('Coffee Futures',     'softs',     'ICE'),
    'SB=F': ('Sugar Futures',      'softs',     'ICE'),
}

def ingest_commodity_futures(days_back: int = 7, max_tickers: int = 10):
    conn = get_connection()
    tickers = get_commodity_tickers(conn)[:max_tickers]
    start   = (date.today() - timedelta(days=days_back)).isoformat()

    cur = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            data = yf.download(ticker, start=start, auto_adjust=True, progress=False)
            # Flatten multi-level columns (e.g. ('Close','CL=F')) to single level
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            meta = COMMODITY_META.get(ticker, (ticker, 'unknown', 'unknown'))

            for ts, row in data.iterrows():
                try:
                    open_val  = float(row['Open'])   if pd.notna(row['Open'])   else None
                    high_val  = float(row['High'])   if pd.notna(row['High'])   else None
                    low_val   = float(row['Low'])    if pd.notna(row['Low'])    else None
                    close_val = float(row['Close'])  if pd.notna(row['Close'])  else None
                    vol_val   = int(row['Volume'])   if pd.notna(row['Volume']) else None
                    cur.execute("""
                        INSERT INTO bronze.yf_commodity_futures
                            (ticker, name, category, exchange, date,
                             open, high, low, close, volume, adjusted_close, ingested_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (ticker, date) DO UPDATE SET
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume
                    """, (
                        ticker, meta[0], meta[1], meta[2],
                        ts.date(),
                        open_val, high_val, low_val, close_val, vol_val, close_val,
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker} {ts}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.yf_commodity_futures — {inserted} rows upserted")


# ── Earnings Calendar ─────────────────────────────────────────────────────────

def ingest_earnings_calendar(tickers: list = None):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)

    cur = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            df = t.earnings_dates
            if df is None or df.empty:
                continue
            df = df.reset_index()
            for _, row in df.iterrows():
                try:
                    earnings_date = row.iloc[0].date() if hasattr(row.iloc[0], 'date') else None
                    if earnings_date is None:
                        continue
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
                        ticker,
                        earnings_date,
                        row.get('EPS Estimate') if row.get('EPS Estimate') == row.get('EPS Estimate') else None,
                        row.get('Reported EPS')  if row.get('Reported EPS')  == row.get('Reported EPS')  else None,
                        row.get('Surprise(%)')   if row.get('Surprise(%)')   == row.get('Surprise(%)')   else None,
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.earnings_calendar — {inserted} rows upserted")


# ── Institutional Holdings ────────────────────────────────────────────────────

def ingest_institutional_holdings(tickers: list = None):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)

    cur = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            t   = yf.Ticker(ticker)
            df  = t.institutional_holders
            if df is None or df.empty:
                continue
            today = date.today()
            for _, row in df.iterrows():
                try:
                    cur.execute("""
                        INSERT INTO bronze.institutional_holdings
                            (ticker, report_date, institutional_holders,
                             institutional_pct, top_holder_name, top_holder_pct,
                             source, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'yfinance', NOW())
                        ON CONFLICT (ticker, report_date) DO NOTHING
                    """, (
                        ticker,
                        today,
                        int(len(df)),
                        None,
                        str(row.get('Holder', '')),
                        float(row.get('% Out', 0)) if row.get('% Out') == row.get('% Out') else None,
                    ))
                    inserted += 1
                    break  # only first row for top holder
                except Exception as e:
                    print(f"    Row error {ticker}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.institutional_holdings — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_yf_prices()
    ingest_commodity_futures()
    # ingest_earnings_calendar()      # deferred — too slow for 120s timeout
    # ingest_institutional_holdings() # deferred — too slow for 120s timeout
