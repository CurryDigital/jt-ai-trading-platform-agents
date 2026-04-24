#!/usr/bin/env python3
"""
Gold Strategy: Strategy Scores & Backtest Results
Reads from: gold.strategy_definitions, gold.kpis_metrics,
            gold.strategy_ticker_assignments, gold.strategy_signal_criteria
Writes to:  gold.strategy_ticker_scores, gold.strategy_backtests,
            gold.strategy_metrics_summary, gold.strategy_registry
"""
import sys, os, json
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_SCORES = """
INSERT INTO gold.strategy_ticker_scores
  (strategy_id, ticker, score, criteria_met, signal_action,
   entry_score, entry_criteria, position_status, updated_at)

WITH criteria AS (
  SELECT
    sc.strategy_id,
    sc.signal_type,
    sc.criterion_name,
    sc.operator,
    sc.threshold,
    sc.logic_mode,
    sc.logic_threshold
  FROM gold.strategy_signal_criteria sc
),
assignments AS (
  SELECT strategy_id, ticker FROM gold.strategy_universes WHERE is_active = TRUE
),
latest_kpis AS (
  SELECT DISTINCT ON (ticker) *
  FROM gold.kpis_metrics
  ORDER BY ticker, date DESC
),
signal_eval AS (
  SELECT
    a.strategy_id,
    a.ticker,
    -- Score = count of criteria met (normalised 0-100)
    COUNT(CASE
      WHEN c.criterion_name = 'rsi_14'         AND c.operator = '<'
           AND k.rsi_14 < c.threshold          THEN 1
      WHEN c.criterion_name = 'volume_ratio'   AND c.operator = '>'
           AND k.volume_ratio > c.threshold    THEN 1
      WHEN c.criterion_name = 'above_sma200'   AND k.cond_above_sma200 THEN 1
      WHEN c.criterion_name = 'macd_bullish'   AND k.cond_macd_bullish  THEN 1
      ELSE NULL
    END) * 100.0 / NULLIF(COUNT(*), 0) AS score,
    COUNT(CASE
      WHEN c.criterion_name = 'rsi_14'       AND c.operator = '<' AND k.rsi_14 < c.threshold THEN 1
      ELSE NULL END) > 0 AS has_entry_signal
  FROM assignments a
  JOIN latest_kpis k USING (ticker)
  JOIN criteria c USING (strategy_id)
  GROUP BY a.strategy_id, a.ticker
)
SELECT
  strategy_id,
  ticker,
  ROUND(score::numeric, 2),
  '{}'::jsonb,   -- criteria_met detail (expand as needed)
  CASE WHEN has_entry_signal THEN 'BUY' ELSE 'HOLD' END,
  ROUND(score::numeric, 2),
  '{}'::jsonb,
  'NONE',
  NOW()
FROM signal_eval

ON CONFLICT (strategy_id, ticker) DO UPDATE SET
  score          = EXCLUDED.score,
  signal_action  = EXCLUDED.signal_action,
  entry_score    = EXCLUDED.entry_score,
  updated_at     = NOW();
"""

SQL_REGISTRY_SYNC = """
UPDATE gold.strategy_registry sr
SET
  win_rate     = sd.win_rate,
  sharpe_ratio = sd.sharpe_ratio,
  max_drawdown_pct = sd.max_drawdown,
  updated_at   = NOW()
FROM gold.strategy_definitions sd
WHERE sr.strategy_id = sd.strategy_id;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SQL_SCORES)
    print(f"✅ gold.strategy_ticker_scores updated: {cur.rowcount} rows upserted")

    cur.execute(SQL_REGISTRY_SYNC)
    print(f"✅ gold.strategy_registry synced: {cur.rowcount} rows updated")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
