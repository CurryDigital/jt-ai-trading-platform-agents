#!/usr/bin/env python3
"""
build_signal_redesign.py
========================
Populates the redesign signal-consumption tables. This script is the bridge
between the signal pipeline (strategy_ticker_scores) and the v2 frontend
views (consumption.signal_setups, consumption.signal_proximity,
consumption.signal_feed).

Reads from:
  - gold.strategy_ticker_scores
  - gold.strategy_registry
  - gold.asset_registry / gold.kpis_metrics

Writes to:
  - gold.signal_evaluations
  - gold.signal_proximity_facts

Does NOT write:
  - gold.signal_family_performance — hit_rate / fwd_return_5d are MEASURED
    quantities (realized outcomes of past signals). No trade-outcome ledger
    exists yet to measure them from, so this builder does not populate the
    table. The frontend's contract (QR_ETL_HANDOFF.md) is explicit that an
    empty panel means missing data, not a bug — an empty performance panel
    is the correct, honest state until outcomes are tracked.

2026-07-10: removed the DEMO_EVALUATIONS / DEMO_PERFORMANCE fallback that
seeded hard-coded fake BUY signals ("NVDA momentum 0.91 — AI demand") and
invented hit rates (0.58 + potential/1000) into gold whenever the real
pipeline produced no actionable signals. On a live trading dashboard a
quiet day must LOOK quiet; fabricated signals presented as real ones are
worse than an empty panel. Also removed INSERT_REAL_EVALUATIONS_SQL, which
was dead code and invalid SQL (it called the Python helper
map_strategy_to_family() inside the query text).

Pipeline: signal generation cycle (run_signal_cycle.sh, AFTER run_signals.py).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIGNALS_ROOT = os.path.normpath(os.path.join(HERE, '..'))
ETL_SHARED = os.path.normpath(os.path.join(SIGNALS_ROOT, '..', 'etl', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
sys.path.insert(0, SIGNALS_ROOT)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


# strategy_id → family_key mapping, applied in SQL via a CASE expression
# rendered from this single table (kept in one place so the WHERE filter and
# the SELECT can't drift apart, which is how the previous version ended up
# with two 12-branch copies of the same CASE).
STRATEGY_KEYWORD_TO_FAMILY = [
    ('momentum',    'momentum'),
    ('macd',        'momentum'),
    ('mean_rev',    'mean_rev'),
    ('contrarian',  'mean_rev'),
    ('breakout',    'breakout'),
    ('donchian',    'breakout'),
    ('earnings',    'earnings'),
    ('pead',        'earnings'),
    ('trend',       'trend'),
    ('carry',       'trend'),
    ('drift',       'trend'),
    ('tactical',    'tactical'),
    ('multi_asset', 'tactical'),
    ('etf',         'tactical'),
    ('nfp',         'Macro Breakout'),
    ('macro',       'Macro Breakout'),
    ('vix',         'Regime Carry'),
    ('regime',      'Regime Carry'),
    ('gap',         'Gap Reversal'),
    ('sue',         'Seasonal SUE'),
    ('seasonal',    'Seasonal SUE'),
    ('btc',         'momentum'),
    ('crypto',      'momentum'),
    ('HK_Quality',  'hk_paper_v1'),
]


def _family_case_sql() -> str:
    branches = "\n".join(
        f"    WHEN sts.strategy_id ILIKE '%%{kw}%%' THEN '{fam}'"
        for kw, fam in STRATEGY_KEYWORD_TO_FAMILY
    )
    return f"CASE\n{branches}\n    ELSE NULL\nEND"


DELETE_SQL = """
DELETE FROM gold.signal_evaluations;
DELETE FROM gold.signal_proximity_facts;
"""

INSERT_EVALUATIONS_SQL = f"""
INSERT INTO gold.signal_evaluations
    (market, ticker, name, family_key, direction, potential, change_pct, note, updated_at)
SELECT DISTINCT ON (market, ticker, family_key)
    market, ticker, name, family_key, direction, potential, change_pct, note, NOW()
FROM (
    SELECT
        CASE
            WHEN ar.market = 'HK' THEN 'HK'
            WHEN ar.asset_class IN ('CRYPTO','CRYPTOCURRENCY') THEN 'CRYPTO'
            WHEN ar.asset_class IN ('FX','CURRENCY') THEN 'FX'
            WHEN ar.ticker IN ('GC=F','SI=F','CL=F','NG=F','HG=F') THEN 'METAL'
            ELSE 'US'
        END AS market,
        sts.ticker,
        COALESCE(ar.name, sts.ticker) AS name,
        {_family_case_sql().replace(chr(10), chr(10) + '        ')} AS family_key,
        CASE WHEN sts.signal_action = 'BUY' THEN 'BUY' ELSE 'SELL' END AS direction,
        ROUND(LEAST(100.0, GREATEST(0.0, sts.score))::numeric, 2) AS potential,
        ROUND(COALESCE(k.change_1d, 0)::numeric, 2) AS change_pct,
        LEFT(COALESCE(sts.criteria_met::text, 'Scored by ' || sts.strategy_id), 200) AS note
    FROM gold.strategy_ticker_scores sts
    JOIN gold.strategy_registry sr ON sr.strategy_id = sts.strategy_id
    JOIN gold.asset_registry ar ON ar.ticker = sts.ticker
    LEFT JOIN LATERAL (
        SELECT change_1d FROM gold.kpis_metrics WHERE ticker = sts.ticker ORDER BY date DESC LIMIT 1
    ) k ON TRUE
    WHERE sts.signal_action IN ('BUY','SELL')
) mapped
WHERE family_key IS NOT NULL
ORDER BY market, ticker, family_key, potential DESC
ON CONFLICT (market, ticker, family_key) DO UPDATE SET
    name = EXCLUDED.name,
    direction = EXCLUDED.direction,
    potential = EXCLUDED.potential,
    change_pct = EXCLUDED.change_pct,
    note = EXCLUDED.note,
    updated_at = NOW();
"""

INSERT_PROXIMITY_SQL = """
INSERT INTO gold.signal_proximity_facts
    (market, ticker, family_key, distance_pct, direction, updated_at)
SELECT
    market,
    ticker,
    family_key,
    ROUND(100.0 - LEAST(100.0, potential), 2) AS distance_pct,
    direction,
    NOW()
FROM gold.signal_evaluations
ON CONFLICT (market, ticker, family_key) DO UPDATE SET
    distance_pct = EXCLUDED.distance_pct,
    direction = EXCLUDED.direction,
    updated_at = NOW();
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL)
            cur.execute(INSERT_EVALUATIONS_SQL)
            n_eval = cur.rowcount
            cur.execute(INSERT_PROXIMITY_SQL)
            n_prox = cur.rowcount
        conn.commit()
        if n_eval == 0:
            # A quiet day looks quiet. Do not backfill with fabricated
            # signals — the frontend renders empty panels by contract.
            print("ℹ️  signal redesign — 0 actionable BUY/SELL signals today; "
                  "signal_evaluations/proximity left empty (honest state)")
        else:
            print(f"✅ signal redesign — evaluations={n_eval}, proximity={n_prox}")
        return n_eval + n_prox
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='signal_redesign',
                asset_class='signals',
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
