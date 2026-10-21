-- 2026-07-29: portfolio_positions_current — drop legacy UNIQUE(ticker)
--
-- Task t_749e13f0. The table originally held only live IBKR + manual
-- positions, where one row per ticker was a sane invariant. It now also
-- carries PAPER_TRADING rows sourced from gold.paper_trades_synthetic, and
-- multiple paper strategies legitimately hold the same ticker
-- (CSX x4, VNQ/IWM/AGG/KO/SCHD x3 as of 2026-07-29). The correct uniqueness
-- invariant is (strategy_id, ticker), already enforced by
-- uq_portfolio_positions_current_strategy_ticker.
--
-- Writers updated in the same change:
--   consumption/portfolio/portfolio_positions_risk.py  ON CONFLICT (ticker) -> (strategy_id, ticker)
--   gold/portfolio/build_manual_positions.py           ON CONSTRAINT ..._ticker_key -> (strategy_id, ticker)

BEGIN;

ALTER TABLE consumption.portfolio_positions_current
    DROP CONSTRAINT IF EXISTS portfolio_positions_current_ticker_key;

COMMIT;
