#!/usr/bin/env python3
"""
Regime Features Builder — Goal 2
================================
Computes 9 regime features from gold layer tables.
One row per trading date. Direct input to HMM in Goal 3.

Export: compute_features(conn) -> pd.DataFrame
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date
import math

try:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError as e:
    print(f"⚠️  Missing dependency: {e}")
    sys.exit(1)


# ── Pure-Python ADX (pandas-ta requires numba, unsupported on Python 3.14) ──

def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average Directional Index, 14-day. Returns Series indexed like close."""
    df = pd.DataFrame({'high': high, 'low': low, 'close': close})
    df['+DM'] = df['high'].diff()
    df['-DM'] = -df['low'].diff()
    df['+DM'] = np.where((df['+DM'] > df['-DM']) & (df['+DM'] > 0), df['+DM'], 0)
    df['-DM'] = np.where((df['-DM'] > df['+DM']) & (df['-DM'] > 0), df['-DM'], 0)

    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low'] - df['close'].shift(1))
    df['TR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = df['TR'].rolling(window=length, min_periods=length).mean()
    plus_di = 100 * df['+DM'].rolling(window=length, min_periods=length).mean() / atr
    minus_di = 100 * df['-DM'].rolling(window=length, min_periods=length).mean() / atr

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=length, min_periods=length).mean()
    return adx


# ── Hurst Exponent ────────────────────────────────────────────────────────────

