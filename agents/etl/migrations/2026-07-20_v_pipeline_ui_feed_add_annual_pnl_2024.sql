-- Migration: expose annual_pnl_2024 in gold.v_pipeline_ui_feed alongside 2025/2026.
-- Source of truth for the annual_pnl columns remains gold.strategy_backtest_runs,
-- populated by gold/strategy/refresh_annual_backtest_returns.py from ETL-owned
-- gold.strategy_backtest_trades.
--
-- Column order is intentionally: annual_pnl_2025, annual_pnl_2026, annual_pnl_2024
-- so CREATE OR REPLACE VIEW preserves the existing 2025/2026 columns and appends
-- 2024 as a new column at the end.
-- Task: t_7d2e4c9a

CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS
WITH latest_backtest AS (
    SELECT DISTINCT ON (strategy_backtest_runs.strategy_id)
        strategy_backtest_runs.strategy_id,
        strategy_backtest_runs.annual_pnl_2025,
        strategy_backtest_runs.annual_pnl_2026,
        strategy_backtest_runs.annual_pnl_2024,
        strategy_backtest_runs.sharpe_oos,
        strategy_backtest_runs.returns_oos,
        strategy_backtest_runs.max_drawdown_oos,
        strategy_backtest_runs.trade_count_oos,
        strategy_backtest_runs.win_rate_oos,
        strategy_backtest_runs.profit_factor_oos,
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
),
strategy_capital AS (
    SELECT strategy_registry.strategy_id,
        strategy_registry.assigned_capital
    FROM gold.strategy_registry
),
live_metrics AS (
    SELECT pts.strategy_id,
        COALESCE(sum(pts.pnl) / NULLIF(sc.assigned_capital, 0::numeric) * 100::numeric, NULL::numeric) AS live_pnl,
        CASE
            WHEN count(*) FILTER (WHERE pts.status = 'closed'::text) > 0 THEN count(*) FILTER (WHERE pts.status = 'closed'::text AND pts.pnl > 0::numeric)::numeric * 100.0 / NULLIF(count(*) FILTER (WHERE pts.status = 'closed'::text), 0)::numeric
            ELSE NULL::numeric
        END AS livewr,
        CASE
            WHEN sum(pts.pnl) FILTER (WHERE pts.status = 'closed'::text AND pts.pnl < 0::numeric) < 0::numeric THEN COALESCE(sum(pts.pnl) FILTER (WHERE pts.status = 'closed'::text AND pts.pnl > 0::numeric), 0::numeric) / NULLIF(abs(sum(pts.pnl) FILTER (WHERE pts.status = 'closed'::text AND pts.pnl < 0::numeric)), 0::numeric)
            ELSE NULL::numeric
        END AS livepf,
        count(*) FILTER (WHERE pts.status = 'closed'::text) AS live_trades_closed
    FROM gold.paper_trades_synthetic pts
    JOIN strategy_capital sc ON sc.strategy_id::text = pts.strategy_id
    GROUP BY pts.strategy_id, sc.assigned_capital
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
        (r.priority::text = ANY (ARRAY['EXPERIMENTAL'::text, 'NEAR_GOLDEN'::text, 'GOLDEN'::text]))
            AND (r.status::text <> ALL (ARRAY['retired'::text, 'paused'::text]))
            AND (res.status::text <> ALL (ARRAY['rejected'::text, 'retired'::text]))
            AND b.sharpe_oos >= 0.5
            AND abs(COALESCE(b.max_drawdown_oos, 0::numeric)) <= 0.20
            AND (b.trade_count_oos >= 30 OR (r.strategy_id::text = ANY (ARRAY['HK_Quality_BlueChips'::text])))
            AND b.returns_oos IS NOT NULL AS publishable,
        b.annual_pnl_2025,
        b.annual_pnl_2026,
        b.annual_pnl_2024
    FROM gold.strategy_registry r
    JOIN gold.strategy_research res ON res.strategy_id::text = r.strategy_id::text
    LEFT JOIN latest_backtest b ON b.strategy_id::text = r.strategy_id::text
    LEFT JOIN latest_ticker_score lts ON lts.strategy_id::text = r.strategy_id::text
)
SELECT s.strategy_id AS id,
    s.name,
    COALESCE(upper(s.asset_class::text), 'EQUITY'::text) AS asset,
    CASE
        WHEN s.frequency::text = ANY (ARRAY['daily'::text, 'intraday'::text, 'day'::text, 'event'::text]) THEN 'day'::text
        WHEN s.frequency::text = ANY (ARRAY['weekly'::text, 'swing'::text]) THEN 'swing'::text
        WHEN s.frequency::text = ANY (ARRAY['monthly'::text, 'quarterly'::text, 'position'::text]) THEN 'position'::text
        ELSE 'swing'::text
    END AS horizon,
    CASE
        WHEN upper(s.priority::text) = 'GOLDEN'::text THEN 'T1'::text
        WHEN upper(s.priority::text) = 'NEAR_GOLDEN'::text THEN 'T2'::text
        ELSE 'T3'::text
    END AS tier,
    CASE
        WHEN upper(s.priority::text) = 'GOLDEN'::text AND s.approved_at IS NOT NULL THEN 'golden'::text
        WHEN upper(s.priority::text) = 'NEAR_GOLDEN'::text AND s.approved_at IS NOT NULL THEN 'near_golden'::text
        WHEN upper(s.priority::text) = 'GOLDEN'::text AND s.approved_at IS NULL THEN 'near_golden'::text
        WHEN upper(s.priority::text) = 'NEAR_GOLDEN'::text AND s.approved_at IS NULL THEN 'experimental'::text
        WHEN s.registry_status::text = 'paper'::text THEN 'golden'::text
        WHEN s.registry_status::text = 'live'::text THEN 'deployed'::text
        ELSE 'experimental'::text
    END AS stage,
    s.win_rate_oos * 100::numeric AS btwr,
    lm.livewr,
    s.profit_factor_oos AS btpf,
    lm.livepf,
    s.trade_count_oos AS trades,
    s.returns_oos * 100::numeric AS returns,
    s.sharpe_oos::numeric AS sharpe,
    (- abs(COALESCE(s.max_drawdown_oos, 0::numeric))) * 100::numeric AS dd,
    CASE
        WHEN s.paper_position_status::text = ANY (ARRAY['PAPER'::text, 'paper'::text]) THEN 'PAPER_TRADING'::text
        WHEN s.registry_status::text = 'live'::text THEN 'LIVE_TRADING'::text
        ELSE 'SIMULATION'::text
    END AS mode,
    NULL::jsonb AS margin,
    s.research_status AS db_status,
    s.frequency,
    'trade_algo_researcher'::text AS agent_source,
    s.updated_at,
    lm.live_pnl,
    CASE
        WHEN NOT s.publishable THEN 'not_publishable'::text
        WHEN s.profit_factor_oos IS NULL AND s.trade_count_oos > 0 THEN 'missing_pf'::text
        WHEN s.sharpe_oos IS NULL AND s.trade_count_oos > 0 THEN 'missing_sharpe'::text
        WHEN abs(COALESCE(s.max_drawdown_oos, 0::numeric)) = 0::numeric AND s.trade_count_oos > 1 THEN 'suspicious_zero_dd'::text
        ELSE 'ok'::text
    END AS metric_valid_flag,
    s.annual_pnl_2025 * 100::numeric AS annual_pnl_2025,
    s.annual_pnl_2026 * 100::numeric AS annual_pnl_2026,
    s.annual_pnl_2024 * 100::numeric AS annual_pnl_2024
FROM published s
LEFT JOIN live_metrics lm ON lm.strategy_id = s.strategy_id::text
WHERE s.publishable
ORDER BY (
    CASE
        WHEN upper(s.priority::text) = 'GOLDEN'::text AND s.approved_at IS NOT NULL THEN 'golden'::text
        WHEN upper(s.priority::text) = 'NEAR_GOLDEN'::text AND s.approved_at IS NOT NULL THEN 'near_golden'::text
        WHEN upper(s.priority::text) = 'GOLDEN'::text AND s.approved_at IS NULL THEN 'near_golden'::text
        WHEN upper(s.priority::text) = 'NEAR_GOLDEN'::text AND s.approved_at IS NULL THEN 'experimental'::text
        WHEN s.registry_status::text = 'paper'::text THEN 'golden'::text
        WHEN s.registry_status::text = 'live'::text THEN 'deployed'::text
        ELSE 'experimental'::text
    END), s.updated_at DESC;
