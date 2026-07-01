#!/usr/bin/env python3
"""
HMM Backfill — Goal G5d
=======================
Backfill gold.hmm_regime_states and gold.regime_label for the gap period
2026-04-16 → 2026-05-19 (~25 business days).

Procedure:
  1. Load serialized HMM model (trained on 2026-04-15, 756 rows).
  2. Load gap rows from gold.regime_features.
  3. Forward-fill adx14 + adx_hurst_cross from last known value (2026-04-15)
     because SPY high/low OHLCV is missing for some gap dates, breaking ADX.
  4. Run HMM inference (NO retrain — avoids lookahead bias).
  5. Pull severity from gold.macro_event_flags for correct two-tier event handling.
  6. Apply regime_label override logic using the canonical assign_regime() from
     regime.regime_rules (EVENT severity>=2 → FLAT → TREND → MEAN_REV → CARRY → HMM).
  7. Idempotent UPSERT into gold.hmm_regime_states + gold.regime_label.

adx14 NULL handling:
  - adx14 is NULL for all 22 gap rows due to missing SPY high/low in gold.daily_ohlcv.
  - We forward-fill from the last known value (2026-04-15: 28.46) and recompute
    adx_hurst_cross = adx14 * hurst_30.
  - This preserves model consistency (same 6 features as training) at the cost
    of slightly stale ADX readings. Documented in README.
"""
import sys, os

# Resolve workspace path robustly against shadow filesystem split-brain
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')
REGIME_DIR = os.path.join(WORKSPACE, 'regime')

sys.path.insert(0, WORKSPACE)
sys.path.insert(0, SHARED)
sys.path.insert(0, REGIME_DIR)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from datetime import date

import numpy as np
import pandas as pd
import joblib

# Import canonical regime logic
from regime_rules import assign_regime, STRATEGY_MAP, VALID_REGIMES


# ── Constants ─────────────────────────────────────────────────────────────────

MODEL_PATH = os.path.join(REGIME_DIR, 'hmm_model.pkl')
FEATURES = ["adx14", "hurst_30", "rv5d", "vix_z60", "adx_hurst_cross", "rv5d_change"]
GAP_START = "2026-04-16"
GAP_END = "2026-05-19"


def load_model():
    """Load serialized HMM + scaler + label_map."""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Model not found at {MODEL_PATH}")
    payload = joblib.load(MODEL_PATH)
    for key in ("model", "scaler", "label_map", "trained_on", "n_rows", "features"):
        if key not in payload:
            raise ValueError(f"Serialized model missing key: {key}")
    return payload


def load_gap_features(conn):
    """Load regime_features + macro_event_flags severity for the gap period."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT r.date,
               r.adx14, r.hurst_30, r.rv5d, r.vix_z60,
               r.adx_hurst_cross, r.rv5d_change,
               r.rv_iv_ratio, r.event_flag, r.funding_z,
               CASE m.severity
                   WHEN 'heavy' THEN 3
                   WHEN 'medium' THEN 2
                   WHEN 'light' THEN 1
                   ELSE 0
               END as severity
        FROM gold.regime_features r
        LEFT JOIN gold.macro_event_flags m ON r.date = m.date
        WHERE r.date BETWEEN %s AND %s
        ORDER BY r.date
    """, (GAP_START, GAP_END))
    rows = cur.fetchall()
    cols = ['date'] + FEATURES + ['rv_iv_ratio', 'event_flag', 'funding_z', 'severity']
    df = pd.DataFrame(rows, columns=cols)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    for col in FEATURES + ['rv_iv_ratio', 'funding_z']:
        df[col] = df[col].astype(float)
    df['event_flag'] = df['event_flag'].fillna(0).astype(int)
    df['severity'] = df['severity'].fillna(0).astype(int)
    return df


def load_last_known_adx14(conn):
    """Get the last non-NULL adx14 before the gap."""
    cur = conn.cursor()
    cur.execute("""
        SELECT date, adx14, hurst_30
        FROM gold.regime_features
        WHERE date < %s AND adx14 IS NOT NULL
        ORDER BY date DESC
        LIMIT 1
    """, (GAP_START,))
    row = cur.fetchone()
    if row is None:
        raise ValueError("No non-NULL adx14 found before gap start")
    return float(row[1]), float(row[2])


