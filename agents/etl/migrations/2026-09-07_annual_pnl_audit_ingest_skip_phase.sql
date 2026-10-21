-- 2026-09-07 t_589e846f: allow phase='ingest_skip' in the annual_pnl audit
-- table so gold/strategy/refresh_annual_backtest_returns.py can durably record
-- correction-preserving skips: strategies gated
-- gold.strategy_configs.trades_sum_is_book_annual_return=false have their
-- annual_pnl_YYYY columns owned by the correction pipeline
-- (audit/apply_annual_pnl_correction.py, t_6ea23eae), and the metrics ingest
-- must NOT overwrite them with trades sums or any other ingest source.
--
-- phase='ingest_skip' row semantics (per-column, like phase='update'):
--   column_name / old_value = current DB value preserved by the guard
--   new_value               = the value the ingest WOULD have written
--   written only when an ingest source disagreed with the DB value, i.e. an
--   overwrite was actually prevented.

ALTER TABLE gold.strategy_backtest_runs_annual_pnl_audit
    DROP CONSTRAINT strategy_backtest_runs_annual_pnl_audit_phase_check;

ALTER TABLE gold.strategy_backtest_runs_annual_pnl_audit
    ADD CONSTRAINT strategy_backtest_runs_annual_pnl_audit_phase_check
        CHECK (phase IN ('before_snapshot', 'update', 'ingest_skip'));
