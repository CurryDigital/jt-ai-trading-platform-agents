-- 017_regime_forecast_v2.sql
-- Regime forecast v2 (nowcast_markov_v2):
--   * gold.regime_forecast gains method + is_stale columns (additive; UI contract
--     on scope/day_offset/risk_on_pct/forecast_date/updated_at unchanged).
--   * gold.regime_forecast_params sidecar holds fitted Markov params (T matrix,
--     state -> P(fwd 21d SPY ret > 0), fit window) for auditability; refit quarterly.
--   * consumption.macro_regime_7d recreated with the new columns appended.

ALTER TABLE gold.regime_forecast
    ADD COLUMN IF NOT EXISTS method varchar(40) DEFAULT 'v1_heuristic';

ALTER TABLE gold.regime_forecast
    ADD COLUMN IF NOT EXISTS is_stale boolean DEFAULT false;

CREATE TABLE IF NOT EXISTS gold.regime_forecast_params (
    id                 serial PRIMARY KEY,
    fit_date           date NOT NULL,
    fit_window_start   date NOT NULL,
    fit_window_end     date NOT NULL,
    n_obs              integer NOT NULL,
    state_order        jsonb NOT NULL,  -- e.g. ["CARRY","MEAN_REV","TREND"]
    state_probs        jsonb NOT NULL,  -- {state: P(fwd 21d SPY return > 0 | hmm_label = state)}
    transition_matrix  jsonb NOT NULL,  -- row-normalized T, rows/cols in state_order
    method             varchar(40) NOT NULL DEFAULT 'nowcast_markov_v2',
    created_at         timestamp NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW consumption.macro_regime_7d AS
SELECT DISTINCT ON (scope, day_offset)
    scope,
    day_offset,
    risk_on_pct,
    forecast_date,
    updated_at,
    method,
    is_stale
FROM gold.regime_forecast
ORDER BY scope, day_offset, forecast_date DESC;