def fill_adx14(df, last_adx14, last_hurst):
    """Forward-fill adx14 and recompute adx_hurst_cross."""
    df = df.copy()
    df['adx14'] = df['adx14'].fillna(last_adx14)
    df['adx_hurst_cross'] = df.apply(
        lambda r: r['adx14'] * (r['hurst_30'] if pd.notna(r['hurst_30']) else last_hurst),
        axis=1
    )
    return df


def run_inference(df, payload):
    """Run HMM inference on gap rows. Returns DataFrame with hmm_state, hmm_label, confidence."""
    model = payload['model']
    scaler = payload['scaler']
    label_map = payload['label_map']

    X = df[FEATURES].values
    if np.isnan(X).any():
        nan_cols = [c for c in FEATURES if df[c].isna().any()]
        raise ValueError(f"NaN still present in features after fill: {nan_cols}")

    X_scaled = scaler.transform(X)
    states = model.predict(X_scaled)
    posteriors = model.predict_proba(X_scaled)
    confidence = posteriors.max(axis=1)

    df['hmm_state'] = states
    df['hmm_label'] = df['hmm_state'].map(label_map)
    df['confidence'] = confidence
    return df


def build_override_flag(df):
    """Compute override_used flag matching regime_rules.py logic exactly."""
    df['override_used'] = (
        (df['event_flag'] == 1) |
        (df['vix_z60'] > 2.5) |
        (
            (df['adx14'] > 22) & (df['hurst_30'] > 0.55) & (df['rv5d_change'] > 0)
        ) |
        (
            (df['adx14'] < 22) & (df['rv5d_change'] < 0) & (df['vix_z60'] < 0.5)
        ) |
        (
            (df['rv_iv_ratio'] < 0.80) & (df['vix_z60'] < 0)
        )
    )
    return df


def insert_hmm_regime_states(conn, df):
    """Idempotent UPSERT into gold.hmm_regime_states."""
    cur = conn.cursor()
    inserted = 0
    for idx, row in df.reset_index().iterrows():
        cur.execute("""
            INSERT INTO gold.hmm_regime_states
                (date, hmm_state, hmm_label, confidence, computed_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (date) DO UPDATE SET
                hmm_state = EXCLUDED.hmm_state,
                hmm_label = EXCLUDED.hmm_label,
                confidence = EXCLUDED.confidence,
                computed_at = NOW()
        """, (row['date'], int(row['hmm_state']), row['hmm_label'], float(row['confidence'])))
        inserted += 1
    conn.commit()
    print(f"  gold.hmm_regime_states — {inserted} rows upserted")
    return inserted


def insert_regime_label(conn, df):
    """Idempotent UPSERT into gold.regime_label with correct severity."""
    cur = conn.cursor()
    inserted = 0
    for idx, row in df.reset_index().iterrows():
        cur.execute("""
            INSERT INTO gold.regime_label
                (date, regime, hmm_label, override_used, confidence, severity, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (date) DO UPDATE SET
                regime = EXCLUDED.regime,
                hmm_label = EXCLUDED.hmm_label,
                override_used = EXCLUDED.override_used,
                confidence = EXCLUDED.confidence,
                severity = EXCLUDED.severity,
                computed_at = NOW()
        """, (
            row['date'], row['regime'], row['hmm_label'],
            bool(row['override_used']), float(row['confidence']),
            int(row['severity']) if pd.notna(row['severity']) else 0
        ))
        inserted += 1
    conn.commit()
    print(f"  gold.regime_label — {inserted} rows upserted")
    return inserted


