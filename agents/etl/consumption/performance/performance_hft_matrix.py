#!/usr/bin/env python3
"""
Consumption: Performance Tab — Monthly Returns, Attribution, HFT Matrix
Reads from: gold.strategy_backtests, gold.strategy_definitions,
            gold.hft_metrics, gold.trade_executions,
            gold.strategy_metrics_summary
Writes to:  consumption.performance_monthly_returns
            consumption.performance_strategy_attribution
            consumption.hft_matrix
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# ── HFT Matrix ────────────────────────────────────────────────────────────────

HFT_MATRIX_SQL = """
INSERT INTO consumption.hft_matrix
    (timestamp, ticker, asset_class,
     liquidity_momentum, fusion_signal, shock_warning,
     pressure_value, reasoning, velocity_estimates)
SELECT
    h.date         AS timestamp,
    h.ticker,
    ar.asset_class,
    CASE
        WHEN h.liquidity_pressure > 0.6 THEN 'HIGH'
        WHEN h.liquidity_pressure > 0.3 THEN 'MED'
        ELSE 'LOW'
    END AS liquidity_momentum,
    CASE
        WHEN h.fusion_score > 0.5 THEN 'BUY'
        WHEN h.fusion_score < -0.5 THEN 'SELL'
        ELSE 'NEUTRAL'
    END AS fusion_signal,
    CASE WHEN h.shock_index > 0.7 THEN 'WARNING' ELSE 'CLEAR' END AS shock_warning,
    h.liquidity_pressure AS pressure_value,
    NULL::text           AS reasoning,
    jsonb_build_object(
        'market_velocity', h.market_velocity,
        'arbitrage_gap',   h.arbitrage_gap,
        'shock_index',     h.shock_index
    ) AS velocity_estimates
FROM (
    SELECT DISTINCT ON (ticker) *
    FROM gold.hft_metrics
    ORDER BY ticker, date DESC
) h
LEFT JOIN gold.asset_registry ar ON ar.ticker = h.ticker
ON CONFLICT (timestamp, ticker) DO UPDATE SET
    liquidity_momentum = EXCLUDED.liquidity_momentum,
    fusion_signal      = EXCLUDED.fusion_signal,
    shock_warning      = EXCLUDED.shock_warning,
    pressure_value     = EXCLUDED.pressure_value;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(HFT_MATRIX_SQL)
    print(f"✅ consumption.hft_matrix — {cur.rowcount} rows upserted")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
