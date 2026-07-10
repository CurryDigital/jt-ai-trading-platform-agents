#!/usr/bin/env python3
"""
build_risk_limits.py
====================
Ensures gold.risk_limits_facts has a sane global row and refreshes any
strategy-specific limits from the current strategy registry. The platform
reads gold.risk_limits (a view over this table) for the kill-switch panel.

Current logic:
  - Global row: halt_phrase_set=FALSE, global_halt=FALSE, capital_cap_pct=NULL,
    used_pct=NULL (no portfolio-derived capital cap is implemented yet).
  - Per-strategy rows: one row per non-retired strategy in gold.strategy_registry
    with default halt_phrase_set=FALSE, global_halt=FALSE.

Pipeline: daily refresh (gold/market/*.py sweep).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


ENSURE_GLOBAL_SQL = """
INSERT INTO gold.risk_limits_facts (strategy_id, halt_phrase_set, global_halt, capital_cap_pct, used_pct, updated_at)
VALUES (NULL, FALSE, FALSE, NULL, NULL, NOW())
ON CONFLICT DO NOTHING;
"""

UPSERT_STRATEGY_SQL = """
INSERT INTO gold.risk_limits_facts (strategy_id, halt_phrase_set, global_halt, capital_cap_pct, used_pct, updated_at)
SELECT strategy_id, FALSE, FALSE, NULL, NULL, NOW()
FROM gold.strategy_registry
WHERE retired_at IS NULL
ON CONFLICT (strategy_id) WHERE strategy_id IS NOT NULL DO UPDATE SET
    updated_at = NOW();
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ENSURE_GLOBAL_SQL)
            cur.execute(UPSERT_STRATEGY_SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.risk_limits_facts — {n} strategy rows refreshed, global row ensured")
        return n
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='risk_limits',
                asset_class='execution',
                expected_max_staleness_hours=24,
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
