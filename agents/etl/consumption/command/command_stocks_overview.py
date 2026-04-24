#!/usr/bin/env python3
"""
Consumption: Command Tab — Stocks Overview & Top Opportunities
Reads from: gold.kpis_metrics, gold.asset_registry, gold.strategy_ticker_scores,
            gold.strategy_definitions
Writes to:  consumption.markets_stocks_overview,
            consumption.dashboard_opportunities_top,
            consumption.dashboard_summary_cards
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_STOCKS = """
INSERT INTO consumption.markets_stocks_overview
  (ticker, name, sector, industry, market,
   price, change_pct, change_value, volume, avg_volume, volume_ratio,
   trend, rsi_14,
   distance_to_52w_high_pct, distance_to_52w_low_pct,
   strategy_signals, top_strategy_score,
   signal, signal_strength, asset_class, updated_at)

WITH latest_kpis AS (
  SELECT DISTINCT ON (ticker) *
  FROM gold.kpis_metrics
  ORDER BY ticker, date DESC
),
strategy_agg AS (
  SELECT
    ticker,
    MAX(score) AS top_score,
    JSONB_OBJECT_AGG(strategy_id, score) AS signals
  FROM gold.strategy_ticker_scores
  GROUP BY ticker
)
SELECT
  k.ticker,
  ar.name,
  ar.sector,
  NULL AS industry,
  ar.market,
  k.close AS price,
  k.change_1d AS change_pct,
  k.close * k.change_1d / 100 AS change_value,
  k.volume,
  k.vol_sma_20 AS avg_volume,
  k.vol_ratio AS volume_ratio,
  CASE
    WHEN k.cond_above_sma50  THEN 'up'
    WHEN k.cond_below_sma50  THEN 'down'
    ELSE 'sideways'
  END AS trend,
  k.rsi_14,
  -- Distance to 52w high/low from kpis (not stored directly, approximate)
  NULL AS distance_to_52w_high_pct,
  NULL AS distance_to_52w_low_pct,
  COALESCE(sa.signals, '{}'::jsonb) AS strategy_signals,
  COALESCE(sa.top_score, 0) AS top_strategy_score,
  CASE
    WHEN k.s001_high_vol_pullback OR k.s002_oversold_bounce OR k.s007_3day_monday OR k.s012_tech_momentum
    THEN 'BUY'
    ELSE 'HOLD'
  END AS signal,
  COALESCE(sa.top_score / 100, 0) AS signal_strength,
  ar.asset_class,
  NOW()
FROM latest_kpis k
JOIN gold.asset_registry ar ON ar.ticker = k.ticker
LEFT JOIN strategy_agg sa ON sa.ticker = k.ticker

ON CONFLICT (ticker) DO UPDATE SET
  price            = EXCLUDED.price,
  change_pct       = EXCLUDED.change_pct,
  rsi_14           = EXCLUDED.rsi_14,
  strategy_signals = EXCLUDED.strategy_signals,
  top_strategy_score = EXCLUDED.top_strategy_score,
  signal           = EXCLUDED.signal,
  updated_at       = NOW();
"""

SQL_OPPORTUNITIES = """
DELETE FROM consumption.dashboard_opportunities_top;

INSERT INTO consumption.dashboard_opportunities_top
  (rank, ticker, name, asset_class, signal_type, direction, confidence,
   expected_return_pct, entry_price, stop_loss, take_profit, rationale, updated_at)
SELECT
  ROW_NUMBER() OVER (ORDER BY sts.score DESC) AS rank,
  sts.ticker,
  ar.name,
  ar.asset_class,
  sd.strategy_id AS signal_type,
  'LONG' AS direction,
  sts.score / 100 AS confidence,
  sd.sharpe_ratio AS expected_return_pct,
  k.close AS entry_price,
  k.close * 0.97 AS stop_loss,
  k.close * 1.05 AS take_profit,
  sd.name AS rationale,
  NOW()
FROM gold.strategy_ticker_scores sts
JOIN gold.strategy_definitions sd USING (strategy_id)
JOIN gold.asset_registry ar ON ar.ticker = sts.ticker
JOIN (
  SELECT DISTINCT ON (ticker) ticker, close
  FROM gold.kpis_metrics ORDER BY ticker, date DESC
) k ON k.ticker = sts.ticker
WHERE sts.score > 60
ORDER BY sts.score DESC
LIMIT 10;
"""

SQL_SUMMARY = """
INSERT INTO consumption.dashboard_summary_cards
  (card_key, card_title, value_display, value_numeric, change_pct, trend, last_updated)
VALUES
  ('active_signals', 'Active Signals',
   (SELECT COUNT(*)::text FROM gold.strategy_ticker_scores WHERE signal_action = 'BUY'),
   (SELECT COUNT(*) FROM gold.strategy_ticker_scores WHERE signal_action = 'BUY'),
   NULL, 'up', NOW()),
  ('strategies_live', 'Live Strategies',
   (SELECT COUNT(*)::text FROM gold.strategy_definitions WHERE status = 'ACTIVE'),
   (SELECT COUNT(*) FROM gold.strategy_definitions WHERE status = 'ACTIVE'),
   NULL, 'up', NOW())
ON CONFLICT (card_key) DO UPDATE SET
  value_display = EXCLUDED.value_display,
  value_numeric = EXCLUDED.value_numeric,
  last_updated  = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_STOCKS)
    print(f"✅ consumption.markets_stocks_overview: {cur.rowcount} rows upserted")
    cur.execute(SQL_OPPORTUNITIES)
    print(f"✅ consumption.dashboard_opportunities_top: refreshed")
    cur.execute(SQL_SUMMARY)
    print(f"✅ consumption.dashboard_summary_cards: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
