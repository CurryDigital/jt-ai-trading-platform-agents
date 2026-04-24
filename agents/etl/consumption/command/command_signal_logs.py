#!/usr/bin/env python3
"""
Consumption: Command Tab — Signal Logs & HFT Matrix
Reads from: gold.strategy_ticker_scores, gold.kpis_metrics, gold.hft_metrics
Writes to:  consumption.signal_logs, consumption.hft_matrix
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_SIGNAL_LOGS = """
INSERT INTO consumption.signal_logs
  (strategy_id, ticker, signal_type, signal_criteria, confidence_score,
   strategy_signal, triggered_at, created_at)
SELECT
  sts.strategy_id,
  sts.ticker,
  sts.signal_action,
  sts.criteria_met::text,
  sts.score,
  sts.signal_action = 'BUY',
  NOW(),
  NOW()
FROM gold.strategy_ticker_scores sts
WHERE sts.signal_action IN ('BUY', 'SELL')
  AND sts.updated_at >= NOW() - INTERVAL '1 day'
ON CONFLICT DO NOTHING;
"""

SQL_HFT = """
INSERT INTO consumption.hft_matrix
  (timestamp, ticker, asset_class,
   liquidity_momentum, fusion_signal, shock_warning,
   pressure_value, reasoning, velocity_estimates)
SELECT
  NOW(),
  h.ticker,
  ar.asset_class,
  CASE WHEN h.liquidity_pressure > 0.6 THEN 'HIGH' ELSE 'NORMAL' END,
  CASE WHEN h.fusion_score > 0.7 THEN 'STRONG' ELSE 'WEAK' END,
  CASE WHEN h.shock_index > 0.8 THEN 'WARNING' ELSE 'CLEAR' END,
  h.liquidity_pressure,
  'Computed from gold.hft_metrics',
  jsonb_build_object('market_velocity', h.market_velocity, 'arbitrage_gap', h.arbitrage_gap)
FROM (
  SELECT DISTINCT ON (ticker) * FROM gold.hft_metrics ORDER BY ticker, date DESC
) h
JOIN gold.asset_registry ar ON ar.ticker = h.ticker

ON CONFLICT (timestamp, ticker) DO UPDATE SET
  pressure_value = EXCLUDED.pressure_value,
  fusion_signal  = EXCLUDED.fusion_signal;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_SIGNAL_LOGS)
    print(f"✅ consumption.signal_logs: {cur.rowcount} rows inserted")
    cur.execute(SQL_HFT)
    print(f"✅ consumption.hft_matrix: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
