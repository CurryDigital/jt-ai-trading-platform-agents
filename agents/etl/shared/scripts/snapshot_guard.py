#!/usr/bin/env python3
"""Snapshot-guard for full-table gold/silver writers (user directive 2026-10-17).

Extends the 2026-10-16 silver-merge rule to every job that rewrites a gold
score/feature table in full. A full-rewrite run must carry a snapshot/run id:

  --snapshot-id <id>            (manual/out-of-band runs: snapshot FIRST)
  ETL_RUN_SNAPSHOT_ID           (set automatically by run_stage.py)
  GOLD_REWRITE_SNAPSHOT_ID      (wrapper-level override)

Usage in a writer, before any write:

    from snapshot_guard import require_snapshot_id
    snapshot_id = require_snapshot_id("gold.sue_scores full upsert",
                                      "gold/equity/build_earnings_signals.py")

Optionally log the run:
    from snapshot_guard import log_snapshot
    log_snapshot(cur, snapshot_id, scope, script, pre_rows, post_rows, note)
"""
import os
import sys


def require_snapshot_id(scope, script):
    for i, a in enumerate(sys.argv):
        if a == "--snapshot-id" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    sid = (os.environ.get("GOLD_REWRITE_SNAPSHOT_ID")
           or os.environ.get("ETL_RUN_SNAPSHOT_ID"))
    if not sid:
        print(f"❌ REFUSED: {script} rewrites {scope} in full.")
        print("   Provide --snapshot-id <id> or set GOLD_REWRITE_SNAPSHOT_ID /")
        print("   ETL_RUN_SNAPSHOT_ID. Out-of-band runs must snapshot the table")
        print("   first and pass that id. Scheduled runs get one from run_stage.")
        sys.exit(2)
    return sid


def log_snapshot(cur, snapshot_id, scope, script, pre_rows, post_rows, note=""):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.etl_snapshot_log (
            snapshot_id text,
            scope text NOT NULL,
            script text NOT NULL,
            pre_rows bigint,
            pre_max_date date,
            post_rows bigint,
            post_max_date date,
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (snapshot_id, scope)
        )""")
    cur.execute("""
        INSERT INTO gold.etl_snapshot_log
            (snapshot_id, scope, script, pre_rows, post_rows, note)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (snapshot_id, scope) DO UPDATE SET
            post_rows = EXCLUDED.post_rows, note = EXCLUDED.note""",
        (snapshot_id, scope, script, pre_rows, post_rows, note))
