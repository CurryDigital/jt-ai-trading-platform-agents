#!/usr/bin/env python3
"""
build_regime_forecast.py
========================
Populates gold.regime_forecast (created in db_setup/migrations/002) for the
UI's 7-day risk-on bar charts.

⚠️  HONEST SCOPE LIMITATION — READ THIS:
We have exactly ONE regime model: gold.regime_label, a NOWCAST of the US
equity regime (TREND / MEAN_REV / CARRY / EVENT / FLAT). We do NOT have:
  - a genuine forward FORECAST model (regime_label is today's state, not a projection)
  - regime models for HK / CRYPTO / FX / METAL

So this builder:
  1. Populates scope='US' with a PERSISTENCE BASELINE: it converts today's
     regime + confidence into a risk_on_pct, then projects the next 7 days
     as that value decaying toward neutral (50) — i.e. "we expect today's
     regime to persist, with rising uncertainty." This is a defensible naive
     baseline, NOT a trained forecast. The decay rate is documented below.
  2. Does NOT write HK/CRYPTO/FX/METAL. Those scopes stay empty until real
     per-scope regime models exist. The UI shows an honest empty state for
     them rather than a fabricated risk-on number in a trading terminal.

When a real multi-scope forecast model lands (likely from
agents/signals/regime/), replace the body of build() with its output.

Risk-on mapping (US regime → risk_on_pct at day 0):
    TREND    (risk-on trending)  → 50 + 25*confidence
    CARRY    (risk-on carry)     → 50 + 15*confidence
    MEAN_REV (choppy)            → 50
    EVENT    (event risk)        → 50 - 15*confidence
    FLAT     (risk-off / defensive) → 50 - 25*confidence

Persistence decay: each forward day pulls risk_on_pct 12% closer to 50.
    day_n = 50 + (day_0 - 50) * (1 - 0.12)^n
"""

import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


# risk_on_pct at forecast day 0, per regime label. Confidence scales the
# distance from neutral.
_REGIME_BASE = {
    'TREND':    lambda c: 50 + 25 * c,
    'CARRY':    lambda c: 50 + 15 * c,
    'MEAN_REV': lambda c: 50.0,
    'EVENT':    lambda c: 50 - 15 * c,
    'FLAT':     lambda c: 50 - 25 * c,
}
_DECAY = 0.12  # each forward day pulls 12% toward neutral


def _latest_us_regime(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT regime, confidence
            FROM   gold.regime_label
            WHERE  date = (SELECT MAX(date) FROM gold.regime_label)
        """)
        row = cur.fetchone()
    if not row:
        return None, None
    regime, confidence = row
    return regime, float(confidence) if confidence is not None else 0.5


def build() -> int:
    conn = get_connection()
    try:
        regime, confidence = _latest_us_regime(conn)
        if regime is None:
            print("⚠️  gold.regime_label empty — no US regime forecast written")
            return 0

        base_fn = _REGIME_BASE.get(regime, lambda c: 50.0)
        day0 = base_fn(confidence)
        day0 = max(0.0, min(100.0, day0))

        today = date.today()
        rows = []
        for n in range(7):
            risk_on = 50.0 + (day0 - 50.0) * ((1 - _DECAY) ** n)
            risk_on = round(max(0.0, min(100.0, risk_on)), 2)
            rows.append(('US', n, risk_on, today + timedelta(days=n)))

        with conn.cursor() as cur:
            # Replace this scope's forecast for today's forecast_date.
            cur.execute("""
                DELETE FROM gold.regime_forecast
                WHERE scope = 'US' AND forecast_date >= %s
            """, (today,))
            cur.executemany("""
                INSERT INTO gold.regime_forecast
                    (scope, day_offset, risk_on_pct, forecast_date, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (scope, day_offset, forecast_date) DO UPDATE SET
                    risk_on_pct = EXCLUDED.risk_on_pct,
                    updated_at  = NOW()
            """, rows)
        conn.commit()
        print(f"✅ gold.regime_forecast — US persistence baseline written "
              f"(regime={regime}, conf={confidence:.2f}, day0={day0:.1f})")
        print("   (HK/CRYPTO/FX/METAL intentionally empty — no model)")
        return len(rows)
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='regime_forecast',
                asset_class='macro',
                expected_max_staleness_hours=30,
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
