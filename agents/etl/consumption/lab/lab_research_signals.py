#!/usr/bin/env python3
"""
Consumption: Lab Tab — Research Signals, SUE Scores, Seasonality, Contrarian
Reads from: gold.sue_scores, gold.seasonality_patterns, gold.earnings_signals,
            gold.asset_registry, silver.unified_earnings
Writes to:  consumption.research_sue_scores,
            consumption.research_seasonality_patterns,
            consumption.research_contrarian_signals
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_SUE = """
INSERT INTO consumption.research_sue_scores
  (ticker, name, report_date, eps_estimate, eps_actual,
   eps_surprise_pct, sue_score, sue_decile, sue_category,
   price_change_1d, price_change_3d, price_change_5d,
   drift_signal, sector, market_cap, updated_at)
SELECT
  s.ticker,
  ar.name,
  s.report_date,
  s.estimate_eps AS eps_estimate,
  s.actual_eps   AS eps_actual,
  s.surprise_pct AS eps_surprise_pct,
  s.sue,
  s.sue_decile,
  s.sue_category,
  -- Price drift after earnings
  (SELECT returns_1d FROM silver.unified_prices
   WHERE ticker = s.ticker AND date = s.report_date) AS price_change_1d,
  NULL AS price_change_3d,
  NULL AS price_change_5d,
  CASE
    WHEN s.sue_decile >= 8 THEN 'drift_up'
    WHEN s.sue_decile <= 2 THEN 'drift_down'
    ELSE 'neutral'
  END AS drift_signal,
  ar.sector,
  NULL AS market_cap,
  NOW()
FROM gold.sue_scores s
JOIN gold.asset_registry ar ON ar.ticker = s.ticker
ON CONFLICT (ticker, report_date) DO UPDATE SET
  sue_score  = EXCLUDED.sue_score,
  sue_decile = EXCLUDED.sue_decile,
  drift_signal = EXCLUDED.drift_signal,
  updated_at = NOW();
"""

SQL_SEASONALITY = """
INSERT INTO consumption.research_seasonality_patterns
  (ticker, name, asset_class,
   current_month, current_month_bias, current_month_historical_return, current_month_win_rate,
   next_month, next_month_bias, next_month_historical_return,
   monthly_patterns_json, updated_at)
SELECT
  sp.ticker,
  ar.name,
  ar.asset_class,
  EXTRACT(MONTH FROM CURRENT_DATE)::int AS current_month,
  MAX(CASE WHEN sp.month = EXTRACT(MONTH FROM CURRENT_DATE)::int THEN sp.seasonal_bias END) AS current_month_bias,
  MAX(CASE WHEN sp.month = EXTRACT(MONTH FROM CURRENT_DATE)::int THEN sp.avg_return_pct END) AS current_month_historical_return,
  MAX(CASE WHEN sp.month = EXTRACT(MONTH FROM CURRENT_DATE)::int THEN sp.win_rate END) AS current_month_win_rate,
  (EXTRACT(MONTH FROM CURRENT_DATE)::int % 12 + 1) AS next_month,
  MAX(CASE WHEN sp.month = (EXTRACT(MONTH FROM CURRENT_DATE)::int % 12 + 1)
           THEN sp.seasonal_bias END) AS next_month_bias,
  MAX(CASE WHEN sp.month = (EXTRACT(MONTH FROM CURRENT_DATE)::int % 12 + 1)
           THEN sp.avg_return_pct END) AS next_month_historical_return,
  JSONB_OBJECT_AGG(sp.month::text,
    jsonb_build_object('avg_return', sp.avg_return_pct, 'win_rate', sp.win_rate,
                       'bias', sp.seasonal_bias)) AS monthly_patterns_json,
  NOW()
FROM gold.seasonality_patterns sp
JOIN gold.asset_registry ar ON ar.ticker = sp.ticker
GROUP BY sp.ticker, ar.name, ar.asset_class
ON CONFLICT (ticker) DO UPDATE SET
  current_month_bias             = EXCLUDED.current_month_bias,
  current_month_historical_return = EXCLUDED.current_month_historical_return,
  monthly_patterns_json          = EXCLUDED.monthly_patterns_json,
  updated_at                     = NOW();
"""

SQL_CONTRARIAN = """
INSERT INTO consumption.research_contrarian_signals
  (ticker, name, signal_type, contrarian_score,
   signal_direction, confidence,
   metric_1_name, metric_1_value, metric_1_percentile,
   metric_2_name, metric_2_value, metric_2_percentile,
   narrative, updated_at)
-- Contrarian = oversold with positive earnings drift
WITH scored AS (
  SELECT
    k.ticker,
    k.rsi_14,
    k.cond_rsi_oversold,
    k.cond_golden_cross,
    s.sue_decile,
    (CASE WHEN k.rsi_14 < 30 THEN 30 ELSE 0 END +
     CASE WHEN s.sue_decile >= 7 THEN 30 ELSE 0 END +
     CASE WHEN k.cond_above_sma200 THEN 20 ELSE 0 END +
     CASE WHEN k.cond_high_volume THEN 20 ELSE 0 END) AS score
  FROM (SELECT DISTINCT ON (ticker) * FROM gold.kpis_metrics ORDER BY ticker, date DESC) k
  LEFT JOIN (SELECT DISTINCT ON (ticker) * FROM gold.sue_scores ORDER BY ticker, report_date DESC) s
        ON s.ticker = k.ticker
  WHERE k.rsi_14 < 40
)
SELECT
  sc.ticker,
  ar.name,
  'contrarian_long' AS signal_type,
  sc.score          AS contrarian_score,
  'long'            AS signal_direction,
  sc.score / 100.0  AS confidence,
  'rsi_14'          AS metric_1_name,
  sc.rsi_14         AS metric_1_value,
  PERCENT_RANK() OVER (ORDER BY sc.rsi_14 DESC) * 100 AS metric_1_percentile,
  'sue_decile'      AS metric_2_name,
  sc.sue_decile     AS metric_2_value,
  COALESCE(sc.sue_decile * 10, 50) AS metric_2_percentile,
  'RSI oversold with positive earnings momentum' AS narrative,
  NOW()
FROM scored sc
JOIN gold.asset_registry ar ON ar.ticker = sc.ticker
WHERE sc.score >= 50
ORDER BY sc.score DESC
ON CONFLICT (ticker, signal_type) DO UPDATE SET
  contrarian_score = EXCLUDED.contrarian_score,
  confidence       = EXCLUDED.confidence,
  updated_at       = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_SUE)
    print(f"✅ consumption.research_sue_scores: {cur.rowcount} rows upserted")
    cur.execute(SQL_SEASONALITY)
    print(f"✅ consumption.research_seasonality_patterns: {cur.rowcount} rows upserted")
    cur.execute(SQL_CONTRARIAN)
    print(f"✅ consumption.research_contrarian_signals: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
