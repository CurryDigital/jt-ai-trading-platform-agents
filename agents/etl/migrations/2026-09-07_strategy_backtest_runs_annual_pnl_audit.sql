-- 2026-09-07 t_ce0deace: audit table for legacy annual_pnl_YYYY values in
-- gold.strategy_backtest_runs ahead of the book-annual correction (t_6ea23eae,
-- origin t_d152898f).
--
-- Two row kinds share one table:
--   phase='before_snapshot' : wide pre-correction capture (rollback record).
--     Populated by agents/etl/audit/snapshot_annual_pnl_audit.py for the latest
--     run of each strategy published in consumption.strategy_monthly_returns.
--   phase='update'          : per-column change log written by the correction
--     task (t_86a4a973): column_name + old_value + new_value, wide columns NULL.

CREATE TABLE IF NOT EXISTS gold.strategy_backtest_runs_annual_pnl_audit (
    audit_id                          bigserial    PRIMARY KEY,
    phase                             text         NOT NULL
        CHECK (phase IN ('before_snapshot', 'update')),
    task_id                           text         NOT NULL,  -- kanban task that wrote the row
    strategy_id                       text         NOT NULL,
    run_id                            uuid         NOT NULL,  -- gold.strategy_backtest_runs row
    -- wide snapshot columns (phase='before_snapshot')
    annual_pnl_2024                   numeric,
    annual_pnl_2025                   numeric,
    annual_pnl_2026                   numeric,
    returns_oos                       numeric,
    -- per-column change columns (phase='update')
    column_name                       text,
    old_value                         numeric,
    new_value                         numeric,
    -- gold.strategy_configs flag at capture time (false = book annuals verified)
    trades_sum_is_book_annual_return  boolean,
    captured_at                       timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sbr_annual_pnl_audit_strategy
    ON gold.strategy_backtest_runs_annual_pnl_audit (strategy_id, run_id);
CREATE INDEX IF NOT EXISTS ix_sbr_annual_pnl_audit_phase
    ON gold.strategy_backtest_runs_annual_pnl_audit (phase, task_id);
