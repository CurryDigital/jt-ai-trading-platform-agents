# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Funding Z-Score Fix — Goal G6b
==============================
Diagnoses and fixes NULL funding_z in gold.regime_features.

Root Causes Found:
  1. 2025-05-14: First day of BTCUSDT data in silver.funding_rates_daily.
     Only 1 observation → z-score requires >=2 days → legitimately NULL.
  2. 2026-02-18, 2026-02-19: Backfilled with days_back=90 on 2026-05-19/20.
     These were the first days of the fetched window → insufficient history
     for 30-day rolling z-score → NULL.

Fix Applied:
  - Recompute z-scores for ALL symbols in silver.funding_rates_daily using
    the FULL historical dataset (not just a 90-day fetched window).
  - For 2025-05-14 (first day ever): set funding_z = 0.0 (neutral placeholder).
  - Propagate corrected funding_z to gold.crypto_funding_metrics.
  - Propagate corrected funding_z to gold.regime_features.

adx14 Status:
  - adx14 NULL is a SEPARATE issue (missing SPY high/low in gold.daily_ohlcv).
  - Not fixed here — requires upstream OHLCV backfill.
  - Documented in README for G5d hmm_backfill.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date

import math


def diagnose(conn):
    """Print diagnostic summary."""
    cur = conn.cursor()
    print("=" * 60)
    print("Funding Z-Score Diagnosis")
    print("=" * 60)

    # NULL funding_z in regime_features
    cur.execute("""
        SELECT date, funding_z FROM gold.regime_features
        WHERE funding_z IS NULL
        ORDER BY date
    """)
    null_rows = cur.fetchall()
    print(f"\nNULL funding_z in gold.regime_features: {len(null_rows)} rows")
    for r in null_rows:
        print(f"  {r[0]}: {r[1]}")

    # NULL funding_z in crypto_funding_metrics (BTCUSDT)
    cur.execute("""
        SELECT date, symbol, funding_rate_8h, funding_z, n_obs
        FROM gold.crypto_funding_metrics
        WHERE funding_z IS NULL
        ORDER BY date, symbol
    """)
    null_crypto = cur.fetchall()
    print(f"\nNULL funding_z in gold.crypto_funding_metrics: {len(null_crypto)} rows")
    for r in null_crypto[:5]:
        print(f"  {r[0]} {r[1]}: rate={r[2]}, z={r[3]}, n_obs={r[4]}")

    # NULL funding_z in silver.funding_rates_daily (BTCUSDT)
    cur.execute("""
        SELECT date, symbol, funding_rate_8h, funding_z, n_obs
        FROM silver.funding_rates_daily
        WHERE funding_z IS NULL
        ORDER BY date, symbol
    """)
    null_silver = cur.fetchall()
    print(f"\nNULL funding_z in silver.funding_rates_daily: {len(null_silver)} rows")
    for r in null_silver[:5]:
        print(f"  {r[0]} {r[1]}: rate={r[2]}, z={r[3]}, n_obs={r[4]}")

    conn.close()
    return len(null_rows), len(null_crypto), len(null_silver)


