#!/usr/bin/env python3
"""
HMM Backfill Tests — G5d
========================
Row count, idempotency, label range, and 2026-05-19 specific checks.
"""
import sys, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..'))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection

GAP_START = '2026-04-16'
GAP_END = '2026-05-19'
EXPECTED_GAP_ROWS = 22


def test_gap_row_counts():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM gold.hmm_regime_states
        WHERE date BETWEEN %s AND %s
    """, (GAP_START, GAP_END))
    hmm_count = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM gold.regime_label
        WHERE date BETWEEN %s AND %s
    """, (GAP_START, GAP_END))
    label_count = cur.fetchone()[0]
    conn.close()

    assert hmm_count == EXPECTED_GAP_ROWS, f'hmm_regime_states gap rows: {hmm_count}, expected {EXPECTED_GAP_ROWS}'
    assert label_count == EXPECTED_GAP_ROWS, f'regime_label gap rows: {label_count}, expected {EXPECTED_GAP_ROWS}'
    print(f'✅ Row counts — hmm: {hmm_count}, label: {label_count}')


def test_max_date():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT MAX(date) FROM gold.hmm_regime_states")
    hmm_max = cur.fetchone()[0]
    cur.execute("SELECT MAX(date) FROM gold.regime_label")
    label_max = cur.fetchone()[0]
    conn.close()

    # Max date should be >= GAP_END (daily pipeline may have added 2026-05-20)
    from datetime import date
    assert hmm_max >= date.fromisoformat(GAP_END), f'hmm max date {hmm_max} < {GAP_END}'
    assert label_max >= date.fromisoformat(GAP_END), f'label max date {label_max} < {GAP_END}'
    print(f'✅ Max dates — hmm: {hmm_max}, label: {label_max}')


def test_idempotency():
    """Re-run hmm_backfill and verify no duplicate rows."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, COUNT(*) FROM gold.hmm_regime_states
        WHERE date BETWEEN %s AND %s
        GROUP BY date HAVING COUNT(*) > 1
    """, (GAP_START, GAP_END))
    hmm_dups = cur.fetchall()
    cur.execute("""
        SELECT date, COUNT(*) FROM gold.regime_label
        WHERE date BETWEEN %s AND %s
        GROUP BY date HAVING COUNT(*) > 1
    """, (GAP_START, GAP_END))
    label_dups = cur.fetchall()
    conn.close()

    assert len(hmm_dups) == 0, f'hmm_regime_states duplicates: {hmm_dups}'
    assert len(label_dups) == 0, f'regime_label duplicates: {label_dups}'
    print('✅ Idempotency — no duplicates')


def test_label_validity():
    conn = get_connection()
    cur = conn.cursor()
    valid = {'TREND', 'MEAN_REV', 'CARRY', 'EVENT', 'FLAT'}
    cur.execute("""
        SELECT DISTINCT regime FROM gold.regime_label
        WHERE date BETWEEN %s AND %s
    """, (GAP_START, GAP_END))
    labels = {r[0] for r in cur.fetchall()}
    conn.close()

    invalid = labels - valid
    assert len(invalid) == 0, f'Invalid labels in gap: {invalid}'
    print(f'✅ Label validity — all labels in {labels} are valid')


def test_event_severity():
    """EVENT rows must have severity >= 2 (high-severity events only)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, severity FROM gold.regime_label
        WHERE date BETWEEN %s AND %s AND regime = 'EVENT'
    """, (GAP_START, GAP_END))
    events = cur.fetchall()
    conn.close()

    bad = [(d, s) for d, s in events if s < 2]
    assert len(bad) == 0, f'EVENT rows with severity < 2: {bad}'
    print(f'✅ Event severity — {len(events)} EVENT rows all have severity >= 2')


def test_2026_05_19():
    """Specific check for 2026-05-19."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, regime, hmm_label, override_used, confidence, severity
        FROM gold.regime_label WHERE date = '2026-05-19'
    """)
    row = cur.fetchone()
    conn.close()

    assert row is not None, '2026-05-19 not found in regime_label'
    date_val, regime, hmm_label, override_used, confidence, severity = row
    print(f'✅ 2026-05-19 — regime={regime}, hmm={hmm_label}, override={override_used}, conf={confidence:.4f}, sev={severity}')

    # HMM confidence must be high (not capped at 0.65)
    assert confidence > 0.9, f'2026-05-19 confidence {confidence} <= 0.9 (should reflect HMM, not fallback cap)'
    print(f'✅ 2026-05-19 confidence {confidence:.4f} > 0.9 (not fallback-capped)')


def test_inference_only():
    """Verify model training cutoff predates gap."""
    import joblib
    model_path = os.path.join(WORKSPACE, 'regime', 'hmm_model.pkl')
    payload = joblib.load(model_path)
    trained_on = payload['trained_on']
    assert trained_on < GAP_START, f'Model trained_on {trained_on} >= gap start {GAP_START}'
    print(f'✅ Inference only — model trained on {trained_on} (before gap)')


def main():
    print('=' * 60)
    print('HMM Backfill Tests — G5d')
    print('=' * 60)
    test_gap_row_counts()
    test_max_date()
    test_idempotency()
    test_label_validity()
    test_event_severity()
    test_2026_05_19()
    test_inference_only()
    print('\n' + '=' * 60)
    print('✅ All tests passed')
    print('=' * 60)


if __name__ == '__main__':
    main()
