"""Regression tests for the shared fail-closed gold-layer gate."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


SIGNALS_DIR = Path(__file__).resolve().parents[1]
if str(SIGNALS_DIR) not in sys.path:
    sys.path.insert(0, str(SIGNALS_DIR))

from check_gold_layer_gate import evaluate_gold_layer_gate


NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
FRESH = NOW - timedelta(hours=2)


def test_ready_state_with_fresh_timestamp_allows_signals():
    decision = evaluate_gold_layer_gate('ready', FRESH, now=NOW)
    assert decision.allowed is True
    assert decision.reason == 'fresh'
    assert decision.age_hours == 2


def test_partial_state_with_fresh_timestamp_allows_signals():
    decision = evaluate_gold_layer_gate('partial', FRESH, now=NOW)
    assert decision.allowed is True


def test_failed_locked_and_stale_states_are_blocked():
    for state in ('failed', 'locked', 'stale'):
        decision = evaluate_gold_layer_gate(state, FRESH, now=NOW)
        assert decision.allowed is False
        assert decision.reason == f'state_{state}'


def test_unknown_and_missing_states_are_blocked():
    for state in (None, '', 'unknown', 'degraded'):
        decision = evaluate_gold_layer_gate(state, FRESH, now=NOW)
        assert decision.allowed is False
        assert decision.reason == 'state_unknown'


def test_missing_or_invalid_refresh_timestamp_is_blocked():
    missing = evaluate_gold_layer_gate('ready', None, now=NOW)
    invalid = evaluate_gold_layer_gate('ready', 'not-a-timestamp', now=NOW)
    assert missing.reason == 'refresh_timestamp_missing'
    assert invalid.reason == 'refresh_timestamp_invalid'
    assert missing.allowed is False
    assert invalid.allowed is False


def test_expired_refresh_timestamp_is_blocked():
    decision = evaluate_gold_layer_gate(
        'ready', NOW - timedelta(hours=30, seconds=1), now=NOW
    )
    assert decision.allowed is False
    assert decision.reason == 'refresh_timestamp_expired'


def test_default_thirty_hour_boundary_is_allowed():
    decision = evaluate_gold_layer_gate(
        'partial', NOW - timedelta(hours=30), now=NOW
    )
    assert decision.allowed is True


def test_configurable_freshness_threshold_is_enforced():
    decision = evaluate_gold_layer_gate(
        'ready', NOW - timedelta(hours=2), now=NOW, max_age_hours=1
    )
    assert decision.allowed is False
    assert decision.reason == 'refresh_timestamp_expired'


def test_naive_timestamp_is_treated_as_utc():
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    decision = evaluate_gold_layer_gate('ready', naive, now=NOW)
    assert decision.allowed is True
    assert decision.age_hours == 1


def test_materially_future_timestamp_is_blocked():
    decision = evaluate_gold_layer_gate(
        'ready', NOW + timedelta(minutes=6), now=NOW
    )
    assert decision.allowed is False
    assert decision.reason == 'refresh_timestamp_future'


def test_cron_and_manual_refresh_use_the_same_fail_closed_gate():
    agents_dir = SIGNALS_DIR.parent
    scripts = (
        agents_dir / 'signals' / 'run_signal_cycle.sh',
        agents_dir / 'signals' / 'refresh_now.sh',
    )
    for script in scripts:
        source = script.read_text()
        assert 'check_gold_layer_gate.py' in source
        assert 'exit 75' in source
        assert 'proceeding cautiously' not in source


def _main():
    fns = [v for k, v in globals().items() if k.startswith('test_') and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f'PASS  {fn.__name__}')
        except AssertionError as exc:
            failures += 1
            print(f'FAIL  {fn.__name__}: {exc}')
        except Exception as exc:
            failures += 1
            print(f'ERROR {fn.__name__}: {type(exc).__name__}: {exc}')
    print(f'\n{len(fns) - failures}/{len(fns)} passed')
    sys.exit(0 if failures == 0 else 1)


if __name__ == '__main__':
    _main()
