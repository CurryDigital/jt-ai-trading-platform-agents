"""
Pure-stdlib backoff helpers for qr_monitor.

Kept in its own module so the unit tests can import it without dragging in
psycopg2 (which `monitor_agent.py` imports at module level for DB calls).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from agents.shared.constants import REQUEUE_BACKOFF_MINUTES, MAX_REQUEUE_COUNT


def requeue_eligible(
    requeue_count: int,
    last_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> Tuple[bool, float]:
    """
    Returns (eligible, wait_minutes_remaining).

    The N-th requeue requires REQUEUE_BACKOFF_MINUTES[N] minutes since the
    previous requeue. After MAX_REQUEUE_COUNT, no more requeues are allowed
    (the caller must escalate to failed instead).
    """
    if requeue_count >= MAX_REQUEUE_COUNT:
        return False, 0.0  # caller must escalate
    required = REQUEUE_BACKOFF_MINUTES[requeue_count]
    if required <= 0 or last_at is None:
        return True, 0.0
    now = now or datetime.now(timezone.utc)
    # last_at may be naive depending on DB driver; normalise to UTC.
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    elapsed_min = (now - last_at).total_seconds() / 60.0
    if elapsed_min >= required:
        return True, 0.0
    return False, max(0.0, required - elapsed_min)
