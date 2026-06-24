#!/usr/bin/env python3
"""
freshness.py — write per-source freshness rows after a successful build.

Pairs with db_setup/migrations/001_source_freshness.sql which created
gold.source_freshness (one row per source) and gold.v_source_freshness.

2026-06-22: helper does INSERT … ON CONFLICT DO UPDATE so derived
gold-table builders (not just bronze sources) work without a separate
seed migration. The asset_class / expected_frequency / staleness fields
are only set when the row didn't already exist; subsequent calls leave
those columns alone (they're operator-tunable).

Contract (kept tiny on purpose — a 3-line call site addition):

    from freshness import mark_source_refreshed
    mark_source_refreshed(conn, source='yfinance', max_date=last_business_day)
    # or, on a tracked failure that should still bump last_checked_at:
    mark_source_refreshed(conn, source='yfinance', error='HTTP 503 from api')

Soft-fails on missing-table — bronze scripts that ship before the
migration is applied still run.
"""

from __future__ import annotations

import sys
from datetime import date as _date, datetime, timezone
from typing import Optional


def mark_source_refreshed(
    conn,
    source: str,
    max_date: Optional[_date] = None,
    error: Optional[str] = None,
    asset_class: Optional[str] = None,
    expected_frequency: str = "daily",
    expected_max_staleness_hours: int = 30,
) -> bool:
    """
    Upsert a freshness row for `source`. Returns True on success, False on a
    soft failure that should NOT crash the caller.

    - Success path: pass `max_date` (the latest business date the source now
      covers). last_refreshed_at is bumped to NOW(); last_error cleared.
    - Tracked-failure path: pass `error` (last_error stored; last_refreshed_at
      is NOT bumped, last_checked_at IS bumped).
    """
    now = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
            if error is not None:
                cur.execute(
                    """
                    INSERT INTO gold.source_freshness
                        (source, asset_class, expected_frequency,
                         expected_max_staleness_hours, last_checked_at, last_error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source) DO UPDATE SET
                        last_checked_at = EXCLUDED.last_checked_at,
                        last_error      = EXCLUDED.last_error
                    """,
                    (source, asset_class, expected_frequency,
                     expected_max_staleness_hours, now, str(error)[:1000]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO gold.source_freshness
                        (source, asset_class, expected_frequency,
                         expected_max_staleness_hours,
                         max_date, last_refreshed_at, last_checked_at, last_error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)
                    ON CONFLICT (source) DO UPDATE SET
                        max_date          = COALESCE(EXCLUDED.max_date, gold.source_freshness.max_date),
                        last_refreshed_at = EXCLUDED.last_refreshed_at,
                        last_checked_at   = EXCLUDED.last_checked_at,
                        last_error        = NULL
                    """,
                    (source, asset_class, expected_frequency,
                     expected_max_staleness_hours, max_date, now, now),
                )
        conn.commit()
        return True

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(
            f"freshness: failed to mark source={source!r}: {e}. "
            f"Has db_setup/migrations/001_source_freshness.sql been applied?",
            file=sys.stderr,
        )
        return False
