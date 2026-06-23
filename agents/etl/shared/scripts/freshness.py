#!/usr/bin/env python3
"""
freshness.py — write per-source freshness rows after a successful bronze ingest.

Pairs with db_setup/migrations/001_source_freshness.sql which created
gold.source_freshness (one row per bronze source) and the gold.v_source_freshness
view. Bronze scripts call mark_source_refreshed() at the end of main() on the
happy path so the operator can SELECT a single view to see which sources are
overdue.

Contract (kept tiny on purpose — should be a 3-line call site addition):

    from freshness import mark_source_refreshed
    mark_source_refreshed(conn, source='yfinance', max_date=last_business_day)
    # or, on a tracked failure that should still bump last_checked_at:
    mark_source_refreshed(conn, source='yfinance', error='HTTP 503 from api')

If gold.source_freshness or its row is missing, the helper logs a warning and
returns False instead of raising. This means a bronze script that ships before
the migration is applied still runs; once the migration lands, freshness starts
populating automatically on next run.
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
) -> bool:
    """
    Upsert a freshness row for `source`. Returns True on success, False on a
    soft failure that should NOT crash the calling bronze script.

    - On success path: pass `max_date` (the latest business date the source
      now covers). `last_refreshed_at` is bumped to NOW().
    - On a tracked failure: pass `error` (last_error gets the message,
      last_refreshed_at is NOT bumped, last_checked_at IS bumped).

    The function never raises on missing-table / missing-row — those are
    deploy-order issues that should not block bronze ingestion.
    """
    now = datetime.now(timezone.utc)

    try:
        with conn.cursor() as cur:
            if error is not None:
                cur.execute(
                    """
                    UPDATE gold.source_freshness
                    SET last_checked_at = %s,
                        last_error      = %s
                    WHERE source = %s
                    """,
                    (now, str(error)[:1000], source),
                )
            else:
                cur.execute(
                    """
                    UPDATE gold.source_freshness
                    SET max_date          = COALESCE(%s, max_date),
                        last_refreshed_at = %s,
                        last_checked_at   = %s,
                        last_error        = NULL
                    WHERE source = %s
                    """,
                    (max_date, now, now, source),
                )

            updated = cur.rowcount
        conn.commit()

        if updated == 0:
            print(
                f"freshness: source={source!r} not in gold.source_freshness — "
                f"add a seed row (see db_setup/migrations/001_source_freshness.sql) "
                f"or run the migration.",
                file=sys.stderr,
            )
            return False
        return True

    except Exception as e:
        # Soft-fail: the bronze script's own data write already succeeded.
        # We don't want a freshness-table issue to roll that back.
        conn.rollback()
        print(
            f"freshness: failed to mark source={source!r}: {e}. "
            f"Has db_setup/migrations/001_source_freshness.sql been applied?",
            file=sys.stderr,
        )
        return False
