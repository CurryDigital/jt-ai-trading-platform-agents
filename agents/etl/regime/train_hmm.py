#!/usr/bin/env python3
"""
Regime HMM Trainer — Goal 3
===========================
Train a 3-state Gaussian HMM on 4 features from gold.regime_features.
Serialize model + scaler + label map for daily inference.

Export:
    train_hmm(conn) -> tuple[GaussianHMM, pd.DataFrame]
    load_hmm()      -> GaussianHMM
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date

import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from hmmlearn.hmm import GaussianHMM
except ImportError:
    raise ImportError("hmmlearn is required. Install: pip install hmmlearn")

try:
    from sklearn.preprocessing import StandardScaler
except ImportError:
    raise ImportError("scikit-learn is required. Install: pip install scikit-learn")


# ── Constants ─────────────────────────────────────────────────────────────────

FEATURES = ["adx14", "hurst_30", "rv5d", "vix_z60", "adx_hurst_cross", "rv5d_change"]
N_COMPONENTS = 3
COVARIANCE_TYPE = "full"
N_ITER = 200
RANDOM_STATE = 42
TRAIN_WINDOW = 756          # 3 years of trading days
MODEL_PATH = os.path.join(os.path.dirname(__file__), "hmm_model.pkl")
PLOT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "hmm_regimes.png")


# ── Public API ────────────────────────────────────────────────────────────────

def train_hmm(conn=None) -> tuple:
    """
    Train 3-state GaussianHMM on the most recent 756 rows of gold.regime_features.
    Predict on full history, write to gold.hmm_regime_states, save model to disk.
    Returns: (model, DataFrame with predictions)
    """
    if conn is None:
        conn = get_connection()
    cur = conn.cursor()

    # ── 1. Load features ──────────────────────────────────────────────────────
    cur.execute(f"""
        SELECT date, {', '.join(FEATURES)}
        FROM gold.regime_features
        ORDER BY date
    """)
    rows = cur.fetchall()
    if not rows:
        raise ValueError("No data found in gold.regime_features")

    df = pd.DataFrame(rows, columns=['date'] + FEATURES)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    for col in FEATURES:
        df[col] = df[col].astype(float)

    # Drop rows with any NaN in the 4 features (HMM cannot handle NaNs)
    df_clean = df.dropna(subset=FEATURES).copy()
    if len(df_clean) < TRAIN_WINDOW:
        raise ValueError(f"Only {len(df_clean)} clean rows available, need {TRAIN_WINDOW} for training")

    # ── 2. Train / test split ─────────────────────────────────────────────────
    train_df = df_clean.tail(TRAIN_WINDOW).copy()
    X_train = train_df[FEATURES].values

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    # ── 3. Fit 3-state HMM ────────────────────────────────────────────────────
    model = GaussianHMM(
        n_components=N_COMPONENTS,
        covariance_type=COVARIANCE_TYPE,
        n_iter=N_ITER,
        random_state=RANDOM_STATE,
        verbose=False,
    )
    model.fit(X_train_scaled)

    # ── 4. Fit 1-state baseline for log-likelihood comparison ─────────────────
    baseline = GaussianHMM(
        n_components=1,
        covariance_type=COVARIANCE_TYPE,
        n_iter=N_ITER,
        random_state=RANDOM_STATE,
        verbose=False,
    )
    baseline.fit(X_train_scaled)
    ll_3state = model.score(X_train_scaled)
    ll_1state = baseline.score(X_train_scaled)

    # ── 5. Auto-label states by mean rv5d ─────────────────────────────────────
    # model.means_ is in scaled space; get means in original space for interpretability
    means_orig = scaler.inverse_transform(model.means_)
    rv5d_idx = FEATURES.index("rv5d")
    rv5d_means = {i: float(means_orig[i, rv5d_idx]) for i in range(N_COMPONENTS)}
    sorted_states = sorted(rv5d_means, key=lambda k: rv5d_means[k])
    label_map = {
        sorted_states[0]: "CARRY",
        sorted_states[1]: "MEAN_REV",
        sorted_states[2]: "TREND",
    }
    print(f"  Label map: {label_map}")
    print(f"  State means (rv5d): {rv5d_means}")

    # ── 6. Predict on FULL history (not just training window) ─────────────────
    X_full = df_clean[FEATURES].values
    X_full_scaled = scaler.transform(X_full)
    states = model.predict(X_full_scaled)
    posteriors = model.predict_proba(X_full_scaled)
    confidence = posteriors.max(axis=1)

    df_clean['hmm_state'] = states
    df_clean['hmm_label'] = df_clean['hmm_state'].map(label_map)
    df_clean['confidence'] = confidence
    print(f"  Predicted on {len(df_clean)} rows, max date: {df_clean.index.max().date()}")
    
    # Check for any dates that might have been dropped
    all_dates = set(df.index)
    clean_dates = set(df_clean.index)
    dropped = sorted(all_dates - clean_dates)
    if dropped:
        print(f"  ⚠️  Dropped {len(dropped)} rows with NaN features: {dropped[:5]}...")
    else:
        print(f"  ✅ No rows dropped — all dates have clean features")

    # ── 9. Serialize model ────────────────────────────────────────────────────
    payload = {
        "model": model,
        "scaler": scaler,
        "label_map": label_map,
        "trained_on": df_clean.index.max().strftime("%Y-%m-%d"),
        "n_rows": len(train_df),
        "features": FEATURES,
    }
    joblib.dump(payload, MODEL_PATH)
    print(f"✅ Model saved: {MODEL_PATH}")

    # ── 10. Sanity plot ───────────────────────────────────────────────────────
    _plot_sanity(df_clean)

    # ── 11. Summary prints ────────────────────────────────────────────────────
    _print_summary(df_clean, ll_3state, ll_1state, means_orig, label_map, rv5d_idx)

    # ── 7. Validation ─────────────────────────────────────────────────────────
    _validate(
        train_df=train_df,
        pred_df=df_clean,
        states=states[-TRAIN_WINDOW:],
        ll_3state=ll_3state,
        ll_1state=ll_1state,
        label_map=label_map,
    )

    # ── 8. Upsert to gold.hmm_regime_states ───────────────────────────────────
    _ensure_table(conn)
    inserted = 0
    for idx, row in df_clean.reset_index().iterrows():
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
    print(f"✅ gold.hmm_regime_states — {inserted} rows upserted")

    conn.close()
    return model, df_clean


def load_hmm() -> GaussianHMM:
    """Load the serialized HMM model dict and return the GaussianHMM instance."""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Model not found at {MODEL_PATH}. Run train_hmm() first.")
    payload = joblib.load(MODEL_PATH)
    # Validation that all keys exist
    for key in ("model", "scaler", "label_map", "trained_on", "n_rows", "features"):
        if key not in payload:
            raise ValueError(f"Serialized model missing key: {key}")
    return payload["model"]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.hmm_regime_states (
            date        DATE PRIMARY KEY,
            hmm_state   SMALLINT,
            hmm_label   VARCHAR(10),
            confidence  FLOAT,
            computed_at TIMESTAMP DEFAULT now()
        )
    """)
    conn.commit()


