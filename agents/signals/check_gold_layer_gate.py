#!/usr/bin/env python3
"""Fail-closed gold-layer health gate for signal generation.

Both cron and manual signal entry points call this helper. Signal generation
may proceed only when the latest synchronized pipeline state is ready/partial
and its refreshed_at timestamp is recent enough for the current cadence.

Default freshness is 30 hours, matching the repository's source-freshness
convention. Override with GOLD_MAX_AGE_HOURS or --max-age-hours for an
explicitly configured deployment.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ETL_SCRIPTS = HERE.parent / "etl" / "shared" / "scripts"
if str(ETL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ETL_SCRIPTS))

DEFAULT_MAX_AGE_HOURS = 30.0
FUTURE_SKEW_SECONDS = 300
ALLOWED_STATES = {"ready", "partial"}
BLOCKED_STATES = {"failed", "locked", "stale"}


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    state: str
    refreshed_at: datetime | None
    age_hours: float | None


def evaluate_gold_layer_gate(
    state: object,
    refreshed_at: object,
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> GateDecision:
    """Evaluate gold-layer health without any database dependency."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    normalized_state = str(state).strip().lower() if state is not None else "unknown"
    if normalized_state not in ALLOWED_STATES:
        reason = (
            f"state_{normalized_state}"
            if normalized_state in BLOCKED_STATES
            else "state_unknown"
        )
        return GateDecision(False, reason, normalized_state, None, None)

    if refreshed_at is None:
        return GateDecision(False, "refresh_timestamp_missing", normalized_state, None, None)

    if isinstance(refreshed_at, datetime):
        refreshed = refreshed_at
    else:
        try:
            refreshed = datetime.fromisoformat(str(refreshed_at))
        except (TypeError, ValueError):
            return GateDecision(False, "refresh_timestamp_invalid", normalized_state, None, None)

    if refreshed.tzinfo is None:
        refreshed = refreshed.replace(tzinfo=timezone.utc)
    else:
        refreshed = refreshed.astimezone(timezone.utc)

    age_hours = (current - refreshed).total_seconds() / 3600.0
    if age_hours * 3600.0 < -FUTURE_SKEW_SECONDS:
        return GateDecision(
            False, "refresh_timestamp_future", normalized_state, refreshed, age_hours
        )
    if age_hours > max_age_hours:
        return GateDecision(
            False, "refresh_timestamp_expired", normalized_state, refreshed, age_hours
        )

    return GateDecision(True, "fresh", normalized_state, refreshed, age_hours)


def _max_age_hours(cli_value: float | None) -> float:
    if cli_value is not None:
        return cli_value
    raw = os.environ.get("GOLD_MAX_AGE_HOURS")
    if raw:
        try:
            return float(raw)
        except ValueError:
            print(
                "blocked reason=max_age_invalid "
                f"value={raw!r} default={DEFAULT_MAX_AGE_HOURS:g}"
            )
            raise SystemExit(75)
    return DEFAULT_MAX_AGE_HOURS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age-hours", type=float, default=None)
    args = parser.parse_args()

    try:
        from db import get_connection

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT state, refreshed_at
                    FROM openclaw_researcher.gold_layer_state
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()
        finally:
            conn.close()
    except Exception as exc:
        # Do not echo a DB error message: it may disclose deployment details.
        print(f"blocked reason=state_query_error error_type={type(exc).__name__}")
        return 75

    state, refreshed_at = row if row else (None, None)
    decision = evaluate_gold_layer_gate(
        state,
        refreshed_at,
        max_age_hours=_max_age_hours(args.max_age_hours),
    )

    refreshed = (
        decision.refreshed_at.isoformat() if decision.refreshed_at else "null"
    )
    age = f"{decision.age_hours:.2f}" if decision.age_hours is not None else "unknown"
    if not decision.allowed:
        print(
            "blocked "
            f"reason={decision.reason} state={decision.state} "
            f"refreshed_at={refreshed} age_hours={age}"
        )
        return 75

    print(
        "allowed "
        f"state={decision.state} refreshed_at={refreshed} age_hours={age}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
