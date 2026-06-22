#!/usr/bin/env python3
"""
Test suite for COT coverage expansion (GC / CL / ES).

Run:  python test_cot_expand.py

Checks:
  1. Row counts — each ticker has ≥ 52 weekly records (minimum for z-score)
  2. Z-score sanity — cot_z is populated, finite, and within reasonable bounds
  3. No duplicate PK violations — (instrument, date) is unique per ticker
  4. Sentiment consistency — sentiment maps correctly from cot_z thresholds
  5. net_noncomm arithmetic — net = long - short for all rows
  6. Structural pair — cot_z correlates with net_noncomm (G4 block validation)
  7. Generator compatibility — DISTINCT tickers query returns new tickers
"""
import sys, os, math
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

import pandas as pd

TICKERS = ['GC', 'CL', 'ES']
MIN_WEEKS = 52


def get_ticker_df(ticker: str) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("""
        SELECT date, report_date, noncomm_long, noncomm_short,
               net_noncomm, cot_z, sentiment, signal_flag
        FROM gold.cot_sentiment
        WHERE instrument = %s
        ORDER BY date
    """, conn, params=(ticker,))
    conn.close()
    return df


def test_row_counts():
    print("\n1. ROW COUNTS")
    ok = True
    for t in TICKERS:
        df = get_ticker_df(t)
        # Count unique report_dates (true weekly observations)
        n_weeks = df['report_date'].nunique()
        n_rows = len(df)
        print(f"   {t}: {n_rows} daily rows, {n_weeks} unique report_dates")
        if n_weeks < MIN_WEEKS:
            print(f"   ❌ FAIL: {t} has only {n_weeks} weeks (need {MIN_WEEKS})")
            ok = False
        else:
            print(f"   ✅ PASS: {t} has sufficient history")
    return ok


def test_zscore_sanity():
    print("\n2. Z-SCORE SANITY")
    ok = True
    for t in TICKERS:
        df = get_ticker_df(t)
        z = df['cot_z'].dropna()
        if len(z) == 0:
            print(f"   ❌ FAIL: {t} cot_z is all NULL")
            ok = False
            continue
        if z.isin([math.inf, -math.inf]).any():
            print(f"   ❌ FAIL: {t} cot_z contains Inf")
            ok = False
            continue
        z_min, z_max = z.min(), z.max()
        print(f"   {t}: cot_z range [{z_min:.3f}, {z_max:.3f}], n={len(z)}")
        if abs(z_min) > 10 or abs(z_max) > 10:
            print(f"   ⚠️  WARN: {t} cot_z exceeds ±10 — possible outlier")
        else:
            print(f"   ✅ PASS: {t} cot_z within bounds")
    return ok


def test_no_duplicate_pks():
    print("\n3. NO DUPLICATE PKs")
    conn = get_connection()
    cur = conn.cursor()
    ok = True
    for t in TICKERS:
        cur.execute("""
            SELECT date, COUNT(*) AS cnt
            FROM gold.cot_sentiment
            WHERE instrument = %s
            GROUP BY date
            HAVING COUNT(*) > 1
        """, (t,))
        dups = cur.fetchall()
        if dups:
            print(f"   ❌ FAIL: {t} has {len(dups)} duplicate dates")
            ok = False
        else:
            print(f"   ✅ PASS: {t} no duplicate (instrument, date)")
    conn.close()
    return ok


def test_sentiment_consistency():
    print("\n4. SENTIMENT CONSISTENCY")
    ok = True
    for t in TICKERS:
        df = get_ticker_df(t)
        df_z = df.dropna(subset=['cot_z'])
        mismatches = []
        for _, row in df_z.iterrows():
            expected = 'bearish' if row['cot_z'] > 1.0 else ('bullish' if row['cot_z'] < -1.0 else 'neutral')
            if row['sentiment'] != expected:
                mismatches.append((row['date'], row['cot_z'], row['sentiment'], expected))
        if mismatches:
            print(f"   ❌ FAIL: {t} {len(mismatches)} sentiment mismatches (first 3: {mismatches[:3]})")
            ok = False
        else:
            print(f"   ✅ PASS: {t} sentiment matches cot_z thresholds")
    return ok


def test_net_arithmetic():
    print("\n5. NET_NONCOMM ARITHMETIC")
    ok = True
    for t in TICKERS:
        df = get_ticker_df(t)
        bad = df[df['net_noncomm'] != (df['noncomm_long'] - df['noncomm_short'])]
        if len(bad) > 0:
            print(f"   ❌ FAIL: {t} {len(bad)} rows with net ≠ long - short")
            ok = False
        else:
            print(f"   ✅ PASS: {t} net_noncomm = long - short for all rows")
    return ok


def test_structural_pair():
    print("\n6. STRUCTURAL PAIR (cot_z ↔ net_noncomm deviation)")
    ok = True
    for t in TICKERS:
        df = get_ticker_df(t).dropna(subset=['cot_z', 'net_noncomm'])
        if len(df) < 2:
            print(f"   ❌ FAIL: {t} insufficient data for correlation")
            ok = False
            continue
        # Compute deviation from rolling mean (what z-score is based on)
        rolling_mean = df['net_noncomm'].rolling(window=364, min_periods=364).mean()
        deviation = df['net_noncomm'] - rolling_mean
        corr = df['cot_z'].corr(deviation)
        print(f"   {t}: corr(cot_z, deviation_from_rolling_mean) = {corr:.4f}")
        if pd.isna(corr) or abs(corr) < 0.5:
            print(f"   ❌ FAIL: {t} correlation too weak — structural pair broken")
            ok = False
        else:
            print(f"   ✅ PASS: {t} strong structural correlation")
    return ok


def test_generator_compatibility():
    print("\n7. GENERATOR COMPATIBILITY")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT instrument FROM gold.cot_sentiment ORDER BY instrument")
    tickers_in_db = [r[0] for r in cur.fetchall()]
    conn.close()
    print(f"   Tickers in gold.cot_sentiment: {tickers_in_db}")
    missing = [t for t in TICKERS if t not in tickers_in_db]
    if missing:
        print(f"   ❌ FAIL: missing tickers {missing}")
        return False
    print(f"   ✅ PASS: all target tickers present")
    return True


def main():
    print("=" * 60)
    print("COT COVERAGE EXPANSION — TEST SUITE")
    print("=" * 60)
    results = []
    results.append(("Row counts", test_row_counts()))
    results.append(("Z-score sanity", test_zscore_sanity()))
    results.append(("No duplicate PKs", test_no_duplicate_pks()))
    results.append(("Sentiment consistency", test_sentiment_consistency()))
    results.append(("Net arithmetic", test_net_arithmetic()))
    results.append(("Structural pair", test_structural_pair()))
    results.append(("Generator compatibility", test_generator_compatibility()))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"   {status}: {name}")
        if not ok:
            all_pass = False
    print("=" * 60)
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
