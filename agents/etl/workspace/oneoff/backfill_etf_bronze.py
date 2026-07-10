#!/usr/bin/env python3
"""
Backfill 50 liquid ETFs into bronze.yf_prices, then refresh silver/gold downstream.
Fetches 5+ years daily OHLCV from yfinance.
"""
import sys, os, time
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection
import yfinance as yf
from datetime import date, timedelta
import pandas as pd

# 50 ETFs requested
TARGET_ETFS = [
    # Stability / broad equity
    'SPY','VTI','VOO','VUG','VYM','SCHD','JEPI','JEPQ','DIA','IWB','IWV',
    # Growth / tech
    'QQQ','IWF','VGT','XLK','SMH','SOXX','IGV','SKYY','CIBR','HACK','QCLN','ARKK','ARKQ','FNGU','TQQQ','QLD','SSO',
    # Bond / fixed income
    'BND','AGG','TLT','IEF','LQD','HYG','JNK','EMB','MUB','VTEB','GOVT',
    # Commodity / inflation
    'GLD','SLV','USO','UNG','DBA','DBC','CPER','WEAT','PALL','PPLT',
    # REIT / real estate
    'VNQ','SCHH','XLRE','IYR','REM',
    # Crypto / fintech
    'BITO','IBIT','FBTC'
]

CATEGORY_SECTOR = {
    'SPY':'ETF','VTI':'ETF','VOO':'ETF','VUG':'ETF','VYM':'ETF','SCHD':'ETF','JEPI':'ETF','JEPQ':'ETF','DIA':'ETF','IWB':'ETF','IWV':'ETF',
    'QQQ':'ETF','IWF':'ETF','VGT':'ETF','XLK':'ETF','SMH':'ETF','SOXX':'ETF','IGV':'ETF','SKYY':'ETF','CIBR':'ETF','HACK':'ETF','QCLN':'ETF','ARKK':'ETF','ARKQ':'ETF','FNGU':'ETF','TQQQ':'ETF','QLD':'ETF','SSO':'ETF',
    'BND':'ETF','AGG':'ETF','TLT':'ETF','IEF':'ETF','LQD':'ETF','HYG':'ETF','JNK':'ETF','EMB':'ETF','MUB':'ETF','VTEB':'ETF','GOVT':'ETF',
    'GLD':'ETF','SLV':'ETF','USO':'ETF','UNG':'ETF','DBA':'ETF','DBC':'ETF','CPER':'ETF','WEAT':'ETF','PALL':'ETF','PPLT':'ETF',
    'VNQ':'ETF','SCHH':'ETF','XLRE':'ETF','IYR':'ETF','REM':'ETF',
    'BITO':'ETF','IBIT':'ETF','FBTC':'ETF'
}

START_DATE = (date.today() - timedelta(days=365*5+30)).isoformat()
CHUNK_SIZE = 90

def ensure_asset_registry(conn):
    cur = conn.cursor()
    cur.execute("SELECT ticker FROM gold.asset_registry WHERE ticker = ANY(%s)", (TARGET_ETFS,))
    existing = {r[0] for r in cur.fetchall()}
    missing = [t for t in TARGET_ETFS if t not in existing]
    for t in missing:
        cur.execute("""
            INSERT INTO gold.asset_registry (ticker, asset_class, market, sector, is_active, created_at, updated_at)
            VALUES (%s, 'ETF', 'US', %s, TRUE, NOW(), NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                asset_class = EXCLUDED.asset_class,
                market = EXCLUDED.market,
                sector = EXCLUDED.sector,
                is_active = TRUE,
                updated_at = NOW()
        """, (t, CATEGORY_SECTOR.get(t)))
    # For existing, ensure is_active true
    cur.execute("""
        UPDATE gold.asset_registry SET is_active = TRUE, updated_at = NOW()
        WHERE ticker = ANY(%s) AND is_active IS NOT TRUE
    """, (TARGET_ETFS,))
    conn.commit()
    print(f"asset_registry: {len(missing)} inserted, is_active set for {len(TARGET_ETFS)}")

def _upsert_prices(cur, ticker, df):
    inserted = 0
    for _, row in df.iterrows():
        try:
            cur.execute("""
                INSERT INTO bronze.yf_prices (ticker, date, open, high, low, close, volume, adjusted_close, ingested_at)
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

    inserted = 0
    failures = []
    for i in range(0, len(TARGET_ETFS), CHUNK_SIZE):
        chunk = TARGET_ETFS[i:i+CHUNK_SIZE]
        print(f"Fetching chunk {i//CHUNK_SIZE+1}: {chunk[0]}..{chunk[-1]} ({len(chunk)} tickers)")
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
        if i + CHUNK_SIZE < len(TARGET_ETFS):
            time.sleep(0.5)
        conn.commit()
        print(f"  Running total: {inserted} rows, {len(failures)} failures")

    conn.commit()
    conn.close()
    print(f"✅ bronze.yf_prices backfill complete: {inserted} rows upserted, failures={failures}")

if __name__ == '__main__':
    backfill_prices()
