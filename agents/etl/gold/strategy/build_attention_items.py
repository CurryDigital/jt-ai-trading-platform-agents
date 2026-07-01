#!/usr/bin/env python3
"""
build_attention_items.py
========================
Populates gold.attention_items (created in db_setup/migrations/002) — the
Action Center on the Command home page. This is the single biggest UX win of
the frontend redesign: structured severity + impact + CTA target, not free text.

Sources unioned (all already exist):
  1. RISK BREACH / demotions   ← gold.audit_events where action ~ 'demot'
                                   or event_type ~ 'mode_change'  → severity by direction
  2. APPROVAL (pending deploy) ← gold.strategy_registry where a strategy is
                                   golden-ish (high conviction) but not yet
                                   approved_at → severity 'warning', tag 'APPROVAL'
  3. DATA staleness            ← gold.source_freshness where a source is
                                   overdue (staleness > expected)  → severity by lateness

Each source maps to the frontend's structured shape:
    severity ∈ {critical, warning, info}
    tag      ∈ {RISK BREACH, APPROVAL, EXPOSURE, DATA, RESEARCH}
    target   ∈ {strategies, execution, settings, research, command}
    ref_id   = the record the CTA deep-links to (strategy_id / order_id / source)

Refresh contract: this builder OWNS the open (unresolved) attention items it
derives — it deletes its own derived rows and re-inserts. Manually-created
items (item_id NOT starting with a derived prefix) are left untouched.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


# Derived items get a prefix so we can safely clear+rebuild only our own rows.
DERIVED_PREFIXES = ('risk_', 'appr_', 'data_')

DELETE_DERIVED_SQL = """
DELETE FROM gold.attention_items
WHERE item_id LIKE 'risk_%'
   OR item_id LIKE 'appr_%'
   OR item_id LIKE 'data_%';
"""

# 1. Risk breaches / demotions from audit_events (last 7 days, open).
INSERT_RISK_SQL = """
INSERT INTO gold.attention_items
    (item_id, severity, tag, title, impact, target, ref_id, created_at)
SELECT
    'risk_' || ae.id                                       AS item_id,
    'critical'                                             AS severity,
    'RISK BREACH'                                          AS tag,
    COALESCE(ae.details->>'title',
             ae.action || ' — ' || COALESCE(ae.details->>'strategy_id','strategy')) AS title,
    COALESCE(ae.details->>'impact',
             ae.details->>'reason',
             'Auto-action logged by risk engine')          AS impact,
    'strategies'                                           AS target,
    ae.details->>'strategy_id'                             AS ref_id,
    ae.event_time                                          AS created_at
FROM gold.audit_events ae
WHERE ae.event_time >= NOW() - INTERVAL '7 days'
  AND (
        ae.action ILIKE '%demot%'
     OR ae.event_type ILIKE '%mode_change%'
     OR ae.event_type ILIKE '%risk%breach%'
  )
ON CONFLICT (item_id) DO NOTHING;
"""

# 2. Golden-ish strategies awaiting deploy approval.
INSERT_APPROVAL_SQL = """
INSERT INTO gold.attention_items
    (item_id, severity, tag, title, impact, target, ref_id, created_at)
SELECT
    'appr_' || sr.strategy_id                              AS item_id,
    'warning'                                              AS severity,
    'APPROVAL'                                             AS tag,
    sr.name || ' ready for deploy'                         AS title,
    'Conviction ' || COALESCE(sr.conviction_score::text,'?')
        || ' · awaiting approval to go live'               AS impact,
    'strategies'                                           AS target,
    sr.strategy_id                                         AS ref_id,
    NOW()                                                  AS created_at
FROM gold.strategy_registry sr
WHERE sr.approved_at IS NULL
  AND sr.retired_at IS NULL
  AND sr.conviction_score IS NOT NULL
  AND sr.conviction_score >= 3.5           -- "golden-ish" threshold on a 0-4 scale
ON CONFLICT (item_id) DO NOTHING;
"""

# 3. Stale data feeds from source_freshness.
INSERT_DATA_SQL = """
INSERT INTO gold.attention_items
    (item_id, severity, tag, title, impact, target, ref_id, created_at)
SELECT
    'data_' || vf.source                                  AS item_id,
    CASE WHEN vf.staleness_hours > vf.expected_max_staleness_hours * 2
         THEN 'critical' ELSE 'warning' END               AS severity,
    'DATA'                                                 AS tag,
    vf.source || ' feed is stale'                          AS title,
    'Last refresh ' || ROUND(vf.staleness_hours::numeric, 1) || 'h ago'
        || ' (SLA ' || vf.expected_max_staleness_hours || 'h)'
        || COALESCE(' · ' || vf.last_error, '')            AS impact,
    'settings'                                             AS target,
    vf.source                                             AS ref_id,
    NOW()                                                  AS created_at
FROM gold.v_source_freshness vf
WHERE vf.freshness_status = 'stale'
ON CONFLICT (item_id) DO NOTHING;
"""


def build() -> int:
    conn = get_connection()
    total = 0
    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_DERIVED_SQL)
            # Each source soft-fails independently: a missing upstream table
            # (e.g. no audit_events yet) shouldn't kill the whole builder.
            for label, sql in (
                ('risk', INSERT_RISK_SQL),
                ('approval', INSERT_APPROVAL_SQL),
                ('data', INSERT_DATA_SQL),
            ):
                try:
                    cur.execute(sql)
                    total += cur.rowcount
                except Exception as e:
                    conn.rollback()
                    print(f"  ⚠️ attention source '{label}' skipped: {e}")
                    # Re-open a clean cursor for the next source.
                    cur = conn.cursor()
        conn.commit()
        print(f"✅ gold.attention_items — {total} derived items (risk + approval + data)")
        return total
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='attention_items',
                asset_class='macro',
                expected_max_staleness_hours=6,
                error=error,
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


if __name__ == "__main__":
    try:
        build()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
