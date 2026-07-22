-- Pipeline UI feed view: maps DB strategy statuses to UI pipeline stages.
-- Target format matches StrategyPipeline.jsx expectations:
-- id, name, asset, horizon, tier, stage, btWR, liveWR, btPF, livePF, trades, returns, sharpe, dd, mode, margin
--
-- Rebuilt as a publication-gated view per classification review t_585de35a.
-- Stage is derived from gold.strategy_registry.priority / approved_at / status,
-- not from a free-text db_status. Only rows that pass the publication gate are
-- surfaced: priority in (EXPERIMENTAL, NEAR_GOLDEN, GOLDEN), status not in
-- (retired, paused), research.status not in (rejected, retired), latest backtest
-- sharpe_oos >= 0.5, |max_drawdown_oos| <= 20%, trade_count_oos >= 30, and
-- returns_oos IS NOT NULL. Metrics are sourced from the latest backtest run only.
CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS
WITH latest_backtest AS (
    SELECT DISTINCT ON (strategy_id)
           strategy_id,
           sharpe_oos,
           returns_oos,
           max_drawdown_oos,
           trade_count_oos,
           win_rate_oos,
           profit_factor_oos,
           all_risk_gates_passed
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_id, created_at DESC
),
latest_ticker_score AS (
    SELECT DISTINCT ON (strategy_id)
           strategy_id,
           signal_action,
           position_status,
           score
    FROM gold.strategy_ticker_scores
    ORDER BY strategy_id, updated_at DESC
),
published AS (
    SELECT r.strategy_id,
           r.name,
           r.asset_class,
           r.frequency,
           r.execution_mode,
           r.status AS registry_status,
           r.priority,
           r.approved_at,
           r.updated_at,
           res.status AS research_status,
           b.sharpe_oos,
           b.returns_oos,
           b.max_drawdown_oos,
           b.trade_count_oos,
           b.win_rate_oos,
           b.profit_factor_oos,
           b.all_risk_gates_passed,
           lts.position_status AS paper_position_status,
           lts.score,
           (r.priority IN ('EXPERIMENTAL', 'NEAR_GOLDEN', 'GOLDEN')
            AND r.status NOT IN ('retired', 'paused')
            AND res.status NOT IN ('rejected', 'retired')
            AND b.sharpe_oos >= 0.5
            AND ABS(COALESCE(b.max_drawdown_oos, 0)) <= 0.20
            AND b.trade_count_oos >= 30
            AND b.returns_oos IS NOT NULL
           ) AS publishable
    FROM gold.strategy_registry r
    JOIN gold.strategy_research res ON res.strategy_id = r.strategy_id
    LEFT JOIN latest_backtest b ON b.strategy_id = r.strategy_id
    LEFT JOIN latest_ticker_score lts ON lts.strategy_id = r.strategy_id
)
SELECT s.strategy_id AS id,
       s.name,
       COALESCE(upper(s.asset_class::text), 'EQUITY') AS asset,
       CASE
           WHEN s.frequency::text = ANY (ARRAY['daily'::text, 'intraday'::text, 'day'::text, 'event'::text]) THEN 'day'
           WHEN s.frequency::text = ANY (ARRAY['weekly'::text, 'swing'::text]) THEN 'swing'
           WHEN s.frequency::text = ANY (ARRAY['monthly'::text, 'quarterly'::text, 'position'::text]) THEN 'position'
           ELSE 'swing'
       END AS horizon,
       CASE
           WHEN upper(s.priority::text) = 'GOLDEN' THEN 'T1'
           WHEN upper(s.priority::text) = 'NEAR_GOLDEN' THEN 'T2'
           ELSE 'T3'
       END AS tier,
       CASE
           WHEN upper(s.priority::text) = 'GOLDEN' AND s.approved_at IS NOT NULL THEN 'golden'
           WHEN upper(s.priority::text) = 'NEAR_GOLDEN' AND s.approved_at IS NOT NULL THEN 'near_golden'
           WHEN upper(s.priority::text) = 'GOLDEN' AND s.approved_at IS NULL THEN 'near_golden'
           WHEN upper(s.priority::text) = 'NEAR_GOLDEN' AND s.approved_at IS NULL THEN 'experimental'
           WHEN s.registry_status = 'paper' THEN 'golden'
           WHEN s.registry_status = 'live' THEN 'deployed'
           ELSE 'experimental'
       END AS stage,
       (s.win_rate_oos * 100)::numeric AS btwr,
       NULL::numeric AS livewr,
       s.profit_factor_oos AS btpf,
       NULL::numeric AS livepf,
       s.trade_count_oos AS trades,
       (s.returns_oos * 100)::numeric AS returns,
       s.sharpe_oos::numeric AS sharpe,
       (-ABS(COALESCE(s.max_drawdown_oos, 0))) * 100 AS dd,
       CASE
           WHEN s.paper_position_status::text = ANY (ARRAY['PAPER'::text, 'paper'::text]) THEN 'PAPER_TRADING'
           WHEN s.registry_status = 'live' THEN 'LIVE_TRADING'
           ELSE 'SIMULATION'
       END AS mode,
       NULL::jsonb AS margin,
       s.research_status AS db_status,
       s.frequency,
       'trade_algo_researcher'::text AS agent_source,
       s.updated_at,
       (s.returns_oos * 100)::numeric AS live_pnl,
       CASE
           WHEN NOT s.publishable THEN 'not_publishable'
           WHEN s.profit_factor_oos IS NULL AND s.trade_count_oos > 0 THEN 'missing_pf'
           WHEN s.sharpe_oos IS NULL AND s.trade_count_oos > 0 THEN 'missing_sharpe'
           WHEN ABS(COALESCE(s.max_drawdown_oos, 0)) = 0 AND s.trade_count_oos > 1 THEN 'suspicious_zero_dd'
           ELSE 'ok'
       END AS metric_valid_flag
FROM published s
WHERE s.publishable
ORDER BY stage, updated_at DESC;

COMMENT ON VIEW gold.v_pipeline_ui_feed IS 'Publication-gated pipeline UI feed. Only includes strategies that pass priority/status/research/metric gates per t_585de35a.';
