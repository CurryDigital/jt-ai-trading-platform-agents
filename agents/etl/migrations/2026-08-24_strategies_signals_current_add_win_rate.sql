-- t_bc9e8d3c: backend /api/signals/1 selects s.win_rate from
-- consumption.strategies_signals_current; column never existed.
-- Data-owner decision: add canonical win_rate column, sourced from
-- gold.strategy_registry.win_rate_oos (OOS backtest win rate, fraction 0-1,
-- the same canonical metric feeding v_pipeline_ui_feed.btwr).
-- Maintained by rebuild_paper_positions.py after each signal upsert
-- (UPDATE ... FROM gold.strategy_registry), so it refreshes with every run.

ALTER TABLE consumption.strategies_signals_current
    ADD COLUMN IF NOT EXISTS win_rate NUMERIC;

UPDATE consumption.strategies_signals_current s
SET    win_rate = r.win_rate_oos
FROM   gold.strategy_registry r
WHERE  s.strategy_id = r.strategy_id;
