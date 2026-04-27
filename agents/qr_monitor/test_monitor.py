"""
Unit tests for qr_monitor's pure-logic helpers.

Mocks the DB completely. Verifies the exponential-backoff gate behaves per
the contract documented in agents/qr_monitor/AGENTS.md.

Run: `python3 agents/qr_monitor/test_monitor.py`
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.qr_monitor._backoff import requeue_eligible
from agents.shared.constants import REQUEUE_BACKOFF_MINUTES, MAX_REQUEUE_COUNT


def test_first_requeue_is_immediate():
    eligible, wait = requeue_eligible(requeue_count=0, last_at=None)
    assert eligible is True and wait == 0


def test_second_requeue_requires_30_minutes():
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=20)        # 20 min ago — too soon
    eligible, wait = requeue_eligible(1, last, now=now)
    assert eligible is False
    assert wait > 0 and wait <= REQUEUE_BACKOFF_MINUTES[1]

    last = now - timedelta(minutes=31)        # 31 min ago — eligible
    eligible, wait = requeue_eligible(1, last, now=now)
    assert eligible is True and wait == 0


def test_third_requeue_requires_120_minutes():
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=119)
    eligible, wait = requeue_eligible(2, last, now=now)
    assert eligible is False and wait > 0

    last = now - timedelta(minutes=121)
    eligible, _ = requeue_eligible(2, last, now=now)
    assert eligible is True


def test_escalation_after_max_requeue_count():
    """Caller MUST escalate when requeue_count >= MAX_REQUEUE_COUNT."""
    eligible, _ = requeue_eligible(MAX_REQUEUE_COUNT, last_at=None)
    assert eligible is False  # caller must escalate, not requeue


def test_naive_timestamp_handled_as_utc():
    """psycopg2 may return naive datetimes; we must not crash."""
    now = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    naive = now.replace(tzinfo=None) - timedelta(minutes=45)
    eligible, _ = requeue_eligible(1, naive, now=now)
    assert eligible is True


def test_backoff_schedule_matches_constants():
    """The constants tuple is the source of truth — surfaced for the contract doc."""
    assert REQUEUE_BACKOFF_MINUTES == (0, 30, 120)
    assert MAX_REQUEUE_COUNT == 3


def _main():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    _main()
