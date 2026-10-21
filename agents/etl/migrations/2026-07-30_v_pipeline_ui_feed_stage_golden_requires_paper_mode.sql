-- Migration: 2026-07-30
-- Task: t_f51d67fe
-- Purpose: align gold.v_pipeline_ui_feed stage derivation with the canonical
--          lifecycle rule used by the frontend stageFor (Pipeline/Performance):
--          stage='golden' requires status='paper' AND execution_mode=PAPER_TRADING.
--          In DB terms the PAPER_TRADING signal is
--          gold.strategy_paper_monitoring.is_active (kept in sync with
--          strategy_registry.execution_mode='PAPER' by trg_sync_strategy_paper_monitoring).
--
-- Background:
--   The stage CASE had a fall-through branch
--       WHEN registry_status='paper' THEN 'golden'
--   which ignored execution_mode/monitoring, so ETF_HK_Balanced_Trend
--   (status=paper, execution_mode=SIMULATION, priority=EXPERIMENTAL,
--   monitoring deactivated 2026-07-29) surfaced as stage='golden'.
--
-- Changes:
--   1. stage CASE (SELECT list and ORDER BY): the registry_status='paper'
--      branch now also requires is_paper_monitoring.
--   2. No output column changes (CREATE OR REPLACE VIEW).
--
-- Generated from the live view definition via pg_get_viewdef to avoid drift.

CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS
 WITH latest_backtest AS (
         SELECT DISTINCT ON (strategy_backtest_runs.strategy_id) strategy_backtest_runs.strategy_id,
            strategy_backtest_runs.run_id,
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
        ), latest_ticker_score AS (
         SELECT DISTINCT ON (strategy_ticker_scores.strategy_id) strategy_ticker_scores.strategy_id,
            strategy_ticker_scores.signal_action,
            strategy_ticker_scores.position_status,
            strategy_ticker_scores.score
           FROM gold.strategy_ticker_scores
          ORDER BY strategy_ticker_scores.strategy_id, strategy_ticker_scores.updated_at DESC
        ), strategy_capital AS (
         SELECT strategy_registry.strategy_id,
            strategy_registry.assigned_capital
           FROM gold.strategy_registry
        ), paper_monitoring AS (
         SELECT strategy_paper_monitoring.strategy_id,
            strategy_paper_monitoring.is_active
           FROM gold.strategy_paper_monitoring
        ), live_metrics AS (
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
             JOIN paper_monitoring pm ON pm.strategy_id = pts.strategy_id AND pm.is_active = true
          GROUP BY pts.strategy_id, sc.assigned_capital
        ), synthetic_metrics AS (
         SELECT live_metrics.strategy_id,
            live_metrics.live_pnl AS live_pnl_synthetic,
            live_metrics.livewr AS livewr_synthetic,
            live_metrics.livepf AS livepf_synthetic,
            live_metrics.live_trades_closed AS synthetic_trades_closed
           FROM live_metrics
        ), current_year_wr AS (
         SELECT sbt.strategy_id,
            count(*) FILTER (WHERE sbt.exit_date IS NOT NULL AND EXTRACT(year FROM sbt.exit_date) = EXTRACT(year FROM CURRENT_DATE)) AS cy_closed,
            count(*) FILTER (WHERE sbt.exit_date IS NOT NULL AND EXTRACT(year FROM sbt.exit_date) = EXTRACT(year FROM CURRENT_DATE) AND sbt.pnl_pct > 0::numeric) AS cy_wins
           FROM gold.strategy_backtest_trades sbt
             JOIN latest_backtest lb ON lb.run_id = sbt.run_id
          GROUP BY sbt.strategy_id
        ), published AS (
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
            COALESCE(pm.is_active, false) AS is_paper_monitoring,
            (r.priority::text = ANY (ARRAY['EXPERIMENTAL'::text, 'NEAR_GOLDEN'::text, 'GOLDEN'::text])) AND (r.status::text <> ALL (ARRAY['retired'::text])) AND (r.status::text <> 'paused'::text OR r.execution_mode::text = 'SIMULATION'::text) AND (res.status::text <> ALL (ARRAY['rejected'::text, 'retired'::text])) AND b.sharpe_oos >= 0.5 AND abs(COALESCE(b.max_drawdown_oos, 0::numeric)) <= 0.20 AND (b.trade_count_oos >= 30 OR (r.strategy_id::text = ANY (ARRAY['HK_Quality_BlueChips'::text]))) AND b.returns_oos IS NOT NULL AS publishable,
            b.annual_pnl_2025,
            b.annual_pnl_2026,
            b.annual_pnl_2024
           FROM gold.strategy_registry r
             JOIN gold.strategy_research res ON res.strategy_id::text = r.strategy_id::text
             LEFT JOIN latest_backtest b ON b.strategy_id::text = r.strategy_id::text
             LEFT JOIN latest_ticker_score lts ON lts.strategy_id::text = r.strategy_id::text
             LEFT JOIN paper_monitoring pm ON pm.strategy_id = r.strategy_id::text
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
            WHEN s.registry_status::text = 'paper'::text AND s.is_paper_monitoring THEN 'golden'::text
            WHEN s.registry_status::text = 'live'::text THEN 'deployed'::text
            ELSE 'experimental'::text
        END AS stage,
    s.win_rate_oos * 100::numeric AS btwr,
        CASE
            WHEN s.is_paper_monitoring THEN lm.livewr
            ELSE NULL::numeric
        END AS livewr,
    s.profit_factor_oos AS btpf,
        CASE
            WHEN s.is_paper_monitoring THEN lm.livepf
            ELSE NULL::numeric
        END AS livepf,
    s.trade_count_oos AS trades,
    s.returns_oos * 100::numeric AS returns,
    s.sharpe_oos::numeric AS sharpe,
    (- abs(COALESCE(s.max_drawdown_oos, 0::numeric))) * 100::numeric AS dd,
        CASE
            WHEN s.is_paper_monitoring THEN 'PAPER_TRADING'::text
            WHEN s.registry_status::text = 'live'::text THEN 'LIVE_TRADING'::text
            ELSE 'SIMULATION'::text
        END AS mode,
    NULL::jsonb AS margin,
    s.research_status AS db_status,
    s.frequency,
    'trade_algo_researcher'::text AS agent_source,
    s.updated_at,
        CASE
            WHEN s.is_paper_monitoring THEN lm.live_pnl
            ELSE NULL::numeric
        END AS live_pnl,
    sm.livewr_synthetic,
    sm.livepf_synthetic,
    sm.live_pnl_synthetic,
        CASE
            WHEN NOT s.publishable THEN 'not_publishable'::text
            WHEN s.profit_factor_oos IS NULL AND s.trade_count_oos > 0 THEN 'missing_pf'::text
            WHEN s.sharpe_oos IS NULL AND s.trade_count_oos > 0 THEN 'missing_sharpe'::text
            WHEN abs(COALESCE(s.max_drawdown_oos, 0::numeric)) = 0::numeric AND s.trade_count_oos > 1 THEN 'suspicious_zero_dd'::text
            ELSE 'ok'::text
        END AS metric_valid_flag,
    s.annual_pnl_2025 * 100::numeric AS annual_pnl_2025,
    s.annual_pnl_2026 * 100::numeric AS annual_pnl_2026,
    s.annual_pnl_2024 * 100::numeric AS annual_pnl_2024,
    cw.cy_wins::numeric * 100.0 / NULLIF(cw.cy_closed, 0)::numeric AS current_year_wr,
    s.is_paper_monitoring
   FROM published s
     LEFT JOIN live_metrics lm ON lm.strategy_id = s.strategy_id::text
     LEFT JOIN synthetic_metrics sm ON sm.strategy_id = s.strategy_id::text
     LEFT JOIN current_year_wr cw ON cw.strategy_id::text = s.strategy_id::text
  WHERE s.publishable
  ORDER BY (
        CASE
            WHEN upper(s.priority::text) = 'GOLDEN'::text AND s.approved_at IS NOT NULL THEN 'golden'::text
            WHEN upper(s.priority::text) = 'NEAR_GOLDEN'::text AND s.approved_at IS NOT NULL THEN 'near_golden'::text
            WHEN upper(s.priority::text) = 'GOLDEN'::text AND s.approved_at IS NULL THEN 'near_golden'::text
            WHEN upper(s.priority::text) = 'NEAR_GOLDEN'::text AND s.approved_at IS NULL THEN 'experimental'::text
            WHEN s.registry_status::text = 'paper'::text AND s.is_paper_monitoring THEN 'golden'::text
            WHEN s.registry_status::text = 'live'::text THEN 'deployed'::text
            ELSE 'experimental'::text
        END), s.updated_at DESC;