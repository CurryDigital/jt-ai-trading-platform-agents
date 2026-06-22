#!/usr/bin/env python3
"""
sync_gold_layer_state.py
========================
Reads .state.json (written by write_pipeline_state.py at the end of
daily_refresh.sh) and syncs the row in openclaw_researcher.gold_layer_state.

CRITICAL: if .state.json is MISSING, this script writes state='stale' with
an explanatory note — it never invents 'ready'/'fresh'. The previous
default-to-fresh behaviour was the source of "operator sees green but
data is days old".
"""

import json
import os
import sys
from datetime import datetime, timezone


STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".state.json"
)


def _connect():
    """Lazy-import the DB driver so the script still runs (and reports
    a clean error) when psycopg2 is missing — instead of crashing at
    `import psycopg2` before printing anything useful."""
    try:
        import psycopg2
    except ModuleNotFoundError:
        sys.stderr.write(
            "sync_gold_layer_state.py: psycopg2 not installed in this venv. "
            "Run bootstrap_hermes_venv.sh on the host.\n"
        )
        sys.exit(2)

    db_host = os.environ.get("DB_HOST")
    db_name = os.environ.get("DB_NAME")
    db_user = os.environ.get("DB_USER")
    db_pwd  = os.environ.get("DB_PASSWORD", "")
    db_port = int(os.environ.get("DB_PORT", 5432))
    if not (db_host and db_name and db_user):
        sys.stderr.write(
            "sync_gold_layer_state.py: DB_HOST / DB_NAME / DB_USER missing. "
            "Source ~/.hermes/profiles/qr_etl/env/etl.env first.\n"
        )
        sys.exit(2)

    if not db_pwd:
        # IAM fallback — only attempted if no static password is set.
        try:
            import boto3
            client = boto3.client(
                "rds", region_name=os.environ.get("DB_REGION", "ap-southeast-1"),
            )
            db_pwd = client.generate_db_auth_token(
                DBHostname=db_host, Port=db_port, DBUsername=db_user,
                Region=os.environ.get("DB_REGION", "ap-southeast-1"),
            )
        except Exception as e:
            sys.stderr.write(
                f"sync_gold_layer_state.py: no DB_PASSWORD and IAM fallback failed: {e}\n"
            )
            sys.exit(2)

    return psycopg2.connect(
        host=db_host, port=db_port, dbname=db_name,
        user=db_user, password=db_pwd, sslmode="require",
    )


def _state_or_stale() -> dict:
    """
    Load .state.json or synthesise an honest 'stale' record.

    Returns a dict that's safe to write to gold_layer_state. The honest
    fallback is critical: a missing state file means the daily refresh
    aborted before write_pipeline_state.py ran, which means data is NOT
    fresh — claiming otherwise misleads downstream consumers.
    """
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)

    return {
        "state": "stale",
        "sources_ok": [],
        "sources_failed": [],
        "locked_since": None,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "stage_counts": {},
        "_note": (
            f".state.json missing at {STATE_FILE}. "
            "daily_refresh.sh likely aborted before write_pipeline_state.py ran. "
            "Defaulting state='stale' so the dashboard does not lie."
        ),
    }


def main() -> int:
    state_doc = _state_or_stale()

    db_state       = state_doc.get("state", "stale")
    sources_ok     = json.dumps(state_doc.get("sources_ok", []))
    sources_failed = json.dumps(state_doc.get("sources_failed", []))
    locked_since   = state_doc.get("locked_since")
    refreshed_at   = state_doc.get("completed_at")
    note           = state_doc.get("_note") or (
        f"Auto-synced from {STATE_FILE} at {datetime.now(timezone.utc).isoformat()}"
    )

    conn = _connect()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE openclaw_researcher.gold_layer_state
                SET state          = %s,
                    sources_ok     = %s::jsonb,
                    sources_failed = %s::jsonb,
                    locked_since   = %s,
                    refreshed_at   = %s,
                    notes          = %s,
                    updated_at     = now()
                WHERE id = 1
                """,
                (db_state, sources_ok, sources_failed,
                 locked_since, refreshed_at, note),
            )
            if cur.rowcount == 0:
                # Singleton row missing — bootstrap it so first-run works.
                cur.execute(
                    """
                    INSERT INTO openclaw_researcher.gold_layer_state
                      (id, state, sources_ok, sources_failed,
                       locked_since, refreshed_at, notes, updated_at)
                    VALUES (1, %s, %s::jsonb, %s::jsonb, %s, %s, %s, now())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (db_state, sources_ok, sources_failed,
                     locked_since, refreshed_at, note),
                )
    finally:
        conn.close()

    print(f"gold_layer_state synced: state={db_state}, "
          f"sources_ok_count={len(state_doc.get('sources_ok', []))}, "
          f"sources_failed_count={len(state_doc.get('sources_failed', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
