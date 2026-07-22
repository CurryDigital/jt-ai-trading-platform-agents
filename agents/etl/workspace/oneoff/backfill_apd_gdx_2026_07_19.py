#!/usr/bin/env python3
"""
One-off backfill: APD + GDX

Problem: APD was marked inactive in gold.asset_registry on 2026-04-11 and
stopped updating in bronze.yf_prices after 2026-04-10. GDX was never in the
asset registry, so it never got price data.

This script:
  1. Reactivates APD and inserts GDX into gold.asset_registry.
  2. Fetches 5 years of daily OHLCV from yfinance for both tickers.
  3. Upserts into bronze.yf_prices.

After running this, the normal silver/gold pipeline should be executed to
propagate the data through silver.unified_prices, silver.technical_indicators,
and gold.kpis_metrics.

Author: qr_etl
Date: 2026-07-19
"""
import sys, os, time
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection
import yfinance as yf
from datetime import date, timedelta
import pandas as pd

TARGET_TICKERS = {
    'APD': {'name': 'Air Products and Chemicals Inc', 'asset_class': 'STOCK', 'market': 'US', 'sector': 'Materials'},
    'GDX': {'name': 'VanEck Gold Miners ETF', 'asset_class': 'ETF', 'market': 'US', 'sector': 'ETF'},
}

START_DATE = (date.today() - timedelta(days=365*5+30)).isoformat()
CHUNK_SIZE = 90


def ensure_asset_registry(conn):
    cur = conn.cursor()
    cur.execute("SELECT ticker, is_active FROM gold.asset_registry WHERE ticker = ANY(%s)",
                (list(TARGET_TICKERS.keys()),))
    existing = {r[0]: r[1] for r in cur.fetchall()}

    for ticker, meta in TARGET_TICKERS.items():
        if ticker in existing:
            cur.execute("""
                UPDATE gold.asset_registry
                SET is_active = TRUE,
                    updated_at = NOW()
                WHERE ticker = %s
            """, (ticker,))
            print(f"asset_registry: reactivated {ticker}")
        else:
            cur.execute("""
                INSERT INTO gold.asset_registry
                    (ticker, name, asset_class, market, sector, is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, TRUE, NOW(), NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    name = EXCLUDED.name,
                    asset_class = EXCLUDED.asset_class,
                    market = EXCLUDED.market,
                    sector = EXCLUDED.sector,
                    is_active = TRUE,
                    updated_at = NOW()
            """, (ticker, meta['name'], meta['asset_class'], meta['market'], meta['sector']))
            print(f"asset_registry: inserted {ticker}")
    conn.commit()


def _upsert_prices(cur, ticker, df):
    inserted = 0
    for _, row in df.iterrows():
        try:
            if not pd.notna(row['Close']):
                continue
            cur.execute("""
                INSERT INTO bronze.yf_prices
                    (ticker, date, open, high, low, close, volume, adjusted_close, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                    open = COALESCE(EXCLUDED.open, bronze.yf_prices.open),
                    high = COALESCE(EXCLUDED.high, bronze.yf_prices.high),
                    low = COALESCE(EXCLUDED.low, bronze.yf_prices.low),
                    close = COALESCE(EXCLUDED.close, bronze.yf_prices.close),
                    volume = COALESCE(EXCLUDED.volume, bronze.yf_prices.volume),
                    adjusted_close = COALESCE(EXCLUDED.adjusted_close, bronze.yf_prices.adjusted_close)
            """, (
                ticker,
                row['Date'].date() if hasattr(row['Date'], 'date') else row['Date'],
                float(row['Open']) if pd.notna(row['Open']) else None,
                float(row['High']) if pd.notna(row['High']) else None,
                float(row['Low']) if pd.notna(row['Low']) else None,
                float(row['Close']) if pd.notna(row['Close']) else None,
                int(row['Volume']) if pd.notna(row['Volume']) else None,
                float(row['Close']) if pd.notna(row['Close']) else None,
            ))
            inserted += 1
        except Exception as e:
            print(f"    Row error {ticker}: {e}")
    return inserted


def backfill_prices():
    conn = get_connection()
    ensure_asset_registry(conn)
    cur = conn.cursor()

    tickers = list(TARGET_TICKERS.keys())
    inserted = 0
    failures = []

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i+CHUNK_SIZE]
        print(f"Fetching chunk {i//CHUNK_SIZE+1}: {chunk}")
        try:
            data = yf.download(chunk, start=START_DATE, auto_adjust=True, progress=False)
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
            time.sleep(0.5)
        conn.commit()
        print(f"  Running total: {inserted} rows, {len(failures)} failures")

    conn.commit()
    conn.close()
    print(f"✅ bronze.yf_prices backfill complete: {inserted} rows upserted, failures={failures}")


if __name__ == '__main__':
    backfill_prices()