def _validate(train_df, pred_df, states, ll_3state, ll_1state, label_map):
    # 1. Each state fires on >= 10% of training days
    train_states = states
    n_train = len(train_states)
    for raw_state, label in label_map.items():
        pct = np.mean(train_states == raw_state)
        if pct < 0.10:
            raise ValueError(f"Validation fail: state '{label}' (raw {raw_state}) fires on only {pct*100:.1f}% of training days (min 10%)")

    # 2. 3-state log-likelihood > 1-state baseline
    if ll_3state <= ll_1state:
        raise ValueError(f"Validation fail: 3-state LL ({ll_3state:.2f}) <= 1-state baseline ({ll_1state:.2f})")

    # 3. Zero NULLs in hmm_label
    if pred_df['hmm_label'].isna().any():
        raise ValueError("Validation fail: NULL values found in hmm_label")

    # 4. Confidence in [0, 1]
    if pred_df['confidence'].min() < 0.0 or pred_df['confidence'].max() > 1.0:
        raise ValueError("Validation fail: confidence outside [0.0, 1.0]")

    # 5. Model file exists and can be loaded
    # (train_hmm saves before _validate is called, so this will succeed)
    if not os.path.exists(MODEL_PATH):
        raise ValueError(f"Validation fail: model file not found at {MODEL_PATH}")
    payload = joblib.load(MODEL_PATH)
    for key in ("model", "scaler", "label_map", "trained_on", "n_rows", "features"):
        if key not in payload:
            raise ValueError(f"Validation fail: serialized model missing key '{key}'")

    print("✅ All validations passed")


