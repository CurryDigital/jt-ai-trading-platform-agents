#!/usr/bin/env python3
"""
Bronze Ingestion: Yahoo Finance (yfinance)
Tables:
  bronze.yf_prices              — daily OHLCV for equities/ETFs/indices
  bronze.yf_commodity_futures   — commodity futures OHLCV
  bronze.earnings_calendar      — earnings dates, EPS estimates/actuals
  bronze.institutional_holdings — aggregate institutional ownership
Source: yfinance Python library
"""
import sys, os, json
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta

try:
    import yfinance as yf
except ImportError:
    print("⚠️  yfinance not installed — run: pip install yfinance")
    sys.exit(1)

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_active_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE is_active = TRUE
          AND asset_class IN ('STOCK', 'ETF', 'INDEX')
        ORDER BY ticker
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

# ── Equity / ETF Prices ───────────────────────────────────────────────────────

def ingest_yf_prices(tickers: list = None, days_back: int = 10):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)

    if not tickers:
        print("⚠️  No tickers to ingest")
        conn.close()
        return

    start = (date.today() - timedelta(days=days_back)).isoformat()
    print(f"  Fetching {len(tickers)} tickers from {start}…")

    data = yf.download(tickers, start=start, auto_adjust=True, progress=False)

    cur = conn.cursor()
    inserted = 0

    if len(tickers) == 1:
        # Single ticker returns a simple DataFrame
        ticker = tickers[0]
        df = data.reset_index()
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
                    row['Date'].date(),
                    float(row['Open'])   if row['Open']   == row['Open'] else None,
                    float(row['High'])   if row['High']   == row['High'] else None,
                    float(row['Low'])    if row['Low']    == row['Low']  else None,
                    float(row['Close'])  if row['Close']  == row['Close'] else None,
                    int(row['Volume'])   if row['Volume'] == row['Volume'] else None,
                    float(row['Close'])  if row['Close']  == row['Close'] else None,
                ))
                inserted += 1
            except Exception as e:
                print(f"    Row error {ticker} {row.get('Date')}: {e}")
    else:
        # Multi-ticker returns MultiIndex columns
        for ticker in tickers:
            try:
                df = data.xs(ticker, axis=1, level=1).reset_index()
                for _, row in df.iterrows():
                    try:
                        cur.execute("""
                            INSERT INTO bronze.yf_prices
                                (ticker, date, open, high, low, close, volume,
                                 adjusted_close, ingested_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (ticker, date) DO UPDATE SET
                                close = EXCLUDED.close,
                                volume = EXCLUDED.volume
                        """, (
                            ticker,
                            row['Date'].date(),
                            float(row['Open'])  if row['Open']  == row['Open']  else None,
                            float(row['High'])  if row['High']  == row['High']  else None,
                            float(row['Low'])   if row['Low']   == row['Low']   else None,
                            float(row['Close']) if row['Close'] == row['Close'] else None,
                            int(row['Volume'])  if row['Volume'] == row['Volume'] else None,
                            float(row['Close']) if row['Close'] == row['Close'] else None,
                        ))
                        inserted += 1
                    except Exception as e:
                        print(f"    Row error {ticker}: {e}")
            except Exception as e:
                print(f"    Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.yf_prices — {inserted} rows upserted")


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

def ingest_commodity_futures(days_back: int = 30):
    conn = get_connection()
    tickers = get_commodity_tickers(conn)
    start   = (date.today() - timedelta(days=days_back)).isoformat()

    cur = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            data = yf.download(ticker, start=start, auto_adjust=True, progress=False)
            meta = COMMODITY_META.get(ticker, (ticker, 'unknown', 'unknown'))

            for ts, row in data.iterrows():
                try:
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
                        float(row['Open'])  if row['Open']  == row['Open']  else None,
                        float(row['High'])  if row['High']  == row['High']  else None,
                        float(row['Low'])   if row['Low']   == row['Low']   else None,
                        float(row['Close']) if row['Close'] == row['Close'] else None,
                        int(row['Volume'])  if row['Volume'] == row['Volume'] else None,
                        float(row['Close']) if row['Close'] == row['Close'] else None,
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
    ingest_earnings_calendar()
    ingest_institutional_holdings()
