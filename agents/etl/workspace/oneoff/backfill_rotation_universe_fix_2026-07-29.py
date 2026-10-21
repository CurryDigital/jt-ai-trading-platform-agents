#!/usr/bin/env python3
"""
DATA_FIX (kanban t_5f218f6c): rotation-signal universe price gaps.

- Onboard EFA, EEM into gold.asset_registry + bronze.yf_prices +
  silver.unified_prices (original 10-asset Multi-Asset universe).
- Backfill FULL 5y history for QYLD, XYLD, PBP (only 15 rows each since
  2026-07-07; 12w momentum not computable, so covered-call rotation can
  only rank JEPI/JEPQ).

Flow follows the established oneoff pattern:
  yfinance -> bronze.yf_prices -> silver.unified_prices
Daily maintenance is automatic afterwards: pipeline A
(bronze/yfinance/ingest_yfinance_prices.py) pulls every active ticker in
gold.asset_registry.
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection
import yfinance as yf
from datetime import date, timedelta
import pandas as pd

NEW_TICKERS = ['EFA', 'EEM']            # onboard from scratch
BACKFILL_TICKERS = ['QYLD', 'XYLD', 'PBP']  # full-history backfill
ALL = NEW_TICKERS + BACKFILL_TICKERS

START_DATE = (date.today() - timedelta(days=365 * 5 + 30)).isoformat()

def ensure_asset_registry(conn):
    cur = conn.cursor()
    for t in NEW_TICKERS:
        cur.execute("""
            INSERT INTO gold.asset_registry (ticker, asset_class, market, sector, is_active, created_at, updated_at)
            VALUES (%s, 'ETF', 'US', 'ETF', TRUE, NOW(), NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                asset_class = 'ETF', market = 'US', is_active = TRUE, updated_at = NOW()
        """, (t,))
    conn.commit()
    print(f"asset_registry: EFA/EEM registered active (ETF/US)")

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

def fetch_bronze(conn):
    cur = conn.cursor()
    total = 0
    failures = []
    for ticker in ALL:
        try:
            df = yf.download(ticker, start=START_DATE, auto_adjust=True, progress=False)
            if df.empty:
                failures.append((ticker, 'empty dataframe'))
                print(f"  {ticker}: EMPTY — check yfinance symbol")
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            n = _upsert_prices(cur, ticker, df.reset_index())
            conn.commit()
            total += n
            print(f"  {ticker}: {n} rows upserted to bronze.yf_prices")
        except Exception as e:
            failures.append((ticker, str(e)))
            print(f"  {ticker}: ERROR {e}")
    print(f"bronze total: {total} rows, failures={failures}")
    return failures

PROMOTE_SQL = """
INSERT INTO silver.unified_prices
    (ticker, asset_class, market, date, open, high, low, close, volume,
     adjusted_close, returns_1d, returns_log, primary_source, all_sources, updated_at)
SELECT
    yf.ticker,
    ar.asset_class,
    ar.market,
    yf.date,
    yf.open::numeric(20,8),
    yf.high::numeric(20,8),
    yf.low::numeric(20,8),
    yf.close::numeric(20,8),
    yf.volume::numeric,
    yf.adjusted_close::numeric(20,8),
    ROUND(
        (yf.close - LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date))
        / NULLIF(LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date), 0),
        6
    ) AS returns_1d,
    ROUND(
        LN(NULLIF(GREATEST(yf.close, 0.0001), 0) / NULLIF(GREATEST(LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date), 0.0001), 0)),
        6
    ) AS returns_log,
    'yfinance' AS primary_source,
    jsonb_build_array('yfinance') AS all_sources,
    NOW() AS updated_at
FROM bronze.yf_prices yf
LEFT JOIN gold.asset_registry ar ON ar.ticker = yf.ticker
WHERE yf.ticker = ANY(%s)
ON CONFLICT (ticker, date) DO UPDATE SET
    open            = EXCLUDED.open,
    high            = EXCLUDED.high,
    low             = EXCLUDED.low,
    close           = EXCLUDED.close,
    volume          = EXCLUDED.volume,
    adjusted_close  = EXCLUDED.adjusted_close,
    returns_1d      = EXCLUDED.returns_1d,
    returns_log     = EXCLUDED.returns_log,
    primary_source  = EXCLUDED.primary_source,
    all_sources     = EXCLUDED.all_sources,
    updated_at      = NOW();
"""

def promote_silver(conn):
    cur = conn.cursor()
    cur.execute(PROMOTE_SQL, (ALL,))
    n = cur.rowcount
    conn.commit()
    print(f"silver.unified_prices: {n} rows upserted for {ALL}")

if __name__ == '__main__':
    conn = get_connection()
    ensure_asset_registry(conn)
    conn.close()
    conn = get_connection()
    failures = fetch_bronze(conn)
    conn.close()
    conn = get_connection()
    promote_silver(conn)
    conn.close()
    print("DONE" if not failures else f"DONE with failures: {failures}")
