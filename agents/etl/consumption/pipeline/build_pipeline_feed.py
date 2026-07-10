#!/usr/bin/env python3
"""
Pipeline UI JSON feed builder.

Reads from gold.v_pipeline_ui_feed and writes a JSON artifact that the frontend
Pipeline UI consumes.  The shape matches StrategyPipeline.jsx card props.

Output paths (overwrites):
  - /home/ubuntu/jtcml_new_frontend/ui_kits/jtcml-workspace/pipeline_feed.json
  - /home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/consumption/pipeline/pipeline_feed.json

Status mapping (DB -> UI stage):
  approved      -> deployed
  risk_review   -> golden
  backtesting   -> near_golden
  rejected      -> experimental
"""
import os
import sys
import json
from datetime import datetime, timezone

# Use shadow workspace for source imports per user hard rule
ETL_HOME = os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl'
)
SHARED = os.path.join(ETL_HOME, 'shared', 'scripts')
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

from db import get_connection  # noqa: E402


def fetch_pipeline_feed(cur) -> list:
    cur.execute("""
        SELECT
            id,
            name,
            asset,
            horizon,
            tier,
            stage,
            btWR,
            liveWR,
            btPF,
            livePF,
            trades,
            returns,
            sharpe,
            dd,
            mode,
            margin,
            db_status,
            frequency,
            agent_source
        FROM gold.v_pipeline_ui_feed
        ORDER BY stage, updated_at DESC
    """)
    cols = [desc[0] for desc in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    return rows


def main():
    rows = []
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        rows = fetch_pipeline_feed(cur)
        cur.close()
    finally:
        if conn is not None:
            conn.close()

    payload = {
        'data': rows,
        'stage_counts': {
            'experimental': sum(1 for r in rows if r['stage'] == 'experimental'),
            'near_golden': sum(1 for r in rows if r['stage'] == 'near_golden'),
            'golden': sum(1 for r in rows if r['stage'] == 'golden'),
            'deployed': sum(1 for r in rows if r['stage'] == 'deployed'),
            'total': len(rows),
        },
        'as_of': datetime.now(timezone.utc).isoformat(),
    }

    out_paths = [
        os.path.join(
            ETL_HOME, 'consumption', 'pipeline', 'pipeline_feed.json'
        ),
        '/home/ubuntu/jtcml_new_frontend/ui_kits/jtcml-workspace/pipeline_feed.json',
    ]

    for path in out_paths:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"wrote {path} — {len(rows)} strategies")


if __name__ == '__main__':
    main()
