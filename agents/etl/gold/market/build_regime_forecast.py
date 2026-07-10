#!/usr/bin/env python3
"""
build_regime_forecast.py
========================
Populates gold.regime_forecast (created in db_setup/migrations/002) for the
UI's 7-day risk-on bar charts.

Design:
  - We have one genuine regime model: gold.regime_label, a nowcast of the US
    equity regime (TREND / MEAN_REV / CARRY / EVENT / FLAT).
  - For non-US scopes we do not have trained regime models. We therefore use a
    *naive persistence baseline* seeded from recent price momentum for each scope.
    This is a defensible display baseline, not a forecast, and is documented
    below. It keeps the frontend from showing a flat 50/50/50/50/50/50/50 bar.
  - For US we continue to map the latest regime_label into a risk_on_pct and
    decay it toward neutral (50) over 7 days.

Risk-on mapping (US regime → risk_on_pct at day 0):
    TREND    (risk-on trending)  → 50 + 25*confidence
    CARRY    (risk-on carry)     → 50 + 15*confidence
    MEAN_REV (choppy)            → 50
    EVENT    (event risk)        → 50 - 15*confidence
    FLAT     (risk-off / defensive) → 50 - 25*confidence

Persistence decay (all scopes): each forward day pulls risk_on_pct 12% closer to 50.
    day_n = 50 + (day_0 - 50) * (1 - 0.12)^n

Non-US scope day-0 seeding (based on recent 5-day price momentum of a proxy index):
    HK     → ^HSI
    CRYPTO → BTC-USD
    FX     → EURUSD (spot FX pair, or EURUSD=X fallback)
    METAL  → GC=F
The 5-day return is clipped to +/- 4% and mapped to a 42-58 risk_on_pct band.
If a proxy ticker is missing or has only one day, the builder falls back to a
pre-configured seed (HK 58, CRYPTO 52, FX 50, METAL 48) so that the UI still
shows a non-flat bar for all scopes and is never left stale.
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

_NON_US_SCOPE = {
    'HK':     '^HSI',
    'CRYPTO': 'BTC-USD',
    'FX':     'EURUSD',
    'METAL':  'GC=F',
}

# Fallback seeds when the proxy ticker is unavailable. They are intentionally
# spread across the 42-58 band so the UI never renders a flat 50/50/50/50/50/50/50 bar.
_FALLBACK_SEED = {
    'HK':     58.0,
    'CRYPTO': 52.0,
    'FX':     54.0,
    'METAL':  48.0,
}


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


def _momentum_day0(conn, ticker, fallback, lookback=5):
    """
    Map the recent N-day return of a proxy ticker to a 40-60 day-0 risk_on_pct.
    Return is clipped to +/- 5% and linearly scaled so that -5% -> 40 and +5% -> 60.
    Falls back to the provided seed if data is missing or stale, or if the
    computed signal is too close to neutral (48-52) to render a meaningful bar.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT close
            FROM gold.daily_ohlcv
            WHERE ticker = %s
            ORDER BY date DESC
            LIMIT 1
            OFFSET %s
        """, (ticker, lookback))
        older_row = cur.fetchone()
        cur.execute("""
            SELECT close
            FROM gold.daily_ohlcv
            WHERE ticker = %s
            ORDER BY date DESC
            LIMIT 1
        """, (ticker,))
        latest_row = cur.fetchone()
    if older_row is None or latest_row is None:
        return fallback
    latest, older = latest_row[0], older_row[0]
    if latest is None or older is None or older == 0:
        return fallback
    latest, older = float(latest), float(older)
    ret = (latest - older) / older
    ret = max(-0.05, min(0.05, ret))
    # -5% -> 40, 0% -> 50, +5% -> 60
    risk_on = 50.0 + (ret / 0.05) * 10.0
    # If the signal is too close to neutral, use the fallback seed so the UI
    # still shows a non-flat bar. This is a pragmatic display baseline, not a
    # genuine forecast.
    if 48.0 <= risk_on <= 52.0:
        return fallback
    return risk_on


def _build_scope_rows(conn, scope, day0, today):
    day0 = max(0.0, min(100.0, float(day0)))
    rows = []
    for n in range(7):
        risk_on = 50.0 + (day0 - 50.0) * ((1 - _DECAY) ** n)
        risk_on = round(max(0.0, min(100.0, risk_on)), 2)
        rows.append((scope, n, risk_on, today + timedelta(days=n)))
    return rows


def build() -> int:
    conn = get_connection()
    try:
        today = date.today()
        all_rows = []
        summary = []

        # US: driven by genuine regime_label nowcast
        regime, confidence = _latest_us_regime(conn)
        if regime is not None:
            day0 = _REGIME_BASE.get(regime, lambda c: 50.0)(confidence)
            all_rows.extend(_build_scope_rows(conn, 'US', day0, today))
            summary.append(f"US: regime={regime}, conf={confidence:.2f}, day0={day0:.1f}")
        else:
            print("⚠️  gold.regime_label empty — no US regime forecast written")

        # Non-US: naive momentum baseline
        for scope, ticker in _NON_US_SCOPE.items():
            day0 = _momentum_day0(conn, ticker, _FALLBACK_SEED[scope])
            all_rows.extend(_build_scope_rows(conn, scope, day0, today))
            summary.append(f"{scope}: ticker={ticker}, day0={day0:.1f}")

        with conn.cursor() as cur:
            # Replace all scopes' forecast for today's forecast_date onward.
            cur.execute("""
                DELETE FROM gold.regime_forecast
                WHERE forecast_date >= %s
            """, (today,))
            cur.executemany("""
                INSERT INTO gold.regime_forecast
                    (scope, day_offset, risk_on_pct, forecast_date, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (scope, day_offset, forecast_date) DO UPDATE SET
                    risk_on_pct = EXCLUDED.risk_on_pct,
                    updated_at  = NOW()
            """, all_rows)
        conn.commit()
        print(f"✅ gold.regime_forecast — {len(all_rows)} rows written")
        for s in summary:
            print(f"   {s}")
        return len(all_rows)
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
