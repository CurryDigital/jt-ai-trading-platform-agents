# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
ADX14 OHLCV Backfill — G6d
============================
Backfill missing SPY high/low/close in gold.daily_ohlcv for 4 dates,
then recompute ADX14 in gold.regime_features.

Source priority:
  1. silver.unified_prices — checked, also NULL high/low
  2. yfinance — used (fetched per-date, minimal bandwidth)
  3. IBKR — not needed

ADX14 uses standard Wilder smoothing (14-period).
We fetch 20 bars before the earliest missing date to ensure
ADX14 has enough history for correct computation.
"""
import sys, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

TICKER = 'SPY'
ADX_PERIOD = 14
EXTRA_BARS = 20  # buffer before earliest missing date

# Dates with NULL high/low/close identified by Step 1
MISSING_DATES = ['2026-04-16', '2026-04-23', '2026-05-19', '2026-05-20']


def _wilder_smoothing(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing: first value = SMA, then EMA with alpha=1/period."""
    return series.ewm(alpha=1/period, min_periods=period, adjust=False).mean()


def compute_adx14(df: pd.DataFrame) -> pd.Series:
    """
    Compute ADX14 from OHLC DataFrame.
    Input: DataFrame with columns [high, low, close], sorted by date ascending.
    Output: Series of ADX14 values, same index.
    """
    df = df.copy()
    high = df['high']
    low = df['low']
    close = df['close']

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # +DM / -DM
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    # Smoothed TR, +DM, -DM
    atr = _wilder_smoothing(tr, ADX_PERIOD)
    plus_di = 100 * _wilder_smoothing(plus_dm, ADX_PERIOD) / atr
    minus_di = 100 * _wilder_smoothing(minus_dm, ADX_PERIOD) / atr

    # DX and ADX
    dx = ( (plus_di - minus_di).abs() / (plus_di + minus_di) ) * 100
    adx = _wilder_smoothing(dx, ADX_PERIOD)

    return adx


def fetch_yfinance_ohlcv(dates: list) -> pd.DataFrame:
    """Fetch SPY OHLCV from yfinance for the required date range."""
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance required. Install: pip install yfinance")

    # Need buffer before earliest date for ADX computation
    earliest = min(pd.to_datetime(dates))
    start = (earliest - timedelta(days=EXTRA_BARS + 10)).strftime('%Y-%m-%d')
    end = (max(pd.to_datetime(dates)) + timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"  Fetching yfinance SPY {start} → {end} ...")
    df = yf.download(TICKER, start=start, end=end, progress=False)

    # Flatten MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [' '.join(col).strip() for col in df.columns]
    else:
        df.columns = [f"{col} {TICKER}" for col in df.columns]

    # Rename to standard
    rename_map = {}
    for col in df.columns:
        if 'Open' in col:
            rename_map[col] = 'open'
        elif 'High' in col:
            rename_map[col] = 'high'
        elif 'Low' in col:
            rename_map[col] = 'low'
        elif 'Close' in col:
            rename_map[col] = 'close'
        elif 'Volume' in col:
            rename_map[col] = 'volume'
    df = df.rename(columns=rename_map)
    df = df[['open', 'high', 'low', 'close', 'volume']]
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def update_gold_ohlcv(conn, yf_df: pd.DataFrame, dates: list):
    """UPDATE gold.daily_ohlcv with yfinance high/low/close/open/volume."""
    cur = conn.cursor()
    updated = 0
    for d in dates:
        ts = pd.Timestamp(d)
        if ts not in yf_df.index:
            print(f"  ⚠️  {d} not found in yfinance data — skipping")
            continue
        row = yf_df.loc[ts]
        cur.execute("""
            UPDATE gold.daily_ohlcv
            SET open = %s,
                high = %s,
                low = %s,
                close = %s,
                volume = %s,
                updated_at = NOW()
            WHERE ticker = %s AND date = %s
        """, (
            float(row['open']), float(row['high']), float(row['low']),
            float(row['close']), float(row['volume']),
            TICKER, d
        ))
        updated += cur.rowcount
    conn.commit()
    print(f"  gold.daily_ohlcv — {updated} rows updated")
    return updated