def run_backfill(dry_run=False):
    """Main backfill procedure."""
    print("=" * 60)
    print("HMM Backfill — G5d")
    print("=" * 60)

    # ── 1. Load model ───────────────────────────────────────────────────────────
    print("\n→ Step 1: Load serialized HMM model...")
    payload = load_model()
    print(f"  Model trained on: {payload['trained_on']} ({payload['n_rows']} rows)")
    print(f"  Features: {payload['features']}")
    print(f"  Label map: {payload['label_map']}")

    # ── 2. Load gap features ────────────────────────────────────────────────────
    print(f"\n→ Step 2: Load gap features ({GAP_START} → {GAP_END})...")
    conn = get_connection()
    df = load_gap_features(conn)
    print(f"  Rows loaded: {len(df)}")

    # Check for NULL adx14
    null_adx = df['adx14'].isna().sum()
    if null_adx > 0:
        print(f"  ⚠️  adx14 NULL count: {null_adx} of {len(df)}")
        last_adx14, last_hurst = load_last_known_adx14(conn)
        print(f"  Last known adx14: {last_adx14:.4f} (from pre-gap date)")
        df = fill_adx14(df, last_adx14, last_hurst)
        print(f"  Forward-filled adx14 + recomputed adx_hurst_cross")
    else:
        print(f"  adx14: no NULLs")

    # ── 3. Run HMM inference ────────────────────────────────────────────────────
    print("\n→ Step 3: HMM inference (no retrain)...")
    df = run_inference(df, payload)
    print(f"  HMM states predicted: {df['hmm_state'].nunique()} unique")
    hmm_counts = df['hmm_label'].value_counts().to_dict()
    print(f"  HMM labels: {hmm_counts}")

    # ── 4. Apply regime overrides ───────────────────────────────────────────────
    print("\n→ Step 4: Apply regime override logic (canonical regime_rules.py)...")
    df['regime'] = df.apply(assign_regime, axis=1)
    df = build_override_flag(df)
    regime_counts = df['regime'].value_counts().to_dict()
    print(f"  Final regimes: {regime_counts}")
    override_pct = df['override_used'].mean() * 100
    print(f"  Override used: {override_pct:.1f}% of gap days")

    # ── 5. Insert ───────────────────────────────────────────────────────────────
    print("\n→ Step 5: Upsert into gold tables...")
    if dry_run:
        print("  DRY RUN — skipping INSERT")
        print(f"  Would upsert {len(df)} rows into hmm_regime_states")
        print(f"  Would upsert {len(df)} rows into regime_label")
        print("\n  Preview (last 5 rows):")
        print(df[['hmm_state', 'hmm_label', 'regime', 'override_used', 'confidence', 'severity']].tail())
    else:
        insert_hmm_regime_states(conn, df)
        insert_regime_label(conn, df)

    # ── 6. Verify ───────────────────────────────────────────────────────────────
    print("\n→ Step 6: Verification...")
    cur = conn.cursor()
    cur.execute("SELECT MAX(date) FROM gold.hmm_regime_states")
    hmm_max = cur.fetchone()[0]
    cur.execute("SELECT MAX(date) FROM gold.regime_label")
    label_max = cur.fetchone()[0]
    print(f"  gold.hmm_regime_states max date: {hmm_max}")
    print(f"  gold.regime_label max date: {label_max}")

    cur.execute("""
        SELECT COUNT(*) FROM gold.hmm_regime_states
        WHERE date BETWEEN %s AND %s
    """, (GAP_START, GAP_END))
    hmm_gap_rows = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM gold.regime_label
        WHERE date BETWEEN %s AND %s
    """, (GAP_START, GAP_END))
    label_gap_rows = cur.fetchone()[0]
    print(f"  Rows in gap window — hmm_regime_states: {hmm_gap_rows}, regime_label: {label_gap_rows}")

    # Label distribution in gap
    cur.execute("""
        SELECT regime, COUNT(*) FROM gold.regime_label
        WHERE date BETWEEN %s AND %s
        GROUP BY regime ORDER BY COUNT(*) DESC
    """, (GAP_START, GAP_END))
    print(f"\n  Gap label distribution:")
    for r in cur.fetchall():
        print(f"    {r[0]}: {r[1]}")

    # Latest regime
    cur.execute("""
        SELECT date, regime, hmm_label, override_used, confidence, severity
        FROM gold.regime_label
        ORDER BY date DESC
        LIMIT 1
    """)
    latest = cur.fetchone()
    print(f"\n  Latest regime_label:")
    print(f"    Date: {latest[0]}")
    print(f"    Regime: {latest[1]}")
    print(f"    HMM label: {latest[2]}")
    print(f"    Override used: {latest[3]}")
    print(f"    Confidence: {latest[4]:.4f}")
    print(f"    Severity: {latest[5]}")

    conn.close()

    print("\n" + "=" * 60)
    print("✅ HMM backfill complete")
    print("=" * 60)
    return df


if __name__ == "__main__":
    dry = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    run_backfill(dry_run=dry)