def recompute_z_scores(conn):
    """
    Recompute 30-day rolling z-scores for ALL symbols in silver.funding_rates_daily
    using the full historical dataset per symbol.
    """
    cur = conn.cursor()
    print("\n" + "=" * 60)
    print("Recomputing Z-Scores")
    print("=" * 60)

    # Get all symbols
    cur.execute("SELECT DISTINCT symbol FROM silver.funding_rates_daily ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]
    print(f"Symbols to process: {len(symbols)}")

    updated_silver = 0
    updated_crypto = 0
    updated_regime = 0

    for symbol in symbols:
        # Load full history for this symbol
        cur.execute("""
            SELECT date, funding_rate_8h
            FROM silver.funding_rates_daily
            WHERE symbol = %s
            ORDER BY date
        """, (symbol,))
        rows = cur.fetchall()
        if len(rows) < 2:
            print(f"  {symbol}: only {len(rows)} rows — skipping")
            continue

        dates = [r[0] for r in rows]
        values = [float(r[1]) for r in rows]
        window = 30

        z_scores = []
        for i, val in enumerate(values):
            lo = max(0, i - window + 1)
            slice_vals = values[lo:i + 1]
            if len(slice_vals) < 2:
                z_scores.append(None)
                continue
            mu = sum(slice_vals) / len(slice_vals)
            sigma = math.sqrt(sum((x - mu) ** 2 for x in slice_vals) / len(slice_vals))
            z = (val - mu) / sigma if sigma > 0 else 0.0
            z_scores.append(z)

        # Update silver.funding_rates_daily
        for d, z in zip(dates, z_scores):
            z_rounded = round(z, 6) if z is not None else None
            cur.execute("""
                UPDATE silver.funding_rates_daily
                SET funding_z = %s
                WHERE symbol = %s AND date = %s
            """, (z_rounded, symbol, d))
            if cur.rowcount > 0:
                updated_silver += 1

        # Update gold.crypto_funding_metrics (same schema, may be a view or table)
        for d, z in zip(dates, z_scores):
            z_rounded = round(z, 6) if z is not None else None
            cur.execute("""
                UPDATE gold.crypto_funding_metrics
                SET funding_z = %s
                WHERE symbol = %s AND date = %s
            """, (z_rounded, symbol, d))
            if cur.rowcount > 0:
                updated_crypto += 1

    conn.commit()
    print(f"  silver.funding_rates_daily: {updated_silver} rows updated")
    print(f"  gold.crypto_funding_metrics: {updated_crypto} rows updated")
    return updated_silver, updated_crypto


def fix_first_day_nulls(conn):
    """
    For the very first day of each symbol (legitimately NULL z-score),
    set funding_z = 0.0 as a neutral placeholder.
    """
    cur = conn.cursor()
    print("\n" + "=" * 60)
    print("Fixing First-Day NULLs")
    print("=" * 60)

    # Find first day per symbol where funding_z IS NULL
    cur.execute("""
        SELECT symbol, MIN(date) as first_date
        FROM silver.funding_rates_daily
        WHERE funding_z IS NULL
        GROUP BY symbol
    """)
    first_days = cur.fetchall()
    print(f"First-day NULLs to fix: {len(first_days)} symbols")

    updated_silver = 0
    updated_crypto = 0
    updated_regime = 0

    for symbol, first_date in first_days:
        # silver
        cur.execute("""
            UPDATE silver.funding_rates_daily
            SET funding_z = 0.0
            WHERE symbol = %s AND date = %s AND funding_z IS NULL
        """, (symbol, first_date))
        updated_silver += cur.rowcount

        # gold.crypto_funding_metrics
        cur.execute("""
            UPDATE gold.crypto_funding_metrics
            SET funding_z = 0.0
            WHERE symbol = %s AND date = %s AND funding_z IS NULL
        """, (symbol, first_date))
        updated_crypto += cur.rowcount

    conn.commit()
    print(f"  silver.funding_rates_daily: {updated_silver} rows set to 0.0")
    print(f"  gold.crypto_funding_metrics: {updated_crypto} rows set to 0.0")
    return updated_silver, updated_crypto


def propagate_to_regime_features(conn):
    """
    Propagate corrected BTCUSDT funding_z to gold.regime_features.
    regime_features.funding_z comes from gold.crypto_funding_metrics WHERE symbol='BTCUSDT'.
    """
    cur = conn.cursor()
    print("\n" + "=" * 60)
    print("Propagating to gold.regime_features")
    print("=" * 60)

    cur.execute("""
        UPDATE gold.regime_features r
        SET funding_z = c.funding_z
        FROM gold.crypto_funding_metrics c
        WHERE r.date = c.date
          AND c.symbol = 'BTCUSDT'
          AND r.funding_z IS NULL
          AND c.funding_z IS NOT NULL
    """)
    updated = cur.rowcount
    conn.commit()
    print(f"  gold.regime_features: {updated} rows updated")
    return updated


def verify(conn):
    """Post-fix verification."""
    cur = conn.cursor()
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # Check remaining NULLs
    cur.execute("SELECT COUNT(*) FROM gold.regime_features WHERE funding_z IS NULL")
    regime_nulls = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM gold.crypto_funding_metrics WHERE funding_z IS NULL")
    crypto_nulls = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM silver.funding_rates_daily WHERE funding_z IS NULL")
    silver_nulls = cur.fetchone()[0]

    print(f"  Remaining NULL funding_z:")
    print(f"    gold.regime_features: {regime_nulls}")
    print(f"    gold.crypto_funding_metrics: {crypto_nulls}")
    print(f"    silver.funding_rates_daily: {silver_nulls}")

    # Show corrected values for the 3 known NULL dates
    cur.execute("""
        SELECT date, funding_z FROM gold.regime_features
        WHERE date IN ('2025-05-14', '2026-02-18', '2026-02-19')
        ORDER BY date
    """)
    print(f"\n  Corrected values:")
    for r in cur.fetchall():
        print(f"    {r[0]}: {r[1]}")

    return regime_nulls, crypto_nulls, silver_nulls


def run_fix():
    print("=" * 60)
    print("Funding Z-Score Fix — G6b")
    print("=" * 60)

    conn = get_connection()

    # Step 1: Diagnose
    diagnose(conn)
    conn = get_connection()  # reconnect after diagnose closes

    # Step 2: Recompute z-scores using full history
    recompute_z_scores(conn)

    # Step 3: Fix first-day NULLs (set to 0.0)
    fix_first_day_nulls(conn)

    # Step 4: Propagate to regime_features
    propagate_to_regime_features(conn)

    # Step 5: Verify
    regime_nulls, crypto_nulls, silver_nulls = verify(conn)

    conn.close()

    print("\n" + "=" * 60)
    if regime_nulls == 0 and crypto_nulls == 0 and silver_nulls == 0:
        print("✅ All funding_z NULLs resolved")
    else:
        print(f"⚠️  Remaining NULLs: regime={regime_nulls}, crypto={crypto_nulls}, silver={silver_nulls}")
    print("=" * 60)
    return regime_nulls, crypto_nulls, silver_nulls


if __name__ == "__main__":
    run_fix()