def recompute_and_update_adx14(conn, dates: list):
    """
    Fetch full SPY OHLCV history, recompute ADX14,
    UPDATE gold.regime_features for ALL dates with NULL adx14
    (not just the originally identified missing dates).
    """
    cur = conn.cursor()

    # Fetch all SPY OHLCV from DB (we need contiguous history for ADX)
    cur.execute("""
        SELECT date, high, low, close
        FROM gold.daily_ohlcv
        WHERE ticker = %s
        ORDER BY date
    """, (TICKER,))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=['date', 'high', 'low', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    for col in ['high', 'low', 'close']:
        df[col] = df[col].astype(float)

    # Check for remaining NULLs in the computation window
    null_mask = df[['high', 'low', 'close']].isna().any(axis=1)
    if null_mask.any():
        null_dates = df.index[null_mask].strftime('%Y-%m-%d').tolist()
        print(f"  ⚠️  Remaining NULL OHLCV dates: {null_dates}")
        df = df.dropna(subset=['high', 'low', 'close'])

    print(f"  Computing ADX14 on {len(df)} contiguous bars ...")
    df['adx14'] = compute_adx14(df)

    # Find ALL dates in regime_features with NULL or NaN adx14
    # Note: NaN may be stored as string 'NaN' (from pandas) or IEEE 754 NaN
    cur.execute("""
        SELECT date FROM gold.regime_features
        WHERE adx14 IS NULL OR adx14::text = 'NaN' OR adx14 <> adx14
        ORDER BY date
    """)
    null_dates = [str(r[0]) for r in cur.fetchall()]
    print(f"  Found {len(null_dates)} dates with NULL adx14 in regime_features")

    # Update regime_features for all NULL dates
    updated = 0
    before_after = []
    for d in null_dates:
        ts = pd.Timestamp(d)
        if ts not in df.index or pd.isna(df.loc[ts, 'adx14']):
            print(f"  ⚠️  ADX14 not computable for {d} (insufficient history or missing data)")
            continue

        cur.execute("SELECT adx14 FROM gold.regime_features WHERE date = %s", (d,))
        before_row = cur.fetchone()
        before_val = before_row[0] if before_row else None
        new_adx = float(df.loc[ts, 'adx14'])

        cur.execute("""
            UPDATE gold.regime_features
            SET adx14 = %s,
                adx_hurst_cross = adx14 * hurst_30,
                computed_at = NOW()
            WHERE date = %s
        """, (new_adx, d))
        updated += cur.rowcount
        before_after.append((d, before_val, new_adx))

    conn.commit()
    print(f"  gold.regime_features — {updated} rows updated")
    return before_after


def run_fix(dry_run=False):
    print("=" * 60)
    print("ADX14 OHLCV Backfill — G6d")
    print("=" * 60)

    print(f"\n→ Step 1: Missing dates identified: {MISSING_DATES}")

    print("\n→ Step 2: Fetch yfinance OHLCV ...")
    yf_df = fetch_yfinance_ohlcv(MISSING_DATES)
    print(f"  Fetched {len(yf_df)} rows from yfinance")

    conn = get_connection()

    if dry_run:
        print("\n  DRY RUN — preview updates:")
        for d in MISSING_DATES:
            ts = pd.Timestamp(d)
            if ts in yf_df.index:
                row = yf_df.loc[ts]
                print(f"    {d}: high={row['high']:.2f} low={row['low']:.2f} close={row['close']:.2f} vol={row['volume']:.0f}")
        print("  Skipping DB updates.")
        conn.close()
        return

    print("\n→ Step 3: Update gold.daily_ohlcv ...")
    update_gold_ohlcv(conn, yf_df, MISSING_DATES)

    print("\n→ Step 4: Recompute ADX14 ...")
    before_after = recompute_and_update_adx14(conn, MISSING_DATES)

    print("\n→ Step 5: Before/After ADX14 values ...")
    print(f"  {'Date':<12} {'Before':<12} {'After':<12}")
    for d, before, after in before_after:
        b_str = f"{before:.4f}" if before is not None else "NULL"
        print(f"  {d:<12} {b_str:<12} {after:.4f}")

    # Validation
    print("\n→ Step 6: Validation ...")
    cur = conn.cursor()
    for d in MISSING_DATES:
        cur.execute("SELECT adx14 FROM gold.regime_features WHERE date = %s", (d,))
        row = cur.fetchone()
        val = row[0] if row else None
        if val is None:
            print(f"  ❌ {d}: adx14 still NULL")
        elif not (0 <= val <= 100):
            print(f"  ❌ {d}: adx14={val:.4f} out of range [0,100]")
        else:
            status = "✅"
            if val > 25:
                status += " (trending)"
            elif val < 20:
                status += " (non-trending)"
            print(f"  {status} {d}: adx14={val:.4f}")

    conn.close()
    print("\n" + "=" * 60)
    print("✅ ADX14 backfill complete")
    print("=" * 60)


if __name__ == "__main__":
    dry = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    run_fix(dry_run=dry)
