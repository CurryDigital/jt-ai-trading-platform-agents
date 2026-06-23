"""
Regime Detection Engine — Test Suite
=====================================
Run: pytest tests/test_regime.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import pytest
import joblib
from datetime import date, datetime, timezone
from db import get_connection

# ── Test 1 ────────────────────────────────────────────────────────────────────

def test_no_null_regimes():
    """Query gold.regime_label for last 252 rows. Assert zero NULL values."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM gold.regime_label
        WHERE regime IS NULL
        AND date >= (SELECT MAX(date) - INTERVAL '252 days' FROM gold.regime_label)
    """)
    null_count = cur.fetchone()[0]
    conn.close()
    assert null_count == 0, f"Found {null_count} NULL regimes in last 252 rows"

# ── Test 2 ────────────────────────────────────────────────────────────────────

def test_valid_regime_labels():
    """Assert regime column contains only valid values."""
    valid = {'TREND', 'MEAN_REV', 'CARRY', 'EVENT', 'FLAT'}
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT regime FROM gold.regime_label
        WHERE date >= (SELECT MAX(date) - INTERVAL '252 days' FROM gold.regime_label)
    """)
    found = {r[0] for r in cur.fetchall()}
    conn.close()
    invalid = found - valid
    assert not invalid, f"Invalid regime labels found: {invalid}"

# ── Test 3 ────────────────────────────────────────────────────────────────────

def test_each_regime_fires_above_1pct():
    """Over full history, assert each of the 5 labels appears in at least 1% of rows."""
    valid = {'TREND', 'MEAN_REV', 'CARRY', 'EVENT', 'FLAT'}
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT regime, COUNT(*) FROM gold.regime_label GROUP BY regime")
    rows = cur.fetchall()
    conn.close()
    counts = {r[0]: r[1] for r in rows}
    total = sum(counts.values())
    for regime in valid:
        pct = counts.get(regime, 0) / total * 100
        assert pct >= 1.0, f"Regime '{regime}' fires on only {pct:.1f}% of days (min 1%)"

# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_flat_on_panic_days():
    """All days with vix_z60 > 2.5 (excluding high-severity events) must be FLAT."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM gold.regime_label l
        JOIN gold.regime_features r ON l.date = r.date
        WHERE r.vix_z60 > 2.5
        AND NOT (r.event_flag = 1 AND l.severity >= 2)
        AND l.regime != 'FLAT'
    """)
    offenders = cur.fetchone()[0]
    conn.close()
    assert offenders == 0, f"{offenders} panic days are not labeled FLAT"

# ── Test 5 ────────────────────────────────────────────────────────────────────

def test_event_on_high_severity_days():
    """All days with event_flag=1 and severity >= 2 must be EVENT."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM gold.regime_label l
        JOIN gold.regime_features r ON l.date = r.date
        WHERE r.event_flag = 1 AND l.severity >= 2 AND l.regime != 'EVENT'
    """)
    offenders = cur.fetchone()[0]
    conn.close()
    assert offenders == 0, f"{offenders} high-severity event days are not labeled EVENT"

# ── Test 6 ────────────────────────────────────────────────────────────────────

def test_no_future_dates():
    """Query gold.daily_ohlcv for any date > today. Assert zero rows."""
    conn = get_connection()
    cur = conn.cursor()
    today = date.today()
    cur.execute("""
        SELECT COUNT(*) FROM gold.daily_ohlcv WHERE date > %s
    """, (today,))
    future_count = cur.fetchone()[0]
    conn.close()
    assert future_count == 0, f"Found {future_count} future dates in gold.daily_ohlcv"

# ── Test 7 ────────────────────────────────────────────────────────────────────

def test_hmm_model_loads():
    """joblib.load('regime/hmm_model.pkl') — assert all 5 keys and 6 features."""
    model_path = os.path.join(os.path.dirname(__file__), '..', 'regime', 'hmm_model.pkl')
    assert os.path.exists(model_path), f"Model file not found: {model_path}"
    payload = joblib.load(model_path)
    required_keys = {'model', 'scaler', 'label_map', 'trained_on', 'features'}
    assert set(payload.keys()) >= required_keys, f"Missing keys: {required_keys - set(payload.keys())}"
    expected_features = ['adx14', 'hurst_30', 'rv5d', 'vix_z60', 'adx_hurst_cross', 'rv5d_change']
    assert payload['features'] == expected_features, \
        f"Features mismatch: {payload['features']} != {expected_features}"

# ── Test 8 ────────────────────────────────────────────────────────────────────

