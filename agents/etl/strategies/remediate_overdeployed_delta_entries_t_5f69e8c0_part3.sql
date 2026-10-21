-- Remediation part 3 (kanban t_5f69e8c0): right-size the two sleeves whose
-- assigned capital was halved by the 2026-09-18 R2 review (parent t_4d006064)
-- without right-sizing the sim book:
--   ETF_Global_Risk_Parity_VolTarget:      91,772.15 open vs 50,000  (100k->50k)
--   ETF_Multi_Asset_Tactical_Allocation:  250,133.85 open vs 125,000 (250k->125k)
--
-- Close ALL open rows MANUAL_CLOSE (honest realized PnL preserved — the
-- engine's --backfill would DELETE the trade history, so it is not used).
-- Immediately after this script, the patched engine is run scoped
-- (--force-rebalance --strategy-id, delta mode) to re-book today's targets
-- at the new capital via NEXT_OPEN pending orders.

BEGIN;

INSERT INTO gold.paper_trades_synthetic_bak_t_5f69e8c0
SELECT p.* FROM gold.paper_trades_synthetic p
WHERE p.status = 'open'
  AND p.strategy_id IN ('ETF_Global_Risk_Parity_VolTarget',
                        'ETF_Multi_Asset_Tactical_Allocation');

WITH latest_px AS (
    SELECT DISTINCT ON (u.ticker)
           u.ticker, u.date AS px_date, u.close AS px_close
    FROM silver.unified_prices u
    WHERE u.ticker IN (SELECT DISTINCT ticker FROM gold.paper_trades_synthetic
                       WHERE status = 'open'
                         AND strategy_id IN ('ETF_Global_Risk_Parity_VolTarget',
                                             'ETF_Multi_Asset_Tactical_Allocation'))
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
  AND lp.px_date >= p.entry_date
  AND p.strategy_id IN ('ETF_Global_Risk_Parity_VolTarget',
                        'ETF_Multi_Asset_Tactical_Allocation');

COMMIT;

-- Verification
SELECT strategy_id, COUNT(*) AS closed_rows, SUM(pnl)::numeric(14,2) AS realized_pnl
FROM gold.paper_trades_synthetic
WHERE exit_price_basis = 'MANUAL_CLOSE'
  AND strategy_id IN ('ETF_Global_Risk_Parity_VolTarget',
                      'ETF_Multi_Asset_Tactical_Allocation')
GROUP BY strategy_id;

SELECT strategy_id, COUNT(*) AS still_open
FROM gold.paper_trades_synthetic
WHERE status = 'open'
  AND strategy_id IN ('ETF_Global_Risk_Parity_VolTarget',
                      'ETF_Multi_Asset_Tactical_Allocation')
GROUP BY strategy_id;
