"""Fix gold.v_pipeline_ui_feed and normalize strategy_backtest_runs OOS sign.

Changes:
  - Make max_drawdown_oos strictly non-positive (flip positive signs).
  - Change the latest_backtest tie-breaker to created_at DESC so the most
    recently inserted row wins, not the ambiguous run_number DESC.
  - Sync gold.strategy_registry from the corrected latest run.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor

DB = dict(
    host=os.environ['PGHOST'],
    dbname=os.environ['PGDATABASE'],
    user=os.environ['PGUSER'],
    password=os.environ['PGPASSWORD'],
)

conn = psycopg2.connect(**DB)
conn.autocommit = False
cur = conn.cursor(cursor_factory=RealDictCursor)

print("1. Normalizing max_drawdown_oos sign to non-positive...")
cur.execute("""
    UPDATE gold.strategy_backtest_runs
    SET max_drawdown_oos = -max_drawdown_oos
    WHERE max_drawdown_oos > 0
""")
print(f"   flipped {cur.rowcount} positive drawdown rows")

print("\n2. Recreating gold.v_pipeline_ui_feed with deterministic latest run...")
cur.execute("""
CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS
WITH latest_backtest AS (
    SELECT DISTINCT ON (strategy_backtest_runs.strategy_id)
        strategy_backtest_runs.strategy_id,
        strategy_backtest_runs.sharpe_oos AS sharpe_ratio,
        strategy_backtest_runs.returns_oos AS total_return,
        strategy_backtest_runs.max_drawdown_oos AS max_drawdown,
        strategy_backtest_runs.trade_count_oos AS trade_count,
        strategy_backtest_runs.win_rate_oos AS win_rate,
        strategy_backtest_runs.profit_factor_oos AS profit_factor,
        strategy_backtest_runs.all_risk_gates_passed
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_backtest_runs.strategy_id,
             strategy_backtest_runs.run_number DESC,
             strategy_backtest_runs.created_at DESC
),
latest_ticker_score AS (
    SELECT DISTINCT ON (strategy_ticker_scores.strategy_id)
        strategy_ticker_scores.strategy_id,
        strategy_ticker_scores.signal_action,
        strategy_ticker_scores.position_status,
        strategy_ticker_scores.score
    FROM gold.strategy_ticker_scores
    ORDER BY strategy_ticker_scores.strategy_id,
             strategy_ticker_scores.updated_at DESC
),
strategy_live_stats AS (
    SELECT p.strategy_id,
        count(*) FILTER (WHERE p.status = 'closed' AND p.rehearsal = false) AS live_trades,
        round(sum(
            CASE
                WHEN p.status = 'closed' AND p.rehearsal = false AND p.pnl > 0 THEN 1
                ELSE 0
            END)::numeric
            / NULLIF(sum(
                CASE
                    WHEN p.status = 'closed' AND p.rehearsal = false THEN 1
                    ELSE 0
                END), 0)::numeric * 100, 1) AS live_win_rate,
        round(sum(
            CASE
                WHEN p.status = 'closed' AND p.rehearsal = false THEN p.pnl
                ELSE 0::numeric
            END), 2) AS live_pnl,
        round(sum(
            CASE
                WHEN p.status = 'closed' AND p.rehearsal = false AND p.pnl > 0 THEN p.pnl
                ELSE 0::numeric
            END)
            / NULLIF(abs(sum(
                CASE
                    WHEN p.status = 'closed' AND p.rehearsal = false AND p.pnl < 0 THEN p.pnl
                    ELSE 0::numeric
                END)), 0::numeric), 2) AS live_profit_factor
    FROM gold.paper_trades p
    GROUP BY p.strategy_id
)
SELECT s.strategy_id AS id,
    s.name,
    COALESCE(upper(s.asset_class::text), 'EQUITY') AS asset,
    CASE
        WHEN s.frequency::text = ANY (ARRAY['daily','intraday','day']) THEN 'day'
        WHEN s.frequency::text = ANY (ARRAY['weekly','swing']) THEN 'swing'
        WHEN s.frequency::text = ANY (ARRAY['monthly','quarterly','position']) THEN 'position'
        ELSE 'swing'
    END AS horizon,
    CASE
        WHEN b.all_risk_gates_passed AND s.status::text = 'approved' THEN 'T1'
        WHEN b.all_risk_gates_passed AND (s.status::text = ANY (ARRAY['risk_review','backtesting'])) THEN 'T2'
        ELSE 'T3'
    END AS tier,
    CASE s.status
        WHEN 'approved' THEN 'deployed'
        WHEN 'risk_review' THEN 'golden'
        WHEN 'backtesting' THEN 'near_golden'
        WHEN 'rejected' THEN 'experimental'
        ELSE 'experimental'
    END AS stage,
    COALESCE(b.win_rate * 100, 0) AS btwr,
    sl.live_win_rate AS livewr,
    b.profit_factor AS btpf,
    sl.live_profit_factor AS livepf,
    COALESCE(b.trade_count, 0) AS trades,
    COALESCE(b.total_return * 100, 0) AS returns,
    COALESCE(b.sharpe_ratio, 0) AS sharpe,
    COALESCE(b.max_drawdown * 100, 0) AS dd,
    sl.live_pnl,
    CASE
        WHEN lts.position_status::text = ANY (ARRAY['PAPER','paper']) THEN 'PAPER_TRADING'
        WHEN s.status::text = 'approved' THEN 'LIVE_TRADING'
        ELSE 'SIMULATION'
    END AS mode,
    NULL::jsonb AS margin,
    s.status AS db_status,
    s.frequency,
    s.source AS agent_source,
    s.updated_at
