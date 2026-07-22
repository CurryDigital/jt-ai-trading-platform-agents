-- Migration: expose gold.v_pipeline_ui_feed columns expected by the frontend pipeline feed endpoint.
-- Task: t_1bb23772
-- Changes:
--   * Add live_pnl column (aliases backtest total_return until a true live PnL source exists)
--   * Remove COALESCE to 0 for backtest numeric metrics so missing backtests are returned as NULL
--     per the endpoint contract (keep NULL as JSON null, not 0).
--   * Rejected rows remain included.

CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS
WITH latest_backtest AS (
    SELECT DISTINCT ON (strategy_backtest_runs.strategy_id)
           strategy_backtest_runs.strategy_id,
           strategy_backtest_runs.sharpe_oos AS sharpe_ratio,
           strategy_backtest_runs.returns_oos AS total_return,
           strategy_backtest_runs.max_drawdown_oos AS max_drawdown,
           strategy_backtest_runs.trade_count_oos AS trade_count,
           strategy_backtest_runs.win_rate_oos AS win_rate,
           strategy_backtest_runs.all_risk_gates_passed
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_backtest_runs.strategy_id, strategy_backtest_runs.created_at DESC
),
latest_ticker_score AS (
    SELECT DISTINCT ON (strategy_ticker_scores.strategy_id)
           strategy_ticker_scores.strategy_id,
           strategy_ticker_scores.signal_action,
           strategy_ticker_scores.position_status,
           strategy_ticker_scores.score
    FROM gold.strategy_ticker_scores
    ORDER BY strategy_ticker_scores.strategy_id, strategy_ticker_scores.updated_at DESC
)
SELECT s.strategy_id AS id,
       s.name,
       COALESCE(upper(s.asset_class::text), 'EQUITY'::text) AS asset,
       CASE
           WHEN s.frequency::text = ANY (ARRAY['daily'::character varying, 'intraday'::character varying, 'day'::character varying]::text[]) THEN 'day'::text
           WHEN s.frequency::text = ANY (ARRAY['weekly'::character varying, 'swing'::character varying]::text[]) THEN 'swing'::text
           WHEN s.frequency::text = ANY (ARRAY['monthly'::character varying, 'quarterly'::character varying, 'position'::character varying]::text[]) THEN 'position'::text
           ELSE 'swing'::text
       END AS horizon,
       CASE
           WHEN b.all_risk_gates_passed AND s.status::text = 'approved'::text THEN 'T1'::text
           WHEN b.all_risk_gates_passed AND (s.status::text = ANY (ARRAY['risk_review'::character varying, 'backtesting'::character varying]::text[])) THEN 'T2'::text
           ELSE 'T3'::text
       END AS tier,
       CASE s.status
           WHEN 'approved'::text THEN 'deployed'::text
           WHEN 'risk_review'::text THEN 'golden'::text
           WHEN 'backtesting'::text THEN 'near_golden'::text
           WHEN 'rejected'::text THEN 'experimental'::text
           ELSE 'experimental'::text
       END AS stage,
       (b.win_rate * 100::numeric) AS btwr,
       NULL::numeric AS livewr,
       NULL::numeric AS btpf,
       NULL::numeric AS livepf,
       b.trade_count AS trades,
       (b.total_return * 100::numeric) AS returns,
       b.sharpe_ratio::numeric AS sharpe,
       (b.max_drawdown * 100::numeric) AS dd,
       CASE
           WHEN lts.position_status::text = ANY (ARRAY['PAPER'::character varying, 'paper'::character varying]::text[]) THEN 'PAPER_TRADING'::text
           WHEN s.status::text = 'approved'::text THEN 'LIVE_TRADING'::text
           ELSE 'SIMULATION'::text
       END AS mode,
       NULL::jsonb AS margin,
       s.status AS db_status,
       s.frequency,
       s.source AS agent_source,
       s.updated_at,
       (b.total_return * 100::numeric) AS live_pnl
FROM gold.strategy_research s
LEFT JOIN latest_backtest b ON b.strategy_id::text = s.strategy_id::text
LEFT JOIN latest_ticker_score lts ON lts.strategy_id::text = s.strategy_id::text
ORDER BY s.status, s.updated_at DESC;
