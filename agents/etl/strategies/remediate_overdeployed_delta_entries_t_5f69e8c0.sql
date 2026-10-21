-- Remediation: close the over-budget delta entries that pushed two paper
-- sleeves' open cost basis above assigned capital (kanban t_5f69e8c0).
--
-- Root cause: rebuild_paper_positions.py delta mode sized NEW entries at
-- their full compute_target slot on top of retained positions (fixed in
-- code by clamp_new_opens this run). These 4 rows are the bug's product:
--   us_stk_sue_mom_01_v2: AVGO 38,610.50 + CIEN 26,382.30 entered 2026-09-01
--     on top of a 399,538.00 book -> 464,530.80 vs 400,000 assigned.
--   cn_stk_lowvol_12: 000001.SZ 9,728.22 + 600519.SS 9,119.60 entered
--     2026-09-02 on top of a 92,736.00 book -> 107,583.82 vs 100,000 assigned.
-- Closing them restores each book to its last valid (<= assigned) state.
-- If the tickers are still BUY, the patched engine re-books them right-sized
-- at the next rebalance via the normal NEXT_OPEN path.
--
-- Close convention matches remediate_retired_open_paper_trades.sql:
--   exit at the latest available silver.unified_prices close,
--   exit_price_basis = 'MANUAL_CLOSE', LONG pnl formulas.

BEGIN;

-- Rollback snapshot of the exact rows being closed.
CREATE TABLE IF NOT EXISTS gold.paper_trades_synthetic_bak_t_5f69e8c0 AS
SELECT * FROM gold.paper_trades_synthetic WHERE false;

INSERT INTO gold.paper_trades_synthetic_bak_t_5f69e8c0
SELECT p.* FROM gold.paper_trades_synthetic p
WHERE p.status = 'open'
  AND (p.strategy_id, p.ticker) IN (
        ('us_stk_sue_mom_01_v2', 'AVGO'),
        ('us_stk_sue_mom_01_v2', 'CIEN'),
        ('cn_stk_lowvol_12', '000001.SZ'),
        ('cn_stk_lowvol_12', '600519.SS'));

WITH latest_px AS (
    SELECT DISTINCT ON (u.ticker)
           u.ticker, u.date AS px_date, u.close AS px_close
    FROM silver.unified_prices u
    WHERE u.ticker IN ('AVGO', 'CIEN', '000001.SZ', '600519.SS')
    ORDER BY u.ticker, u.date DESC
)
UPDATE gold.paper_trades_synthetic p
SET status                 = 'closed',
    exit_date              = lp.px_date,
    exit_price             = lp.px_close,
    exit_price_source_date = lp.px_date,
    exit_price_basis       = 'MANUAL_CLOSE',
    pnl                    = CASE WHEN p.direction = 'SHORT'
                                  THEN (p.entry_price - lp.px_close)
                                  ELSE (lp.px_close - p.entry_price)
                             END * p.n_shares,
    pnl_pct                = CASE WHEN p.direction = 'SHORT'
                                  THEN (p.entry_price - lp.px_close)
                                  ELSE (lp.px_close - p.entry_price)
                             END / NULLIF(p.entry_price, 0) * 100,
    updated_at             = NOW()
FROM latest_px lp
WHERE p.ticker = lp.ticker
  AND p.status = 'open'
  AND lp.px_date >= p.entry_date   -- never close before entry (guards stale prices)
  AND (p.strategy_id, p.ticker) IN (
        ('us_stk_sue_mom_01_v2', 'AVGO'),
        ('us_stk_sue_mom_01_v2', 'CIEN'),
        ('cn_stk_lowvol_12', '000001.SZ'),
        ('cn_stk_lowvol_12', '600519.SS'));

COMMIT;

-- Verification (run after COMMIT):
-- 1. Closed rows with realized pnl.
SELECT id, strategy_id, ticker, status, entry_date, exit_date,
       entry_price, exit_price, exit_price_basis, n_shares, pnl, pnl_pct
FROM gold.paper_trades_synthetic
WHERE (strategy_id, ticker) IN (
        ('us_stk_sue_mom_01_v2', 'AVGO'),
        ('us_stk_sue_mom_01_v2', 'CIEN'),
        ('cn_stk_lowvol_12', '000001.SZ'),
        ('cn_stk_lowvol_12', '600519.SS'))
  AND entry_date >= DATE '2026-09-01'
ORDER BY strategy_id, ticker;

-- 2. Remaining open cost basis per sleeve vs assigned.
SELECT r.strategy_id, r.assigned_capital,
       COALESCE(SUM(p.n_shares * p.entry_price), 0)::numeric(14,2) AS open_cost_basis
FROM gold.strategy_registry r
LEFT JOIN gold.paper_trades_synthetic p
       ON p.strategy_id = r.strategy_id AND p.status = 'open'
WHERE r.strategy_id IN ('us_stk_sue_mom_01_v2', 'cn_stk_lowvol_12')
GROUP BY r.strategy_id, r.assigned_capital
ORDER BY r.strategy_id;