FROM gold.strategy_research s
LEFT JOIN latest_backtest b ON b.strategy_id::text = s.strategy_id::text
LEFT JOIN latest_ticker_score lts ON lts.strategy_id::text = s.strategy_id::text
LEFT JOIN strategy_live_stats sl ON sl.strategy_id = s.strategy_id::text
ORDER BY s.status, s.updated_at DESC;
""")

print("\n3. Recreating gold.v_strategy_live_stats as a stable view...")
cur.execute("""
CREATE OR REPLACE VIEW gold.v_strategy_live_stats AS
SELECT strategy_id,
    count(*) FILTER (WHERE status = 'closed' AND rehearsal = false) AS live_trades,
    round(sum(
        CASE
            WHEN status = 'closed' AND rehearsal = false AND pnl > 0 THEN 1
            ELSE 0
        END)::numeric
        / NULLIF(sum(
            CASE
                WHEN status = 'closed' AND rehearsal = false THEN 1
                ELSE 0
            END), 0)::numeric * 100, 1) AS live_win_rate,
    round(sum(
        CASE
            WHEN status = 'closed' AND rehearsal = false THEN pnl
            ELSE 0::numeric
        END), 2) AS live_pnl,
    round(sum(
        CASE
            WHEN status = 'closed' AND rehearsal = false AND pnl > 0 THEN pnl
            ELSE 0::numeric
        END)
        / NULLIF(abs(sum(
            CASE
                WHEN status = 'closed' AND rehearsal = false AND pnl < 0 THEN pnl
                ELSE 0::numeric
            END)), 0::numeric), 2) AS live_profit_factor
FROM gold.paper_trades
GROUP BY strategy_id;
""")

print("\n4. Syncing gold.strategy_registry from corrected latest backtest run...")
cur.execute("""
UPDATE gold.strategy_registry r
SET
    win_rate_oos = b.win_rate_oos * 100,
    profit_factor_oos = b.profit_factor_oos,
    trade_count_oos = b.trade_count_oos,
    max_drawdown_oos = ABS(b.max_drawdown_oos) * 100,
    sharpe_oos = b.sharpe_oos,
    updated_at = NOW()
FROM (
    SELECT DISTINCT ON (strategy_id)
        strategy_id,
        win_rate_oos,
        profit_factor_oos,
        trade_count_oos,
        max_drawdown_oos,
        sharpe_oos
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_id, run_number DESC, created_at DESC
) b
WHERE r.strategy_id = b.strategy_id
  AND b.profit_factor_oos IS NOT NULL
""")
print(f"   synced {cur.rowcount} registry rows")

conn.commit()
print("\nCommitted view/sign fixes")

print("\n5. Verification: approved/backtesting 30 view rows")
cur.execute("""
SELECT id, btwr, btpf, livewr, livepf, trades, sharpe, dd, live_pnl, db_status
FROM gold.v_pipeline_ui_feed
WHERE db_status IN ('approved','backtesting')
ORDER BY id
""")
for r in cur.fetchall():
    print(dict(r))

conn.close()
