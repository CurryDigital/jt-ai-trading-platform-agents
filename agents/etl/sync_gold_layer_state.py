#!/usr/bin/env python3
"""
sync_gold_layer_state.py
Reads .state.json from ETL manager workspace and syncs to openclaw_researcher.gold_layer_state.
Run at the end of daily_refresh.sh.
"""

import json
import os
import sys
import boto3
import psycopg2

STATE_FILE = os.path.join(
    os.path.dirname(__file__),
    "../qr_etl_manager/.state.json"
)

DB_HOST   = os.environ["DB_HOST"]
DB_PORT   = int(os.environ.get("DB_PORT", 5432))
DB_NAME   = os.environ["DB_NAME"]
DB_USER   = os.environ["DB_USER"]
DB_REGION = os.environ.get("DB_REGION", "ap-southeast-1")

def get_password():
    # Try static password first (TOOLS.md: Standard Static Password)
    if os.environ.get("DB_PASSWORD"):
        return os.environ["DB_PASSWORD"]
    # Fallback to IAM auth token
    try:
        client = boto3.client("rds", region_name=DB_REGION)
        return client.generate_db_auth_token(
            DBHostname=DB_HOST,
            Port=DB_PORT,
            DBUsername=DB_USER,
            Region=DB_REGION
        )
    except Exception as e:
        print(f"WARNING: Failed to generate IAM auth token: {e}")
        return ""

def main():
    if not os.path.exists(STATE_FILE):
        print(f"ERROR: state file not found: {STATE_FILE}")
        sys.exit(1)

    with open(STATE_FILE) as f:
        state = json.load(f)

    db_state      = state.get("state", "stale")
    sources_ok    = json.dumps(state.get("sources_ok", []))
    sources_failed = json.dumps([
        s["source"] for s in state.get("sources_failed", [])
    ])
    locked_since  = state.get("locked_since")  # None or ISO string
    refreshed_at  = state.get("completed_at")

    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=get_password(), sslmode="require"
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        UPDATE openclaw_researcher.gold_layer_state
        SET state          = %s,
            sources_ok     = %s::jsonb,
            sources_failed = %s::jsonb,
            locked_since   = %s,
            refreshed_at   = %s,
            notes          = 'Auto-synced from ETL .state.json',
            updated_at     = now()
        WHERE id = 1
    """, (db_state, sources_ok, sources_failed, locked_since, refreshed_at))

    print(f"✅ gold_layer_state synced: state={db_state}, "
          f"sources_ok={state.get('sources_ok')}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