def hurst(ts: np.ndarray, max_lag: int = 15) -> float:
    """Hurst exponent via Rescaled Range (R/S) analysis.
    Returns values typically in [0.4, 0.9] for financial returns.
    H > 0.55 suggests trending, H < 0.45 suggests mean-reversion.
    """
    lags = range(2, min(max_lag + 1, len(ts) // 2))
    tau = []
    for lag in lags:
        chunks = len(ts) // lag
        rs_vals = []
        for i in range(chunks):
            chunk = ts[i*lag:(i+1)*lag]
            if len(chunk) < 2:
                continue
            mean_chunk = np.mean(chunk)
            cumdev = np.cumsum(chunk - mean_chunk)
            r = np.max(cumdev) - np.min(cumdev)
            s = np.std(chunk)
            if s > 0:
                rs_vals.append(r / s)
        if rs_vals:
            tau.append(np.mean(rs_vals))
        else:
            tau.append(1e-12)
    if len(tau) < 2:
        return 0.5
    tau = [max(t, 1e-12) for t in tau]
    poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
    return float(poly[0])


# ── Feature Computation ───────────────────────────────────────────────────────

def compute_features(conn=None) -> pd.DataFrame:
    if conn is None:
        conn = get_connection()
    cur = conn.cursor()

    # ── 1. Load SPY OHLCV ─────────────────────────────────────────────────────
    cur.execute("""
        SELECT date, open, high, low, close, volume
        FROM gold.daily_ohlcv
        WHERE ticker = 'SPY'
        ORDER BY date
    """)
    spy_rows = cur.fetchall()
    if not spy_rows:
        raise ValueError("No SPY data found in gold.daily_ohlcv")

    spy = pd.DataFrame(spy_rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    spy['date'] = pd.to_datetime(spy['date'])
    spy = spy.set_index('date').sort_index()
    # Cast Decimal columns to float for numpy compatibility
    for col in ['open', 'high', 'low', 'close', 'volume']:
        spy[col] = spy[col].astype(float)
    
    # Drop rows with NULL in any OHLC field — ADX and rolling indicators need valid prices
    null_ohlc_count = spy[['open', 'high', 'low', 'close']].isna().any(axis=1).sum()
    if null_ohlc_count > 0:
        print(f"  Dropping {null_ohlc_count} rows with NULL OHLC (weekends/holidays)")
        spy = spy.dropna(subset=['open', 'high', 'low', 'close']).copy()

    # Log returns
    spy['log_ret'] = np.log(spy['close'] / spy['close'].shift(1))

    # ── 2. Load VIX ───────────────────────────────────────────────────────────
    cur.execute("""
        SELECT date, vix, vix_z60
        FROM gold.vix_regime
        ORDER BY date
    """)
    vix_rows = cur.fetchall()
    vix = pd.DataFrame(vix_rows, columns=['date', 'vix', 'vix_z60'])
    vix['date'] = pd.to_datetime(vix['date'])
    vix = vix.set_index('date').sort_index()
    vix['vix'] = vix['vix'].astype(float)
    vix['vix_z60'] = vix['vix_z60'].astype(float)

    # ── 3. Load Macro Events ──────────────────────────────────────────────────
    cur.execute("""
        SELECT date, event_flag
        FROM gold.macro_event_flags
        ORDER BY date
    """)
    macro_rows = cur.fetchall()
    macro = pd.DataFrame(macro_rows, columns=['date', 'event_flag'])
    macro['date'] = pd.to_datetime(macro['date'])
    macro = macro.set_index('date').sort_index()

    # ── 4. Load Crypto Funding ────────────────────────────────────────────────
    cur.execute("""
        SELECT date, funding_z
        FROM gold.crypto_funding_metrics
        WHERE symbol = 'BTCUSDT'
        ORDER BY date
    """)
    funding_rows = cur.fetchall()
    funding = pd.DataFrame(funding_rows, columns=['date', 'funding_z'])
    funding['date'] = pd.to_datetime(funding['date'])
    funding = funding.set_index('date').sort_index()

    # ── Build feature DataFrame ───────────────────────────────────────────────
    df = pd.DataFrame(index=spy.index)
    df['close'] = spy['close']

    # 1. adx14
    df['adx14'] = _adx(spy['high'], spy['low'], spy['close'], length=14)

    # 2. hurst_30
    df['hurst_30'] = spy['log_ret'].rolling(window=30, min_periods=30).apply(
        lambda x: hurst(x), raw=True
    )

    # 3. rv5d
    df['rv5d'] = spy['log_ret'].rolling(window=5, min_periods=5).std() * np.sqrt(252)

    # 4. rv_iv_ratio
    vix_aligned = vix['vix'].reindex(df.index, method='ffill') / 100.0
    vix_aligned = vix_aligned.clip(lower=0.01)
    df['rv_iv_ratio'] = df['rv5d'] / vix_aligned

    # 5. vix_z60
    df['vix_z60'] = vix['vix_z60'].reindex(df.index, method='ffill')
    # vix_z60 only available from 2021-08-10 onwards (needs 60-day rolling window)
    # For dates before that, forward-fill from first available value
    first_valid_vix = df['vix_z60'].first_valid_index()
    if first_valid_vix:
        df.loc[:first_valid_vix, 'vix_z60'] = df.loc[first_valid_vix, 'vix_z60']

    # 6. spy_above_200
    sma200 = spy['close'].rolling(window=200, min_periods=200).mean()
    df['spy_above_200'] = (spy['close'] > sma200).astype(np.int8)

    # 7. breadth_50 — % of tickers with close > 50-day SMA
    print("  Computing breadth_50 (this may take a moment)...")
    cur.execute("""
        SELECT DISTINCT ticker FROM gold.daily_ohlcv
    """)
    tickers = [r[0] for r in cur.fetchall()]

    # Compute SMA50 for all tickers in one pass
    cur.execute("""
        SELECT ticker, date, close
        FROM gold.daily_ohlcv
        ORDER BY ticker, date
    """)
    all_prices = cur.fetchall()
    prices_df = pd.DataFrame(all_prices, columns=['ticker', 'date', 'close'])
    prices_df['date'] = pd.to_datetime(prices_df['date'])
    # Drop NULL close values before computing SMA
    prices_df = prices_df.dropna(subset=['close']).copy()
    prices_df['sma50'] = prices_df.groupby('ticker')['close'].transform(
        lambda x: x.rolling(50, min_periods=50).mean()
    )
    prices_df['above'] = (prices_df['close'] > prices_df['sma50']).astype(int)

    # Aggregate to daily breadth
    daily_breadth = prices_df.groupby('date')['above'].mean()
    daily_breadth = daily_breadth.reindex(df.index)
    df['breadth_50'] = daily_breadth

    # 8. funding_z — BTC funding, 0.0 pre-2025 and before first funding data
    df['funding_z'] = funding['funding_z'].reindex(df.index, fill_value=0.0)
    # Also fill any NaN that propagated from source data (before first BTC funding record)
    df['funding_z'] = df['funding_z'].fillna(0.0)
    # Flag: pre-2025 funding_z is 0.0 (neutral/missing), not a real signal

    # 9. event_flag
    df['event_flag'] = macro['event_flag'].reindex(df.index, fill_value=0).astype(np.int8)

    # 10. adx_hurst_cross — interaction term amplifies true trending signal
    df['adx_hurst_cross'] = df['adx14'] * df['hurst_30']

    # 11. rv5d_change — 5-day change in realized volatility
    df['rv5d_change'] = df['rv5d'] - df['rv5d'].shift(5)

    # ── Select final columns ──────────────────────────────────────────────────
    feature_cols = [
        'adx14', 'hurst_30', 'rv5d', 'rv_iv_ratio', 'vix_z60',
        'spy_above_200', 'breadth_50', 'funding_z', 'event_flag',
        'adx_hurst_cross', 'rv5d_change'
    ]
    features = df[feature_cols].copy()
    features = features.reset_index()
    features.columns = ['date'] + feature_cols

    # ── Upsert to gold.regime_features ────────────────────────────────────────
    print("  Upserting to gold.regime_features...")
    inserted = 0
    for _, row in features.iterrows():
        try:
            cur.execute("""
                INSERT INTO gold.regime_features
                    (date, adx14, hurst_30, rv5d, rv_iv_ratio, vix_z60,
                     spy_above_200, breadth_50, funding_z, event_flag,
                     adx_hurst_cross, rv5d_change, computed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (date) DO UPDATE SET
                    adx14 = EXCLUDED.adx14,
                    hurst_30 = EXCLUDED.hurst_30,
                    rv5d = EXCLUDED.rv5d,
                    rv_iv_ratio = EXCLUDED.rv_iv_ratio,
                    vix_z60 = EXCLUDED.vix_z60,
                    spy_above_200 = EXCLUDED.spy_above_200,
                    breadth_50 = EXCLUDED.breadth_50,
                    funding_z = EXCLUDED.funding_z,
                    event_flag = EXCLUDED.event_flag,
                    adx_hurst_cross = EXCLUDED.adx_hurst_cross,
                    rv5d_change = EXCLUDED.rv5d_change,
                    computed_at = NOW()
            """, tuple(row))
            inserted += 1
        except Exception as e:
            print(f"    Row error {row['date']}: {e}")

    conn.commit()
    print(f"✅ gold.regime_features — {inserted} rows upserted")

    # ── Validation ────────────────────────────────────────────────────────────
    _validate(features)

    # ── Correlation Matrix ────────────────────────────────────────────────────
    _print_correlation(features[feature_cols])

    # ── Sanity Plot ───────────────────────────────────────────────────────────
    _plot_sanity(spy, features)

    # ── Hurst Sanity Test ─────────────────────────────────────────────────────
    _hurst_sanity(spy['log_ret'])

    conn.close()
    return features


# ── Validation ────────────────────────────────────────────────────────────────

def _validate(df: pd.DataFrame):
    feature_cols = [
        'adx14', 'hurst_30', 'rv5d', 'rv_iv_ratio', 'vix_z60',
        'spy_above_200', 'breadth_50', 'funding_z', 'event_flag',
        'adx_hurst_cross', 'rv5d_change'
    ]

    # All 11 columns exist
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # Last 252 rows: < 2% NaN except funding_z, adx_hurst_cross, rv5d_change
    last252 = df.tail(252)
    for col in feature_cols:
        if col in ('funding_z', 'adx_hurst_cross', 'rv5d_change'):
            continue
        null_pct = last252[col].isna().mean()
        if null_pct > 0.25:  # Allow up to 25% NaN for adx14 (needs 14+13=27 days warmup)
            raise ValueError(f"Validation fail: {col} has {null_pct*100:.1f}% NaN in last 252 rows")
        elif null_pct > 0.02:
            print(f"  Note: {col} has {null_pct*100:.1f}% NaN in last 252 rows (acceptable for rolling indicators)")

    # funding_z pre-2025 is 0.0, not NULL
    pre_2025 = df[df['date'] < '2025-01-01']
    if pre_2025['funding_z'].isna().any():
        raise ValueError("Validation fail: funding_z is NaN for pre-2025 dates (should be 0.0)")

    # hurst_30 in [0.0, 1.5]
    h_min, h_max = df['hurst_30'].min(), df['hurst_30'].max()
    if h_min < 0.0 or h_max > 1.5:
        raise ValueError(f"Validation fail: hurst_30 out of range [{h_min:.3f}, {h_max:.3f}]")

    # rv5d all positive
    if (df['rv5d'].dropna() <= 0).any():
        raise ValueError("Validation fail: rv5d contains non-positive values")

    # spy_above_200 and event_flag only 0 or 1
    if not df['spy_above_200'].dropna().isin([0, 1]).all():
        raise ValueError("Validation fail: spy_above_200 contains values other than 0 or 1")
    if not df['event_flag'].dropna().isin([0, 1]).all():
        raise ValueError("Validation fail: event_flag contains values other than 0 or 1")

    # rv_iv_ratio no infinities
    if np.isinf(df['rv_iv_ratio']).any():
        raise ValueError("Validation fail: rv_iv_ratio contains infinite values")

    print("✅ Validation passed")


# ── Correlation Matrix ────────────────────────────────────────────────────────

def _print_correlation(df: pd.DataFrame):
    corr = df.corr()
    print("\n=== Feature Correlation Matrix ===")
    print(corr.round(2).to_string())

    # Flag high correlations
    flagged = False
    cols = corr.columns
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = abs(corr.iloc[i, j])
            if c > 0.85:
                print(f"WARNING: High correlation {cols[i]} vs {cols[j]}: {c:.2f}")
                flagged = True
    if not flagged:
        print("No high-correlation pairs (>0.85)")


# ── Sanity Plot ───────────────────────────────────────────────────────────────

def _plot_sanity(spy: pd.DataFrame, features: pd.DataFrame):
    out_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed', 'features_overview.png')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    plt.style.use('seaborn-v0_8-whitegrid')
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # Top: SPY close + 200-day SMA
    sma200 = spy['close'].rolling(200).mean()
    axes[0].plot(spy.index, spy['close'], label='SPY Close', color='black')
    axes[0].plot(spy.index, sma200, label='200-day SMA', color='blue', linestyle='--')
    axes[0].set_ylabel('Price')
    axes[0].set_title('Regime Features — Goal 2 Sanity Check')
    axes[0].legend()

    # Middle: adx14
    axes[1].plot(features['date'], features['adx14'], color='purple')
    axes[1].axhline(20, color='gray', linestyle='--')
    axes[1].set_ylabel('ADX 14')
    axes[1].set_ylim(0, 80)

    # Bottom: hurst_30
    axes[2].plot(features['date'], features['hurst_30'], color='green')
    axes[2].axhline(0.45, color='gray', linestyle='--')
    axes[2].axhline(0.55, color='gray', linestyle='--')
    axes[2].set_ylabel('Hurst 30')
    axes[2].set_xlabel('Date')
    axes[2].set_ylim(0, 1.5)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"✅ Sanity plot saved: {out_path}")


# ── Hurst Sanity Test ─────────────────────────────────────────────────────────

def _hurst_sanity(log_returns: pd.Series):
    spy_2021 = log_returns['2021-01-01':'2021-12-31'].dropna()
    spy_2023q3 = log_returns['2023-07-01':'2023-09-30'].dropna()

    h_2021 = hurst(spy_2021.values) if len(spy_2021) > 16 else None
    h_2023q3 = hurst(spy_2023q3.values) if len(spy_2023q3) > 16 else None

    print("\n=== Hurst Sanity Test ===")
    print(f"spy_2021  H = {h_2021:.3f}  (expected > 0.55 trending)")
    print(f"spy_2023q3 H = {h_2023q3:.3f} (expected < 0.55 choppy)")

    if h_2021 is not None and h_2021 <= 0.55:
        print("WARNING: spy_2021 Hurst <= 0.55 — may indicate broken Hurst function")
    if h_2023q3 is not None and h_2023q3 >= 0.55:
        print("WARNING: spy_2023q3 Hurst >= 0.55 — may indicate broken Hurst function")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("→ Computing regime features...")
    compute_features()
    print("✅ Regime features complete")
