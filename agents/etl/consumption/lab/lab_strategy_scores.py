#!/usr/bin/env python3
"""
Consumption: Lab Tab — Strategy Backtest Scores & Dynamic Scores
Reads from: gold.strategy_backtests, gold.strategy_definitions,
            gold.strategy_ticker_scores, gold.kpis_metrics
Writes to:  consumption.strategies_backtest_results
            consumption.strategy_scores_dynamic
            consumption.ticker_scores

Evidence contract (2026-10-09, t_835ba3c4): RETRACTED gold.strategy_backtests
rows are quarantined and never fed; evidence_class/verification_note are
carried into consumption so UNVERIFIED_NON_PIT rows can be badged and excluded
from rankings. Gold-sourced rows are DELETE-then-INSERT per refresh (the
historical ON CONFLICT (id) never fired — id is serial — causing duplicates).
FLAG: legacy signal-agent position_size uses hardcoded price=100.0/atr14=2.0
(BaseStrategy.run stub) — NO P&L may ever be derived from gold.strategy_signals
or gold.regime_gate_decision_log; shadow-PnL proposals must be rejected.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# ── Backtest Results ──────────────────────────────────────────────────────────

BACKTEST_DELETE_SQL = """
-- Re-sync the gold-sourced slice (see migration
-- 2026-10-09_strategy_backtests_evidence_quarantine.sql).
DELETE FROM consumption.strategies_backtest_results
WHERE strategy_id IN (SELECT strategy_id::text FROM gold.strategy_backtests);
"""

BACKTEST_SQL = """
INSERT INTO consumption.strategies_backtest_results
    (strategy_id, asset_class,
     sharpe_ratio, max_drawdown_pct, total_trades, win_rate,
     sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
     updated_at, evidence_class, verification_note)
SELECT
    sb.strategy_id::text,
    NULL AS asset_class,
    sb.sharpe AS sharpe_ratio,
    ABS(sb.max_dd) * 100 AS max_drawdown_pct,
    sb.n_trades AS total_trades,
    sb.win_rate,
    NULL AS sharpe_oos,
    NULL AS returns_oos,
    NULL AS max_drawdown_oos,
    NULL AS trade_count_oos,
    NULL AS win_rate_oos,
    sb.run_date AS updated_at,
    sb.evidence_class,
    sb.verification_note
FROM gold.strategy_backtests sb
WHERE sb.evidence_class IS DISTINCT FROM 'RETRACTED'  -- quarantined rows never surface (t_835ba3c4)
ON CONFLICT (id) DO UPDATE SET
    sharpe_ratio        = EXCLUDED.sharpe_ratio,
    max_drawdown_pct    = EXCLUDED.max_drawdown_pct,
    win_rate            = EXCLUDED.win_rate,
    total_trades        = EXCLUDED.total_trades,
    updated_at          = EXCLUDED.updated_at,
    evidence_class      = EXCLUDED.evidence_class,
    verification_note   = EXCLUDED.verification_note;
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
         FROM jsonb_each_text(sts.criteria_met)
         WHERE value::text = 'true'), '[]'::jsonb
    ) AS buy_signals,
    COALESCE(
        (SELECT jsonb_agg(key)
         FROM jsonb_each_text(sts.criteria_met)
         WHERE value::text = 'false'), '[]'::jsonb
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
    cur.execute("SELECT COUNT(*) FROM gold.strategy_backtests")
    if cur.fetchone()[0] == 0:
        print("⚠️ gold.strategy_backtests empty — skipping")
        conn.close()
        return

    cur.execute(BACKTEST_DELETE_SQL)
    print(f"🧹 consumption.strategies_backtest_results — {cur.rowcount} stale gold-sourced rows removed")
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
