-- 2026-09-07 t_d152898f: rebuild consumption.strategy_monthly_returns from
-- research backtest engines' own portfolio-level daily curves (gold table),
-- replacing unweighted SUM(pnl_pct) exit-month attribution + unit sniffing.
--
-- consumption.strategy_monthly_returns keeps its column contract:
--   strategy_id, year, month, return_pct (decimal fraction),
--   benchmark_return_pct (NULL), excess_return_pct (NULL)

CREATE TABLE IF NOT EXISTS gold.strategy_backtest_monthly_returns (
    strategy_id   text        NOT NULL,
    year          smallint    NOT NULL,
    month         smallint    NOT NULL,
    return_pct    numeric     NOT NULL,          -- decimal fraction, e.g. 0.0234 = +2.34%
    source        text        NOT NULL,          -- 'research_curve' | 'trades_recon_single_position'
    artifact      text,                          -- research artifact path (NULL for trades recon)
    window_return numeric     NOT NULL,          -- compounded window return reproduced at ingest
    run_id        uuid,                          -- gold.strategy_backtest_runs row verified against
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_id, year, month)
);

DROP VIEW IF EXISTS consumption.strategy_monthly_returns;

CREATE VIEW consumption.strategy_monthly_returns AS
SELECT strategy_id::varchar AS strategy_id,
       year::int            AS year,
       month::int           AS month,
       ROUND(return_pct, 6) AS return_pct,
       NULL::numeric        AS benchmark_return_pct,
       NULL::numeric        AS excess_return_pct
FROM gold.strategy_backtest_monthly_returns;
