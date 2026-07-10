#!/usr/bin/env python3
"""
build_market_sentiment.py
=========================
Populates gold.market_sentiment_facts (one row per region: US, HK).

Output schema (per region):
    region, fear_greed, fear_greed_label, vix, vix_change_pct,
    put_call, regime, vix_sma60, vix_z60, updated_at

Sources today:
    US
      vix/vix_sma60/vix_z60 → gold.vix_regime (latest row)
      vix_change_pct        → derived from yesterday vs today close
      fear_greed            → derived from VIX z-score band
      regime                → latest gold.regime_label.regime

    HK
      HSI close/ma_50/ma_200/volatility_21d → gold.index_metrics ^HSI
      fear_greed            → HK stress model: vol z-score + 21d return
      regime                → technical rule on HSI trend
      vix* columns          → NULL (no HK VIX feed wired)

The placeholder F&G for US is documented as such; replace the CASE in this
file once a real F&G ingest lands.  HK sentiment is a best-effort proxy
until a dedicated HK fear/greed feed is available.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


SQL = """
WITH us_today AS (
    SELECT date, vix, vix_sma60, vix_z60
    FROM   gold.vix_regime
    ORDER  BY date DESC
    LIMIT  1
),
us_yesterday AS (
    SELECT vix
    FROM   gold.vix_regime
    WHERE  date < (SELECT date FROM us_today)
    ORDER  BY date DESC
    LIMIT  1
),
us_regime AS (
    SELECT regime
    FROM   gold.regime_label
    ORDER  BY date DESC
    LIMIT  1
),
us_calc AS (
    SELECT
        'US'::varchar(8) AS region,
        1 AS id,
        t.vix,
        CASE WHEN y.vix IS NULL OR y.vix = 0 THEN NULL
             ELSE ROUND((t.vix / y.vix - 1.0) * 100.0, 4)
        END AS vix_change_pct,
        t.vix_sma60,
        t.vix_z60,
        CASE
            WHEN t.vix_z60 IS NULL          THEN 50
            WHEN t.vix_z60 >   1.5          THEN 15
            WHEN t.vix_z60 >   0.5          THEN 35
            WHEN t.vix_z60 >  -0.5          THEN 50
            WHEN t.vix_z60 >  -1.5          THEN 70
            ELSE                                 85
        END AS fear_greed,
        CASE
            WHEN t.vix_z60 IS NULL          THEN 'Neutral'
            WHEN t.vix_z60 >   1.5          THEN 'Extreme Fear'
            WHEN t.vix_z60 >   0.5          THEN 'Fear'
            WHEN t.vix_z60 >  -0.5          THEN 'Neutral'
            WHEN t.vix_z60 >  -1.5          THEN 'Greed'
            ELSE                                 'Extreme Greed'
        END AS fear_greed_label,
        r.regime
    FROM us_today t
    LEFT JOIN us_yesterday y ON TRUE
    LEFT JOIN us_regime    r ON TRUE
),
hk_all AS (
    SELECT date, close, ma_50, ma_200, volatility_21d,
           LAG(close, 21) OVER (ORDER BY date) AS close_21d_ago
    FROM   gold.index_metrics
    WHERE  ticker = '^HSI'
),
hk_today AS (
    SELECT * FROM hk_all
    ORDER  BY date DESC
    LIMIT  1
),
hk_vol_stats AS (
    SELECT AVG(volatility_21d) AS vol_sma60,
           STDDEV(volatility_21d) AS vol_std60
    FROM   (
        SELECT volatility_21d
        FROM   gold.index_metrics
        WHERE  ticker = '^HSI'
        ORDER  BY date DESC
        LIMIT  60
    ) x
),
hk_calc AS (
    SELECT
        'HK'::varchar(8) AS region,
        2 AS id,
        NULL::numeric AS vix,
        NULL::numeric AS vix_change_pct,
        NULL::numeric AS vix_sma60,
        NULL::numeric AS vix_z60,
        GREATEST(0, LEAST(100,
            50
            - COALESCE((t.volatility_21d - s.vol_sma60)
                       / NULLIF(s.vol_std60, 0) * 15, 0)
            + COALESCE((t.close - t.close_21d_ago)
                       / NULLIF(t.close_21d_ago, 0) * 200, 0)
        ))::int AS fear_greed,
        CASE
            WHEN GREATEST(0, LEAST(100,
                50
                - COALESCE((t.volatility_21d - s.vol_sma60)
                           / NULLIF(s.vol_std60, 0) * 15, 0)
                + COALESCE((t.close - t.close_21d_ago)
                           / NULLIF(t.close_21d_ago, 0) * 200, 0)
            )) <= 20 THEN 'Extreme Fear'
            WHEN GREATEST(0, LEAST(100,
                50
                - COALESCE((t.volatility_21d - s.vol_sma60)
                           / NULLIF(s.vol_std60, 0) * 15, 0)
                + COALESCE((t.close - t.close_21d_ago)
                           / NULLIF(t.close_21d_ago, 0) * 200, 0)
            )) <= 40 THEN 'Fear'
            WHEN GREATEST(0, LEAST(100,
                50
                - COALESCE((t.volatility_21d - s.vol_sma60)
                           / NULLIF(s.vol_std60, 0) * 15, 0)
                + COALESCE((t.close - t.close_21d_ago)
                           / NULLIF(t.close_21d_ago, 0) * 200, 0)
            )) <= 60 THEN 'Neutral'
            WHEN GREATEST(0, LEAST(100,
                50
                - COALESCE((t.volatility_21d - s.vol_sma60)
                           / NULLIF(s.vol_std60, 0) * 15, 0)
                + COALESCE((t.close - t.close_21d_ago)
                           / NULLIF(t.close_21d_ago, 0) * 200, 0)
            )) <= 80 THEN 'Greed'
            ELSE 'Extreme Greed'
        END AS fear_greed_label,
        CASE
            WHEN s.vol_std60 IS NOT NULL AND s.vol_std60 > 0
                 AND (t.volatility_21d - s.vol_sma60) / s.vol_std60 > 1.5
                 THEN 'FLAT'
            WHEN t.close > t.ma_50
                 AND t.close_21d_ago IS NOT NULL
                 AND t.close > t.close_21d_ago
                 THEN 'TREND'
            WHEN t.close < t.ma_50
                 AND t.close_21d_ago IS NOT NULL
                 AND t.close < t.close_21d_ago
                 THEN 'FLAT'
            ELSE 'MEAN_REV'
        END AS regime
    FROM hk_today t
    CROSS JOIN hk_vol_stats s
),
combined AS (
    SELECT region, id, fear_greed, fear_greed_label, vix, vix_change_pct,
           vix_sma60, vix_z60, regime
    FROM us_calc
    UNION ALL
    SELECT region, id, fear_greed, fear_greed_label, vix, vix_change_pct,
           vix_sma60, vix_z60, regime
    FROM hk_calc
)
INSERT INTO gold.market_sentiment_facts
    (region, id, fear_greed, fear_greed_label, vix, vix_change_pct,
     put_call, vix_sma60, vix_z60, regime, updated_at)
SELECT
    region, id, fear_greed, fear_greed_label, vix, vix_change_pct,
    NULL, vix_sma60, vix_z60, regime, NOW()
FROM combined
ON CONFLICT (region) DO UPDATE SET
    id               = EXCLUDED.id,
    fear_greed       = EXCLUDED.fear_greed,
    fear_greed_label = EXCLUDED.fear_greed_label,
    vix              = EXCLUDED.vix,
    vix_change_pct   = EXCLUDED.vix_change_pct,
    -- put_call deliberately not overwritten — a real feed can fill it independently.
    vix_sma60        = EXCLUDED.vix_sma60,
    vix_z60          = EXCLUDED.vix_z60,
    regime           = EXCLUDED.regime,
    updated_at       = EXCLUDED.updated_at;
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL)
            n = cur.rowcount
        conn.commit()
        print(f"✅ gold.market_sentiment_facts — {n} row(s) upserted (US + HK)")
        return n
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='market_sentiment',
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
