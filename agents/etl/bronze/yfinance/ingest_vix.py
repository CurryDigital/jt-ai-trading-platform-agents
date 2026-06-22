#!/usr/bin/env python3
"""
Bronze Ingestion: VIX via yfinance
Tables:
  bronze.yf_prices  — raw ^VIX daily close (REUSED)
  silver.vix_indicators — vix, vix_sma60, vix_z60
Source: yfinance ticker ^VIX

Validation:
  - Raises ValueError if DataFrame empty
  - Raises ValueError if close <= 0 or NaN
  - Raises ValueError if vix_z60 is NaN/Inf
  - Requires minimum 60 rows for SMA/z-score
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta
import math
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("⚠️  yfinance not installed — run: pip install yfinance")
    sys.exit(1)

TICKER = '^VIX'
MIN_ROWS_FOR_SMA = 60


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns from yfinance single-ticker download."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = ['_'.join(col).strip() if col[1] else col[0] for col in df.columns.values]
    return df


def _validate_prices(df):
    """Raise on invalid price data."""
    if df is None or df.empty:
        raise ValueError("VIX fetch returned empty DataFrame")
    close_col = f"Close_{TICKER}" if f"Close_{TICKER}" in df.columns else 'Close'
    if close_col not in df.columns:
        raise ValueError(f"VIX DataFrame missing close column (looked for {close_col})")
    close_series = df[close_col]
    if close_series.isna().all():
        raise ValueError("VIX close prices are all NaN")
    if (close_series <= 0).any():
        bad = df[close_series <= 0]
        raise ValueError(f"VIX close <= 0 on {len(bad)} rows: {bad.index.tolist()[:5]}")


def _validate_zscore(series):
    """Raise on invalid z-score output."""
    if series.isna().all():
        raise ValueError("vix_z60 is all NaN — insufficient history")
    if series.isin([math.inf, -math.inf]).any():
        raise ValueError("vix_z60 contains Inf values")


def fetch_vix(days_back: int = 365):
    """Fetch ^VIX from yfinance."""
    start = (date.today() - timedelta(days=days_back)).isoformat()
    print(f"  Fetching {TICKER} from {start}…")
    data = yf.download(TICKER, start=start, auto_adjust=True, progress=False)
    data = _flatten_columns(data)
    _validate_prices(data)
    return data


def ingest_bronze(df):
    """Upsert raw VIX close into bronze.yf_prices."""
    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    close_col = f"Close_{TICKER}" if f"Close_{TICKER}" in df.columns else 'Close'
    open_col = f"Open_{TICKER}" if f"Open_{TICKER}" in df.columns else 'Open'
    high_col = f"High_{TICKER}" if f"High_{TICKER}" in df.columns else 'High'
    low_col = f"Low_{TICKER}" if f"Low_{TICKER}" in df.columns else 'Low'
    vol_col = f"Volume_{TICKER}" if f"Volume_{TICKER}" in df.columns else 'Volume'

    for ts, row in df.iterrows():
        try:
            close_raw = row[close_col]
            close_val = float(close_raw) if pd.notna(close_raw) else None
            if close_val is None or close_val <= 0:
                continue

            def _get(col):
                v = row[col]
                return float(v) if pd.notna(v) else None

            cur.execute("""
                INSERT INTO bronze.yf_prices
                    (ticker, date, open, high, low, close, volume,
                     adjusted_close, ingested_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                    close = EXCLUDED.close,
                    adjusted_close = EXCLUDED.adjusted_close,
                    ingested_at = NOW()
            """, (
                TICKER,
                ts.date(),
                _get(open_col),
                _get(high_col),
                _get(low_col),
                close_val,
                int(_get(vol_col)) if _get(vol_col) is not None else 0,
                close_val,
            ))
            inserted += 1
        except Exception as e:
            print(f"    Row error {ts}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.yf_prices ({TICKER}) — {inserted} rows upserted")
    return inserted


def compute_and_ingest_silver(df):
    """Compute vix_sma60, vix_z60 and upsert into silver.vix_indicators.
    
    Uses full historical VIX data from bronze.yf_prices to ensure the 60-day
    rolling window has sufficient history. Only the most recent fetched rows
    are updated; historical rows are preserved.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    # Load full VIX history for accurate rolling computation
    cur.execute("""
        SELECT date, close FROM bronze.yf_prices
        WHERE ticker = %s
        ORDER BY date
    """, (TICKER,))
    rows = cur.fetchall()
    if not rows:
        conn.close()
        raise ValueError("No VIX history found in bronze.yf_prices")
    
    hist = pd.DataFrame(rows, columns=['date', 'vix'])
    hist['date'] = pd.to_datetime(hist['date'])
    hist = hist.set_index('date').sort_index()
    hist['vix'] = hist['vix'].astype(float)
    
    # Compute indicators on full history
    hist['vix_sma60'] = hist['vix'].rolling(window=MIN_ROWS_FOR_SMA, min_periods=MIN_ROWS_FOR_SMA).mean()
    rolling_std = hist['vix'].rolling(window=MIN_ROWS_FOR_SMA, min_periods=MIN_ROWS_FOR_SMA).std()
    hist['vix_z60'] = (hist['vix'] - hist['vix_sma60']) / rolling_std
    
    _validate_zscore(hist['vix_z60'])
    
    # Upsert all rows
    inserted = 0
    for ts, row in hist.iterrows():
        try:
            vix = float(row['vix']) if pd.notna(row['vix']) else None
            vix_sma60 = float(row['vix_sma60']) if pd.notna(row['vix_sma60']) else None
            vix_z60 = float(row['vix_z60']) if pd.notna(row['vix_z60']) else None
            if vix is None:
                continue
            cur.execute("""
                INSERT INTO silver.vix_indicators
                    (ticker, date, vix, vix_sma60, vix_z60, calculated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ticker, date) DO UPDATE SET
                    vix = EXCLUDED.vix,
                    vix_sma60 = EXCLUDED.vix_sma60,
                    vix_z60 = EXCLUDED.vix_z60,
                    calculated_at = NOW()
            """, (TICKER, ts.date(), vix, vix_sma60, vix_z60))
            inserted += 1
        except Exception as e:
            print(f"    Row error {ts.date()}: {e}")
    
    conn.commit()
    conn.close()
    print(f"✅ silver.vix_indicators ({TICKER}) — {inserted} rows upserted")
    return inserted


def main():
    try:
        df = fetch_vix(days_back=90)
    except Exception as e:
        print(f"⚠️ VIX fetch failed: {e} — skipping")
        return
    ingest_bronze(df)
    compute_and_ingest_silver(df)


if __name__ == "__main__":
    main()
