-- Remediation part 2 (kanban t_5f69e8c0): close remaining delta-stacked
-- excess entries in three more sleeves sharing the same over-deployment bug.
--
--   etf_vix_scaled_11: IEF 82,645.92 entered 2026-09-15 on top of
--     183,979.10 -> 266,625.02 vs 200,000 assigned. Close IEF -> 183,979.10.
--   us_stk_lowbeta_14: ADBE/LHX/WDAY 61,909.26 entered 2026-09-01 on top of
--     497,807.00 -> 559,716.26 vs 500,000. Close the 3 adds -> 497,807.00.
--   etf_def_sector_rot_12_w: SPY 49,989.55 entered 2026-09-08 on top of
--     98,496.00 -> 148,485.55 vs 100,000. Close SPY -> 98,496.00.
--
-- Same MANUAL_CLOSE convention as part 1 / remediate_retired_open_paper_trades.sql.

BEGIN;

INSERT INTO gold.paper_trades_synthetic_bak_t_5f69e8c0
SELECT p.* FROM gold.paper_trades_synthetic p
WHERE p.status = 'open'
  AND (p.strategy_id, p.ticker) IN (
        ('etf_vix_scaled_11', 'IEF'),
        ('us_stk_lowbeta_14', 'ADBE'),
        ('us_stk_lowbeta_14', 'LHX'),
        ('us_stk_lowbeta_14', 'WDAY'),
        ('etf_def_sector_rot_12_w', 'SPY'));

WITH latest_px AS (
    SELECT DISTINCT ON (u.ticker)
           u.ticker, u.date AS px_date, u.close AS px_close
    FROM silver.unified_prices u
    WHERE u.ticker IN ('IEF', 'ADBE', 'LHX', 'WDAY', 'SPY')
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
        ('etf_vix_scaled_11', 'IEF'),
        ('us_stk_lowbeta_14', 'ADBE'),
        ('us_stk_lowbeta_14', 'LHX'),
        ('us_stk_lowbeta_14', 'WDAY'),
        ('etf_def_sector_rot_12_w', 'SPY'));

COMMIT;

-- Verification
SELECT id, strategy_id, ticker, status, entry_date, exit_date,
       exit_price, exit_price_basis, n_shares, pnl::numeric(14,2), pnl_pct::numeric(10,4)
FROM gold.paper_trades_synthetic
WHERE exit_price_basis = 'MANUAL_CLOSE'
  AND strategy_id IN ('etf_vix_scaled_11','us_stk_lowbeta_14','etf_def_sector_rot_12_w')
ORDER BY strategy_id, ticker;

SELECT r.strategy_id, r.assigned_capital,
       COALESCE(SUM(p.n_shares * p.entry_price), 0)::numeric(14,2) AS open_cost_basis
FROM gold.strategy_registry r
LEFT JOIN gold.paper_trades_synthetic p
       ON p.strategy_id = r.strategy_id AND p.status = 'open'
WHERE r.strategy_id IN ('etf_vix_scaled_11','us_stk_lowbeta_14','etf_def_sector_rot_12_w')
GROUP BY r.strategy_id, r.assigned_capital
ORDER BY r.strategy_id;
