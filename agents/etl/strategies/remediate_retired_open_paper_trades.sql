-- Remediation: close residual open rows in gold.paper_trades_synthetic whose
-- strategy is retired in gold.strategy_registry.
--
-- Context: kanban t_cb0b4b98 (QA follow-up to t_e6fbd6dc / t_465e0c5f).
-- QA flagged 3 rows (ids 2416 JEPQ, 2385 GC=F, 735 JEPI) for the two strategies
-- retired 2026-07-31 (gc_cot_contrarian_inverse, ETF_Covered_Call_Income_Rotation),
-- but a full sweep found 29 open rows across 12 retired strategies. Acceptance
-- criterion 3 requires ZERO open rows for any retired strategy, so this script
-- sweeps generically rather than hard-coding ids.
--
-- Close convention (matches engine semantics):
--   exit at the latest available silver.unified_prices close
--   exit_price_basis = 'MANUAL_CLOSE' (existing precedent for operator closes)
--   pnl     = (exit - entry) * n_shares           (LONG; inverted for SHORT)
--   pnl_pct = (exit/entry - 1) * 100              (percent units, LONG; inverted for SHORT)
--   futures rows (e.g. GC=F) are unit-sized without contract multiplier,
--   consistent with existing paper-ledger policy.
--
-- Idempotent: the WHERE clause targets status='open' joined to retired registry
-- rows only; a second run updates 0 rows.

BEGIN;

WITH latest_px AS (
    SELECT DISTINCT ON (u.ticker)
           u.ticker, u.date AS px_date, u.close AS px_close
    FROM silver.unified_prices u
    WHERE u.ticker IN (
        SELECT DISTINCT p.ticker
        FROM gold.paper_trades_synthetic p
        JOIN gold.strategy_registry r ON r.strategy_id = p.strategy_id
        WHERE p.status = 'open' AND r.status = 'retired'
    )
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
  AND EXISTS (SELECT 1 FROM gold.strategy_registry r
              WHERE r.strategy_id = p.strategy_id AND r.status = 'retired');

COMMIT;

-- Acceptance verification (run after COMMIT):

-- 1. Must return 0 rows: no open rows for any retired strategy.
SELECT p.id, p.strategy_id, p.ticker, p.status
FROM gold.paper_trades_synthetic p
JOIN gold.strategy_registry r ON r.strategy_id = p.strategy_id
WHERE p.status = 'open' AND r.status = 'retired';

-- 2. QA-flagged rows must be closed.
SELECT id, strategy_id, ticker, status, exit_date, exit_price, exit_price_basis, pnl, pnl_pct
FROM gold.paper_trades_synthetic
WHERE id IN (2416, 2385, 735)
ORDER BY id;

-- 3. Sweep summary: rows closed by this remediation.
SELECT strategy_id, COUNT(*) AS closed_rows, SUM(pnl) AS total_realized_pnl
FROM gold.paper_trades_synthetic
WHERE exit_price_basis = 'MANUAL_CLOSE'
  AND exit_date >= DATE '2026-08-20'
GROUP BY strategy_id
ORDER BY strategy_id;