def test_pipeline_idempotent():
    """Run gold_builder.py twice. Assert same row count in regime_label."""
    import subprocess, sys
    workspace = os.path.join(os.path.dirname(__file__), '..')
    gold_builder = os.path.join(workspace, 'gold', 'gold_builder.py')

    conn = get_connection()
    cur = conn.cursor()

    # Count before
    cur.execute("SELECT COUNT(*) FROM gold.regime_label")
    before = cur.fetchone()[0]

    # Run gold_builder once
    r1 = subprocess.run([sys.executable, gold_builder], capture_output=True, text=True,
                        cwd=workspace, timeout=300)
    assert r1.returncode == 0, f"First gold_builder run failed: {r1.stderr[:500]}"

    cur.execute("SELECT COUNT(*) FROM gold.regime_label")
    after1 = cur.fetchone()[0]

    # Run gold_builder again
    r2 = subprocess.run([sys.executable, gold_builder], capture_output=True, text=True,
                        cwd=workspace, timeout=300)
    assert r2.returncode == 0, f"Second gold_builder run failed: {r2.stderr[:500]}"

    cur.execute("SELECT COUNT(*) FROM gold.regime_label")
    after2 = cur.fetchone()[0]
    conn.close()

    assert after1 == before, f"Row count changed after first run: {before} → {after1}"
    assert after2 == after1, f"Row count changed after second run: {after1} → {after2}"

# ── Test 9 ────────────────────────────────────────────────────────────────────

def test_get_active_strategies_structure():
    """Call get_active_strategies(conn). Assert valid dict structure."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from regime.regime_rules import get_active_strategies

    conn = get_connection()
    result = get_active_strategies(conn)
    conn.close()

    required_keys = {'date', 'regime', 'active_strategies', 'override_used', 'confidence'}
    assert set(result.keys()) >= required_keys, f"Missing keys: {required_keys - set(result.keys())}"
    assert isinstance(result['active_strategies'], list), "active_strategies must be a list"
    assert all(isinstance(x, int) for x in result['active_strategies']), \
        "active_strategies must contain integers"
    assert result['regime'] in {'TREND', 'MEAN_REV', 'CARRY', 'EVENT', 'FLAT'}, \
        f"Invalid regime: {result['regime']}"

# ── Test 10 ───────────────────────────────────────────────────────────────────

def test_regime_gate_blocks_inactive_strategies():
    """Simulate regime = CARRY. Instantiate Strategy01 (TREND strategy).
    Assert compute_signal() == 0 and result['active'] == False."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from strategies.stubs import Strategy01

    conn = get_connection()
    strat = Strategy01(conn)
    signal = strat.compute_signal()
    result = strat.run()
    conn.close()

    assert signal == 0, f"Expected signal=0 for inactive strategy, got {signal}"
    assert result['active'] == False, f"Expected active=False for inactive strategy, got {result['active']}"

# ── Test 11 ───────────────────────────────────────────────────────────────────

def test_regime_gate_allows_active_strategies():
    """Simulate regime = CARRY. Instantiate Strategy07 (CARRY strategy).
    Assert is_active_today() == True."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from strategies.stubs import Strategy07

    conn = get_connection()
    strat = Strategy07(conn)
    active = strat.is_active_today()
    conn.close()

    assert active == True, f"Expected active=True for Strategy07 in CARRY regime, got {active}"

# ── Test 12 ───────────────────────────────────────────────────────────────────

def test_position_sizer_returns_zero_when_flat():
    """Call size_position(signal=0, price=100, atr14=2). Assert result == 0.0"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from strategies.stubs import Strategy01

    conn = get_connection()
    strat = Strategy01(conn)
    size = strat.size_position(signal=0, price=100, atr14=2)
    conn.close()

    assert size == 0.0, f"Expected position_size=0.0 for signal=0, got {size}"

# ── Test 13 ───────────────────────────────────────────────────────────────────

def test_position_sizer_returns_correct_size():
    """Call size_position(signal=1, price=100, atr14=2).
    Expected: (100_000 * 0.01) / (2 * 100) = 5.0 units"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from strategies.stubs import Strategy01

    conn = get_connection()
    strat = Strategy01(conn)
    size = strat.size_position(signal=1, price=100, atr14=2)
    conn.close()

    expected = (100_000 * 0.01) / (2 * 100)
    assert size == expected, f"Expected position_size={expected}, got {size}"

# ── Test 14 ───────────────────────────────────────────────────────────────────

def test_strategy_signals_table_exists():
    """Query information_schema.tables. Assert gold.strategy_signals exists."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'gold' AND table_name = 'strategy_signals'
    """)
    count = cur.fetchone()[0]
    conn.close()

    assert count == 1, f"gold.strategy_signals table not found (count={count})"
