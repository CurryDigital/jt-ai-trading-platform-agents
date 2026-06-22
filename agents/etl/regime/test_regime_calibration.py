#!/usr/bin/env python3
"""
Test suite for G9 regime rules calibration.
Run: cd .../etl/regime && python3 test_regime_calibration.py
"""
import sys, os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'), override=True)

sys.path.insert(0, '../shared/scripts')
sys.path.insert(0, '.')

import pandas as pd
import psycopg2
from db import get_connection
import regime_rules

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_gap_window_df():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, hmm_state, hmm_label, confidence
        FROM gold.hmm_regime_states
        WHERE date BETWEEN '2026-04-16' AND '2026-05-19'
        ORDER BY date
    """)
    hmm = pd.DataFrame(cur.fetchall(), columns=['date','hmm_state','hmm_label','confidence'])
    hmm['date'] = pd.to_datetime(hmm['date'])
    hmm = hmm.set_index('date').sort_index()

    cur.execute("""
        SELECT r.date, r.adx14, r.hurst_30, r.rv5d, r.rv_iv_ratio, r.vix_z60,
               r.event_flag, r.rv5d_change,
               CASE m.severity WHEN 'heavy' THEN 3 WHEN 'medium' THEN 2
                               WHEN 'light' THEN 1 ELSE 0 END as severity
        FROM gold.regime_features r
        LEFT JOIN gold.macro_event_flags m ON r.date = m.date
        WHERE r.date BETWEEN '2026-04-16' AND '2026-05-19'
        ORDER BY r.date
    """)
    feat = pd.DataFrame(cur.fetchall(), columns=[
        'date','adx14','hurst_30','rv5d','rv_iv_ratio',
        'vix_z60','event_flag','rv5d_change','severity'
    ])
    feat['date'] = pd.to_datetime(feat['date'])
    feat = feat.set_index('date').sort_index()
    for col in feat.columns:
        feat[col] = feat[col].astype(float)
    conn.close()
    return hmm.join(feat, how='inner')

# ── Tests ─────────────────────────────────────────────────────────────────────

def test_carry_threshold_is_060():
    """Priority 5 CARRY rule must use 0.60, not 0.80."""
    import inspect
    src = inspect.getsource(regime_rules.assign_regime)
    assert '0.60' in src, "CARRY threshold not found as 0.60 in assign_regime"
    assert src.count('0.80') == 0, "Old 0.80 threshold still present in assign_regime"
    print("✅ test_carry_threshold_is_060")

def test_2026_05_19_is_mean_rev():
    """2026-05-19 must be MEAN_REV with override_used=False."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT regime, hmm_label, override_used, confidence
        FROM gold.regime_label
        WHERE date = '2026-05-19'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "2026-05-19 not found in gold.regime_label"
    regime, hmm, override, conf = row
    assert regime == 'MEAN_REV', f"Expected MEAN_REV, got {regime}"
    assert override == False, f"Expected override_used=False, got {override}"
    assert hmm == 'MEAN_REV', f"Expected hmm=MEAN_REV, got {hmm}"
    assert conf > 0.95, f"Expected confidence > 0.95, got {conf}"
    print("✅ test_2026_05_19_is_mean_rev")

def test_gap_window_carry_count_drops():
    """CARRY count in gap window must be <= 2 (was 8)."""
    df = get_gap_window_df()
    df['regime'] = df.apply(regime_rules.assign_regime, axis=1)
    carry_count = (df['regime'] == 'CARRY').sum()
    assert carry_count <= 2, f"Expected CARRY <= 2, got {carry_count}"
    print(f"✅ test_gap_window_carry_count_drops (CARRY={carry_count})")

def test_idempotency():
    """Re-running build_regime_label must not change row count."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM gold.regime_label")
    before = cur.fetchone()[0]

    # Re-run (this is idempotent by design)
    regime_rules.build_regime_label()

    cur.execute("SELECT COUNT(*) FROM gold.regime_label")
    after = cur.fetchone()[0]
    conn.close()
    assert before == after, f"Row count changed: {before} → {after}"
    print(f"✅ test_idempotency ({before} rows before/after)")

def test_full_history_affected_rows():
    """Report how many CARRY rows have rv_iv_ratio in [0.60, 0.80)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*)
        FROM gold.regime_label l
        JOIN gold.regime_features r ON l.date = r.date
        WHERE l.regime = 'CARRY'
          AND r.rv_iv_ratio >= 0.60
          AND r.rv_iv_ratio < 0.80
    """)
    count = cur.fetchone()[0]
    conn.close()
    assert count <= 65, f"Expected <= 65 affected rows, got {count}"
    print(f"✅ test_full_history_affected_rows (affected={count})")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    test_carry_threshold_is_060()
    test_2026_05_19_is_mean_rev()
    test_gap_window_carry_count_drops()
    test_idempotency()
    test_full_history_affected_rows()
    print("\n🎉 All tests passed")
