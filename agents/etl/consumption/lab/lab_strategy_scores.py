#!/usr/bin/env python3
"""
Consumption: Lab Tab — Strategy Backtest Scores & Dynamic Scores
Reads from: gold.strategy_backtests, gold.strategy_definitions,
            gold.strategy_ticker_scores, gold.kpis_metrics
Writes to:  consumption.strategies_backtest_results
            consumption.strategy_scores_dynamic
            consumption.ticker_scores
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# ── Backtest Results ──────────────────────────────────────────────────────────

BACKTEST_SQL = """
INSERT INTO consumption.strategies_backtest_results
    (strategy_id, ticker, period_start, period_end, total_days,
     total_return_pct, annualized_return_pct, benchmark_return_pct, alpha_pct,
     volatility_annual, sharpe_ratio, sortino_ratio, max_drawdown_pct, calmar_ratio,
     total_trades, win_rate, profit_factor, avg_trade_return_pct,
     avg_win_pct, avg_loss_pct, equity_curve_json, calculated_at,
     asset_class, direction, time_horizon)
SELECT
    sb.strategy_id,
    sb.ticker,
    (CURRENT_DATE - INTERVAL '5 years')::date   AS period_start,
    CURRENT_DATE                                AS period_end,
    365 * 5                                     AS total_days,
    sb.total_return * 100                       AS total_return_pct,
    -- Annualised: (1 + total)^(1/5) - 1
    ROUND(((1 + sb.total_return)^(1.0/5) - 1) * 100, 4) AS annualized_return_pct,
    NULL::numeric                               AS benchmark_return_pct,
    NULL::numeric                               AS alpha_pct,
    NULL::numeric                               AS volatility_annual,
    sb.sharpe_ratio,
    NULL::numeric                               AS sortino_ratio,
    sb.max_drawdown * 100                       AS max_drawdown_pct,
    NULL::numeric                               AS calmar_ratio,
    sb.num_trades,
    sb.win_rate,
    sb.profit_factor,
    sb.avg_trade_return * 100                   AS avg_trade_return_pct,
    NULL::numeric                               AS avg_win_pct,
    NULL::numeric                               AS avg_loss_pct,
    NULL::jsonb                                 AS equity_curve_json,
    NOW(),
    sd.asset_class,
    sd.direction,
    sd.time_horizon
FROM gold.strategy_backtests sb
LEFT JOIN gold.strategy_definitions sd ON sd.strategy_id = sb.strategy_id
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
    sharpe_ratio        = EXCLUDED.sharpe_ratio,
    max_drawdown_pct    = EXCLUDED.max_drawdown_pct,
    win_rate            = EXCLUDED.win_rate,
    total_trades        = EXCLUDED.total_trades,
    calculated_at       = NOW();
"""

# ── Dynamic Scores ────────────────────────────────────────────────────────────

DYNAMIC_SCORES_SQL = """
INSERT INTO consumption.strategy_scores_dynamic
    (strategy_id, ticker, score, buy_signals, sell_signals, signal_strength, last_updated)
SELECT
    sts.strategy_id,
    sts.ticker,
    sts.score,
    -- Collect buy signals from criteria_met json
    COALESCE(
        (SELECT jsonb_agg(key)
         FROM jsonb_each_text(sts.entry_criteria)
         WHERE value::boolean = true), '[]'::jsonb
    ) AS buy_signals,
    COALESCE(
        (SELECT jsonb_agg(key)
         FROM jsonb_each_text(sts.exit_criteria)
         WHERE value::boolean = true), '[]'::jsonb
    ) AS sell_signals,
    -- Signal strength: score normalised 0-1
    ROUND(LEAST(sts.score / 100.0, 1.0), 3) AS signal_strength,
    NOW()
FROM gold.strategy_ticker_scores sts
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
    score           = EXCLUDED.score,
    buy_signals     = EXCLUDED.buy_signals,
    sell_signals    = EXCLUDED.sell_signals,
    signal_strength = EXCLUDED.signal_strength,
    last_updated    = NOW();
"""

# ── Ticker Scores (consumption) ───────────────────────────────────────────────

TICKER_SCORES_SQL = """
INSERT INTO consumption.ticker_scores
    (ticker, strategy_id, score, criteria_met, signal_action, last_updated)
SELECT
    ticker,
    strategy_id,
    score,
    criteria_met,
    signal_action,
    NOW()
FROM gold.strategy_ticker_scores
ON CONFLICT (ticker, strategy_id) DO UPDATE SET
    score         = EXCLUDED.score,
    criteria_met  = EXCLUDED.criteria_met,
    signal_action = EXCLUDED.signal_action,
    last_updated  = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(BACKTEST_SQL)
    print(f"✅ consumption.strategies_backtest_results — {cur.rowcount} rows upserted")

    cur.execute(DYNAMIC_SCORES_SQL)
    print(f"✅ consumption.strategy_scores_dynamic — {cur.rowcount} rows upserted")

    cur.execute(TICKER_SCORES_SQL)
    print(f"✅ consumption.ticker_scores — {cur.rowcount} rows upserted")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
