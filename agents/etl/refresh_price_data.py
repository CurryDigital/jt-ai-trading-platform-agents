# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
refresh_price_data.py
=====================
Refreshes stale price data and recomputes regime features.

Goal: REFRESH_PRICE_DATA
Agent: qr_etl
Priority: P1

Usage:
    python refresh_price_data.py

What it does:
1. Checks silver.unified_prices for stale SPY/VIX data
2. Recomputes gold.regime_features for gap dates
3. Handles edge cases (weekends, hurst NaN forward-fill)
"""

import os
import sys
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ─── DB CONFIG ───────────────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "aitrading")
DB_USER = os.getenv("DB_USER", "openclaw_user")
DB_PASS = os.getenv("DB_PASSWORD", "NewStrongPasswordHere12")

# ─── INDICATOR COMPUTATIONS ──────────────────────────────────────────────────

def compute_adx14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Compute 14-day ADX using Wilder's smoothing."""
    plus_dm = high.diff()
    minus_dm = low.diff().abs()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/14, min_periods=14).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/14, min_periods=14).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/14, min_periods=14).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1/14, min_periods=14).mean()
    return adx


def hurst_rs(ts: np.ndarray, max_lag: int = 20) -> float:
    """Hurst exponent via R/S analysis."""
    lags = range(2, min(max_lag + 1, len(ts) // 2))
    tau = [np.std(np.subtract(ts[lag:], ts[:-lag])) for lag in lags]
    if len(tau) < 2 or any(t == 0 for t in tau):
        return np.nan
    reg = np.polyfit(np.log(lags), np.log(tau), 1)
    return reg[0]


def compute_regime_features(spy_df: pd.DataFrame, vix_df: pd.DataFrame,
                            btc_df: pd.DataFrame) -> pd.DataFrame:
    """Compute full regime feature set from raw price data."""
    # Forward fill gaps (weekends/holidays)
    spy_df = spy_df.ffill()
    vix_df = vix_df.ffill()

    # Align VIX to SPY dates
    vix_df = vix_df.reindex(spy_df.index, method='ffill')

    # Returns
    spy_df['returns'] = spy_df['close'].pct_change()

    # ADX14
    spy_df['adx14'] = compute_adx14(spy_df['high'], spy_df['low'], spy_df['close'])

    # Hurst 30-day
    spy_df['hurst_30'] = spy_df['returns'].rolling(window=30).apply(
        lambda x: hurst_rs(x.dropna().values) if len(x.dropna()) >= 20 else np.nan,
        raw=False
    )
    # Forward-fill hurst once for edge cases (weekends, insufficient window)
    spy_df['hurst_30'] = spy_df['hurst_30'].ffill(limit=1)

    # RV5d
    spy_df['rv5d'] = spy_df['returns'].rolling(window=5).std() * np.sqrt(252)

    # Merge with VIX
    merged = spy_df.join(vix_df, how='left')
    merged['rv_iv_ratio'] = merged['rv5d'] / (merged['vix_close'] / 100)

    # VIX z-score (60-day, min 30 observations)
    merged['vix_mean_60'] = merged['vix_close'].rolling(window=60, min_periods=30).mean()
    merged['vix_std_60'] = merged['vix_close'].rolling(window=60, min_periods=30).std()
    merged['vix_z60'] = (merged['vix_close'] - merged['vix_mean_60']) / merged['vix_std_60']

    # SPY above 200d MA
    merged['spy_above_200'] = (merged['close'] > merged['close'].rolling(200).mean()).astype(int)

    # Breadth (50-day % positive returns)
    merged['breadth_50'] = (merged['returns'] > 0).rolling(50).mean()

    # Funding z from BTC
    merged = merged.join(btc_df[['funding_z']], how='left')

    # Event flag
    merged['event_flag'] = 0

    return merged[['adx14', 'hurst_30', 'rv5d', 'rv_iv_ratio', 'vix_z60',
                   'spy_above_200', 'breadth_50', 'funding_z', 'event_flag']]


# ─── DB OPERATIONS ───────────────────────────────────────────────────────────

def fetch_data(conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch SPY, VIX, and BTC funding data from DB."""
    spy = pd.read_sql("""
        SELECT date, open, high, low, close, volume
        FROM silver.unified_prices WHERE ticker = 'SPY' ORDER BY date
    """, conn)
    spy['date'] = pd.to_datetime(spy['date'])
    spy = spy.set_index('date')

    vix = pd.read_sql("""
        SELECT date, close as vix_close
        FROM silver.unified_prices WHERE ticker = '^VIX' ORDER BY date
    """, conn)
    vix['date'] = pd.to_datetime(vix['date'])
    vix = vix.set_index('date')

    btc = pd.read_sql("""
        SELECT date, funding_z
        FROM gold.crypto_funding_metrics WHERE symbol = 'BTCUSDT' ORDER BY date
    """, conn)
    btc['date'] = pd.to_datetime(btc['date'])
    btc = btc.set_index('date')

    return spy, vix, btc


def upsert_regime_features(conn, df: pd.DataFrame) -> int:
    """Upsert regime features to gold.regime_features."""
    cur = conn.cursor()
    sql = """
        INSERT INTO gold.regime_features
        (date, adx14, hurst_30, rv5d, rv_iv_ratio, vix_z60,
         spy_above_200, breadth_50, funding_z, event_flag)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (date) DO UPDATE SET
            adx14 = EXCLUDED.adx14,
            hurst_30 = EXCLUDED.hurst_30,
            rv5d = EXCLUDED.rv5d,
            rv_iv_ratio = EXCLUDED.rv_iv_ratio,
            vix_z60 = EXCLUDED.vix_z60,
            spy_above_200 = EXCLUDED.spy_above_200,
            breadth_50 = EXCLUDED.breadth_50,
            funding_z = EXCLUDED.funding_z,
            event_flag = EXCLUDED.event_flag
    """
    rows = 0
    for date, row in df.iterrows():
        cur.execute(sql, (
            date,
            float(row['adx14']) if pd.notna(row['adx14']) else None,
            float(row['hurst_30']) if pd.notna(row['hurst_30']) else None,
            float(row['rv5d']) if pd.notna(row['rv5d']) else None,
            float(row['rv_iv_ratio']) if pd.notna(row['rv_iv_ratio']) else None,
            float(row['vix_z60']) if pd.notna(row['vix_z60']) else None,
            int(row['spy_above_200']) if pd.notna(row['spy_above_200']) else None,
            float(row['breadth_50']) if pd.notna(row['breadth_50']) else None,
            float(row['funding_z']) if pd.notna(row['funding_z']) else None,
            int(row['event_flag']) if pd.notna(row['event_flag']) else 0
        ))
        rows += 1
    conn.commit()
    cur.close()
    return rows


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now()}] Starting regime features refresh")

    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASS
    )

    # 1. Fetch data
    spy, vix, btc = fetch_data(conn)
    print(f"  SPY: {len(spy)} rows, {spy.index.min().date()} to {spy.index.max().date()}")
    print(f"  VIX: {len(vix)} rows, {vix.index.min().date()} to {vix.index.max().date()}")
    print(f"  BTC funding: {len(btc)} rows, {btc.index.min().date()} to {btc.index.max().date()}")

    # 2. Compute features
    features = compute_regime_features(spy, vix, btc)
    features = features.reset_index()
    features['date'] = features['date'].dt.date

    # 3. Find stale dates (where existing data has NaN or is missing)
    existing = pd.read_sql("""
        SELECT date, adx14, hurst_30 FROM gold.regime_features
        WHERE date >= '2025-01-01' ORDER BY date
    """, conn)
    existing['date'] = pd.to_datetime(existing['date']).dt.date

    # Merge to find rows needing update
    merged_check = existing.merge(features, on='date', how='left', suffixes=('_old', '_new'))

    # Find rows with NaN in existing data
    stale = merged_check[
        (merged_check['adx14_old'].isna()) |
        (merged_check['hurst_30_old'].isna())
    ].copy()

    # Also find missing dates
    all_dates = set(features['date'])
    existing_dates = set(existing['date'])
    missing_dates = all_dates - existing_dates

    print(f"  Stale rows to fix: {len(stale)}")
    print(f"  Missing dates: {len(missing_dates)}")

    # 4. Upsert all recent data (last 30 days) to be safe
    cutoff = (datetime.now() - timedelta(days=30)).date()
    update_df = features[features['date'] >= cutoff].set_index('date')

    # 5. Upsert
    rows = upsert_regime_features(conn, update_df)
    print(f"  Upserted {rows} rows")

    # 6. Verify
    verify = pd.read_sql("""
        SELECT MAX(date) as latest,
               COUNT(CASE WHEN adx14 IS NULL THEN 1 END) as adx_nulls,
               COUNT(CASE WHEN hurst_30 IS NULL THEN 1 END) as hurst_nulls
        FROM gold.regime_features
        WHERE date > '2025-01-01'
    """, conn)
    print(f"\nVerification:")
    print(f"  Latest date: {verify['latest'].iloc()[0]}")
    print(f"  ADX14 nulls (since 2025): {verify['adx_nulls'].iloc()[0]}")
    print(f"  Hurst nulls (since 2025): {verify['hurst_nulls'].iloc()[0]}")

    conn.close()
    print(f"[{datetime.now()}] Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
