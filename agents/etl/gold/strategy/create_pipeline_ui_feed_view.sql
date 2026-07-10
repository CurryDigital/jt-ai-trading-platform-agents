-- Pipeline UI feed view: maps DB strategy statuses to UI pipeline stages.
-- Target format matches StrategyPipeline.jsx expectations:
-- id, name, asset, horizon, tier, stage, btWR, liveWR, btPF, livePF, trades, returns, sharpe, dd, mode, margin
CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS
WITH latest_backtest AS (
    SELECT DISTINCT ON (strategy_id)
        strategy_id,
        sharpe_oos AS sharpe_ratio,
        returns_oos AS total_return,
        max_drawdown_oos AS max_drawdown,
        trade_count_oos AS trade_count,
        win_rate_oos AS win_rate,
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
)
SELECT
    s.strategy_id AS id,
    s.name,
    COALESCE(UPPER(s.asset_class), 'EQUITY') AS asset,
    CASE
        WHEN s.frequency IN ('daily','intraday','day') THEN 'day'
        WHEN s.frequency IN ('weekly','swing') THEN 'swing'
        WHEN s.frequency IN ('monthly','quarterly','position') THEN 'position'
        ELSE 'swing'
    END AS horizon,
    CASE
        WHEN b.all_risk_gates_passed AND s.status = 'approved' THEN 'T1'
        WHEN b.all_risk_gates_passed AND s.status IN ('risk_review','backtesting') THEN 'T2'
        ELSE 'T3'
    END AS tier,
    CASE s.status
        WHEN 'approved' THEN 'deployed'
        WHEN 'risk_review' THEN 'golden'
        WHEN 'backtesting' THEN 'near_golden'
        WHEN 'rejected' THEN 'experimental'
        ELSE 'experimental'
    END AS stage,
    COALESCE(b.win_rate * 100, 0)::numeric AS btWR,
    NULL::numeric AS liveWR,
    NULL::numeric AS btPF,
    NULL::numeric AS livePF,
    COALESCE(b.trade_count, 0) AS trades,
    COALESCE(b.total_return * 100, 0)::numeric AS returns,
    COALESCE(b.sharpe_ratio, 0)::numeric AS sharpe,
    COALESCE(b.max_drawdown * 100, 0)::numeric AS dd,
    CASE
        WHEN lts.position_status IN ('PAPER','paper') THEN 'PAPER_TRADING'
        WHEN s.status = 'approved' THEN 'LIVE_TRADING'
        ELSE 'SIMULATION'
    END AS mode,
    NULL::jsonb AS margin,
    s.status AS db_status,
    s.frequency,
    s.source AS agent_source,
    s.updated_at
FROM gold.strategy_research s
LEFT JOIN latest_backtest b ON b.strategy_id = s.strategy_id::text
LEFT JOIN latest_ticker_score lts ON lts.strategy_id = s.strategy_id::text
ORDER BY s.status, s.updated_at DESC;

COMMENT ON VIEW gold.v_pipeline_ui_feed IS 'Pipeline UI feed: maps gold.strategy_research + latest backtest metrics to the StrategyPipeline.jsx card schema.';
