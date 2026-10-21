-- 2026-09-09 OOS-window extension refresh (kanban t_f5e3164b)
--
-- Scheduled weekly job (Hermes cron qr_etl.oos_window_refresh) re-runs the
-- research backtest engine for paper-deployed, script-reproducible strategies
-- with time-based exits, extending oos_end to the latest available price date.
-- Without this, gold.strategy_backtest_trades keeps stale OPEN rows on the
-- Simulation tab whenever a position's scheduled exit falls after the last
-- research run's window end (concrete instance: t_c84850c0, run 4e941d50).
--
-- 1. Audit log table: one row per strategy per job pass.
-- 2. Engine registry: gold.strategy_configs config_key='oos_window_refresh_engine'
--    gates which paper strategies the job may refresh (registry-gated, never a
--    blind scan of the research workspace). Absent row => strategy is skipped.

CREATE TABLE IF NOT EXISTS gold.oos_window_refresh_log (
    id              bigserial PRIMARY KEY,
    run_at          timestamptz NOT NULL DEFAULT now(),
    strategy_id     text NOT NULL,
    status          text NOT NULL,           -- ok | skipped_no_change | skipped_not_reproducible | error
    prev_run_id     uuid,
    new_run_id      uuid,
    prev_oos_end    date,
    new_oos_end     date,
    trades_before   integer,
    trades_after    integer,
    open_before     integer,
    open_after      integer,
    message         text
);

CREATE INDEX IF NOT EXISTS idx_oos_window_refresh_log_sid
    ON gold.oos_window_refresh_log (strategy_id, run_at DESC);

-- Engine registry seeds: HK IPO book (all status='paper', engines verified
-- script-reproducible 2026-09-09; artifacts written alongside the engine).
INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value) VALUES
('hk_ipo_postlisting_drift_p1_v3', 'oos_window_refresh_engine', '{
  "engine": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_pulse_v3.py",
  "results_json": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_pulse_V3_results.json",
  "trades_csv": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_pulse_V3_trades.csv",
  "exit_reason_default": "time_exit_20td",
  "max_single_asset_exposure": 0.2,
  "timeout_seconds": 900
}'::jsonb),
('hk_ipo_day1_green_momentum_v1', 'oos_window_refresh_engine', '{
  "engine": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_day1_green_v1.py",
  "results_json": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_day1_green_V1_results.json",
  "trades_csv": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_day1_green_V1_trades.csv",
  "exit_reason_default": "time_exit_5td",
  "max_single_asset_exposure": 0.2,
  "timeout_seconds": 900
}'::jsonb),
('hk_ipo_postlisting_drift_p2', 'oos_window_refresh_engine', '{
  "engine": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_pulse_p2.py",
  "results_json": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_pulse_P2_results.json",
  "trades_csv": "/home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/ipo_pulse_P2_trades.csv",
  "exit_reason_default": "time_exit_20td",
  "max_single_asset_exposure": 0.2,
  "timeout_seconds": 900
}'::jsonb)
ON CONFLICT (strategy_id, config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = now();
