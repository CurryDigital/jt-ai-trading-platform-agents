#!/usr/bin/env python3
"""
Consumption: Lab Tab — Research Signals, Seasonality, SUE Scores
Reads from: gold.seasonality_patterns, gold.sue_scores, gold.research_signals,
            gold.earnings_signals, silver.unified_earnings, silver.asset_registry
Writes to:  consumption.research_seasonality_patterns
            consumption.research_sue_scores
            consumption.research_contrarian_signals
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# ── Seasonality Patterns ──────────────────────────────────────────────────────

SEASONALITY_SQL = """
INSERT INTO consumption.research_seasonality_patterns
    (ticker, name, asset_class,
     current_month, current_month_bias, current_month_historical_return, current_month_win_rate,
     next_month, next_month_bias, next_month_historical_return,
     monthly_patterns_json, updated_at)
WITH current_month AS (
    SELECT
        sp.ticker,
        ar.name,
        sp.asset_class,
        EXTRACT(MONTH FROM CURRENT_DATE)::int     AS current_month,
        EXTRACT(MONTH FROM CURRENT_DATE + 30)::int AS next_month
    FROM gold.seasonality_patterns sp
    LEFT JOIN gold.asset_registry ar ON ar.ticker = sp.ticker
    GROUP BY sp.ticker, ar.name, sp.asset_class
),
monthly_agg AS (
    SELECT
        ticker,
        jsonb_object_agg(
            month::text,
            jsonb_build_object(
                'avg_return', avg_return_pct,
                'win_rate',   win_rate,
                'std_dev',    std_dev,
                'bias',       seasonal_bias,
                'sample',     sample_size
            )
        ) AS monthly_patterns_json
    FROM gold.seasonality_patterns
    GROUP BY ticker
)
SELECT
    cm.ticker,
    cm.name,
    cm.asset_class,
    cm.current_month,
    cur.seasonal_bias        AS current_month_bias,
    cur.avg_return_pct       AS current_month_historical_return,
    cur.win_rate             AS current_month_win_rate,
    cm.next_month,
    nxt.seasonal_bias        AS next_month_bias,
    nxt.avg_return_pct       AS next_month_historical_return,
    ma.monthly_patterns_json,
    NOW()
FROM current_month cm
LEFT JOIN gold.seasonality_patterns cur
    ON cur.ticker = cm.ticker AND cur.month = cm.current_month
LEFT JOIN gold.seasonality_patterns nxt
    ON nxt.ticker = cm.ticker AND nxt.month = cm.next_month
LEFT JOIN monthly_agg ma ON ma.ticker = cm.ticker
ON CONFLICT (ticker) DO UPDATE SET
    current_month_bias                = EXCLUDED.current_month_bias,
    current_month_historical_return   = EXCLUDED.current_month_historical_return,
    current_month_win_rate            = EXCLUDED.current_month_win_rate,
    next_month_bias                   = EXCLUDED.next_month_bias,
    next_month_historical_return      = EXCLUDED.next_month_historical_return,
    monthly_patterns_json             = EXCLUDED.monthly_patterns_json,
    updated_at                        = NOW();
"""

# ── SUE Scores ────────────────────────────────────────────────────────────────

SUE_SQL = """
INSERT INTO consumption.research_sue_scores
    (ticker, name, report_date,
     eps_estimate, eps_actual, eps_surprise_pct,
     sue_score, sue_decile, sue_category,
     price_change_1d, price_change_3d, price_change_5d,
     drift_signal, sector, market_cap, updated_at)
SELECT
    ue.ticker,
    ar.name,
    ue.report_date,
    ue.eps_estimate,
    ue.eps_actual,
    ue.eps_surprise_pct,
    ue.sue_score,
    ue.sue_decile,
    ue.sue_category,
    -- Price changes post-earnings
    ROUND(
        (p1.close / NULLIF(p0.close, 0) - 1) * 100, 4
    ) AS price_change_1d,
    ROUND(
        (p3.close / NULLIF(p0.close, 0) - 1) * 100, 4
    ) AS price_change_3d,
    ROUND(
        (p5.close / NULLIF(p0.close, 0) - 1) * 100, 4
    ) AS price_change_5d,
    CASE
        WHEN ue.sue_score > 1  THEN 'DRIFT_UP'
        WHEN ue.sue_score < -1 THEN 'DRIFT_DOWN'
        ELSE 'NEUTRAL'
    END AS drift_signal,
    gold_ar.sector,
    NULL::bigint AS market_cap,
    NOW()
FROM silver.unified_earnings ue
LEFT JOIN silver.asset_registry ar ON ar.ticker = ue.ticker
LEFT JOIN gold.asset_registry gold_ar ON gold_ar.ticker = ue.ticker
-- Price on earnings day
LEFT JOIN silver.unified_prices p0
    ON p0.ticker = ue.ticker AND p0.date = ue.report_date
-- Price 1 day after
LEFT JOIN silver.unified_prices p1
    ON p1.ticker = ue.ticker AND p1.date = (
        SELECT MIN(date) FROM silver.unified_prices
        WHERE ticker = ue.ticker AND date > ue.report_date
    )
-- Price 3 days after
LEFT JOIN silver.unified_prices p3
    ON p3.ticker = ue.ticker AND p3.date = (
        SELECT MIN(date) FROM silver.unified_prices
        WHERE ticker = ue.ticker
          AND date > (SELECT MIN(date) FROM silver.unified_prices
                      WHERE ticker = ue.ticker AND date > ue.report_date)
          AND date > (SELECT MIN(date) FROM silver.unified_prices
                      WHERE ticker = ue.ticker AND date > ue.report_date)
    )
-- Price 5 days after (simplified)
LEFT JOIN silver.unified_prices p5
    ON p5.ticker = ue.ticker AND p5.date = (
        SELECT date FROM silver.unified_prices
        WHERE ticker = ue.ticker AND date > ue.report_date
        ORDER BY date LIMIT 1 OFFSET 4
    )
WHERE ue.sue_score IS NOT NULL
ORDER BY ABS(ue.sue_score) DESC NULLS LAST
ON CONFLICT (ticker, report_date) DO UPDATE SET
    sue_score        = EXCLUDED.sue_score,
    sue_decile       = EXCLUDED.sue_decile,
    sue_category     = EXCLUDED.sue_category,
    price_change_1d  = EXCLUDED.price_change_1d,
    price_change_3d  = EXCLUDED.price_change_3d,
    price_change_5d  = EXCLUDED.price_change_5d,
    drift_signal     = EXCLUDED.drift_signal,
    updated_at       = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SEASONALITY_SQL)
    print(f"✅ consumption.research_seasonality_patterns — {cur.rowcount} rows upserted")

    cur.execute(SUE_SQL)
    print(f"✅ consumption.research_sue_scores — {cur.rowcount} rows upserted")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
