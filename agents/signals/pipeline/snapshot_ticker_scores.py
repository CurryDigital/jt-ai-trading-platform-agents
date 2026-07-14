#!/usr/bin/env python3
"""
snapshot_ticker_scores.py — daily signal-history snapshot (P0-3).

gold.strategy_ticker_scores is overwrite-in-place: without this step the
system has no record of yesterday's signals, so hit rate / forward returns
can never be measured. Runs as the FINAL step of run_signal_cycle.sh so it
captures the day's final state from ALL score writers (criteria scorer, S9,
paper-signal ingesters) in one pass.

Writes: gold.strategy_ticker_scores_history (one row per strategy/ticker/day;
same-day re-runs update the day's row, prior days are never touched).

Requires: db_setup/migrations/005_signal_history.sql applied. If the history
table is missing, prints the migration path and exits non-zero — a missing
history table means signals are silently unmeasurable again, which should be
loud, not skipped.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'etl', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path: sys.path.insert(0, _ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection

SNAPSHOT_SQL = """
INSERT INTO gold.strategy_ticker_scores_history
    (snapshot_date, strategy_id, ticker, score, signal_action,
     entry_score, exit_score, criteria_met, position_status, snapshotted_at)
SELECT
    CURRENT_DATE, strategy_id, ticker, score, signal_action,
    entry_score, exit_score, criteria_met, position_status, NOW()
FROM gold.strategy_ticker_scores
ON CONFLICT (snapshot_date, strategy_id, ticker) DO UPDATE SET
    score           = EXCLUDED.score,
    signal_action   = EXCLUDED.signal_action,
    entry_score     = EXCLUDED.entry_score,
    exit_score      = EXCLUDED.exit_score,
    criteria_met    = EXCLUDED.criteria_met,
    position_status = EXCLUDED.position_status,
    snapshotted_at  = NOW();
"""


def main() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('gold.strategy_ticker_scores_history')")
            if cur.fetchone()[0] is None:
                print("❌ gold.strategy_ticker_scores_history does not exist — "
                      "apply db_setup/migrations/005_signal_history.sql first. "
                      "Without it, signal history is silently lost every cycle.")
                return 1
            cur.execute(SNAPSHOT_SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.strategy_ticker_scores_history — {n} rows snapshotted for today")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
