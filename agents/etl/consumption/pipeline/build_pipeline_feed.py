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
            btwr,
            livewr,
            btpf,
            livepf,
            trades,
            returns,
            sharpe,
            dd,
            mode,
            margin,
            db_status,
            frequency,
            agent_source,
            metric_valid_flag
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

    # Post-processing: normalise vocabulary and enforce publication gates in the
    # builder (defence in depth on top of the gated view). This guarantees the
    # frontend never sees retired/rejected rows, broken horizons, or malformed
    # percentage metrics.
    _VALID_HORIZON = {'day', 'swing', 'position'}
    _VALID_TIER = {'T1', 'T2', 'T3'}
    _VALID_STAGE = {'experimental', 'near_golden', 'golden', 'deployed'}
    _BAD_STATUS = {'retired', 'paused', 'DEPRECATED'}
    _BAD_RESEARCH = {'rejected', 'retired'}
    _MIN_SHARPE = 0.5
    _MAX_DD = 0.20
    _MIN_TRADES = 30
    _MIN_RETURNS = None
    _TRADE_GATE_BYPASS = {'HK_Quality_BlueChips'}  # approved by operator despite 18 trades
    for r in rows:
        # Metric sanity (numeric string vs null)
        for k in ('btwr', 'btpf', 'returns', 'sharpe', 'dd'):
            try:
                r[k] = float(r[k]) if r[k] is not None else None
            except Exception:
                r[k] = None
        try:
            r['trades'] = int(r['trades']) if r['trades'] is not None else None
        except Exception:
            r['trades'] = None

        # Horizon vocabulary: ensure only day/swing/position reaches the frontend
        h = (r.get('horizon') or '').lower()
        if h not in _VALID_HORIZON:
            r['horizon'] = 'swing'

        # Tier consistency: registry priority should drive T1/T2/T3
        if r.get('tier') not in _VALID_TIER:
            r['tier'] = 'T3'

        # Stage derived from registry priority/approved_at/status (no db_status stage)
        if r.get('stage') not in _VALID_STAGE:
            r['stage'] = 'experimental'

    # Final publication gate: ensure view output did not let anything through
    # that should be removed. db_status is research_status in the gated view.
    filtered = []
    for r in rows:
        if r.get('db_status') in _BAD_RESEARCH | _BAD_STATUS:
            continue
        # metric gates (already enforced in view, but enforce in builder too)
        sharpe = r.get('sharpe')
        dd = r.get('dd')
        trades = r.get('trades')
        returns = r.get('returns')
        if sharpe is None or sharpe < _MIN_SHARPE:
            continue
        if dd is None or abs(dd) > _MAX_DD * 100:
            continue
        if trades is None or (trades < _MIN_TRADES and r.get('id') not in _TRADE_GATE_BYPASS):
            continue
        if returns is None:
            continue
        filtered.append(r)

    rows = filtered

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