def _plot_sanity(pred_df: pd.DataFrame):
    # Load SPY close for top panel
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, close FROM gold.daily_ohlcv WHERE ticker = 'SPY' ORDER BY date
    """)
    spy_rows = cur.fetchall()
    conn.close()

    spy = pd.DataFrame(spy_rows, columns=['date', 'close'])
    spy['date'] = pd.to_datetime(spy['date'])
    spy = spy.set_index('date').sort_index()
    spy['close'] = spy['close'].astype(float)

    # Colour map
    color_map = {"CARRY": "green", "MEAN_REV": "orange", "TREND": "red"}

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                             gridspec_kw={'height_ratios': [2, 1]})

    # Top: SPY close
    axes[0].plot(spy.index, spy['close'], color='black', linewidth=0.8)
    axes[0].set_ylabel('SPY Close')
    axes[0].set_title('HMM Regime States — Goal 3')

    # Mark March 2020 crash
    axes[0].axvline(pd.Timestamp("2020-03-20"), color='gray', linestyle='--', linewidth=1)

    # Shade Jan-Dec 2021 bull run
    axes[0].axvspan(pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31"),
                    color='blue', alpha=0.08)

    # Bottom: colour-coded regime band
    pred_df = pred_df.reset_index()
    for label, group in pred_df.groupby('hmm_label'):
        axes[1].scatter(group['date'], [1]*len(group),
                        c=color_map.get(label, 'gray'),
                        label=label, s=3, alpha=0.7)
    axes[1].set_yticks([])
    axes[1].set_xlabel('Date')
    axes[1].legend(loc='upper left', markerscale=3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(PLOT_PATH), exist_ok=True)
    plt.savefig(PLOT_PATH, dpi=150)
    plt.close()
    print(f"✅ Sanity plot saved: {PLOT_PATH}")


def _print_summary(pred_df, ll_3state, ll_1state, means_orig, label_map, rv5d_idx):
    n_total = len(pred_df)
    counts = pred_df['hmm_label'].value_counts()

    print("\n=== Regime Distribution ===")
    for label in ["CARRY", "MEAN_REV", "TREND"]:
        c = counts.get(label, 0)
        pct = c / n_total * 100 if n_total else 0
        print(f"  {label:8s}: {c:5d} days ({pct:5.1f}%)")
    print(f"  Total predicted: {n_total} days")

    print("\n=== Regime Distribution Test ===")
    warnings = []
    for label in ["CARRY", "MEAN_REV", "TREND"]:
        c = counts.get(label, 0)
        pct = c / n_total * 100 if n_total else 0
        if pct < 10.0:
            warnings.append(f"  WARNING: {label} is {pct:.1f}% (< 10%)")
        elif pct > 60.0:
            warnings.append(f"  WARNING: {label} is {pct:.1f}% (> 60%)")
    if warnings:
        print("\n".join(warnings))
    else:
        print("  All states within 10-60% bounds")

    delta = ll_3state - ll_1state
    pct_improve = (delta / abs(ll_1state) * 100) if ll_1state != 0 else float('inf')
    result = "PASS" if ll_3state > ll_1state else "FAIL"
    print("\n=== Log-Likelihood Test ===")
    print(f"  3-state HMM log-likelihood:      {ll_3state:.2f}")
    print(f"  1-state baseline log-likelihood: {ll_1state:.2f}")
    print(f"  Improvement: {delta:.2f} ({pct_improve:.1f}% better)")
    print(f"  Result: {result}")

    print("\n=== State Means (original feature space) ===")
    state_means = pd.DataFrame(means_orig, columns=FEATURES)
    state_means['label'] = [label_map[i] for i in range(N_COMPONENTS)]
    state_means = state_means[['label'] + FEATURES]
    print(state_means.to_string(index=False))

    date_min = pred_df.index.min().strftime("%Y-%m-%d")
    date_max = pred_df.index.max().strftime("%Y-%m-%d")
    print(f"\n=== gold.hmm_regime_states ===")
    print(f"  Rows: {n_total}")
    print(f"  Date range: {date_min} to {date_max}")


# ── Main (standalone) ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("→ Training HMM regime model...")
    train_hmm()
    print("✅ HMM training complete")
