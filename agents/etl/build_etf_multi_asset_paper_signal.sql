BEGIN;

-- Promote the strategy registry execution mode to PAPER and allocate notional capital
UPDATE gold.strategy_registry
SET execution_mode = 'PAPER',
    in_market_capital = assigned_capital,
    updated_at = now()
WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation'
  AND execution_mode <> 'PAPER';

-- Enrich per-ticker score records with risk/audit provenance and risk caps
UPDATE gold.strategy_ticker_scores
SET criteria_met = criteria_met
  || jsonb_build_object(
       'execution_mode', 'PAPER',
       'max_leverage', 1.0,
       'drawdown_halt', 0.12,
       'backtest_run_id', 'f3566fae-e585-48b8-87b3-b5b7e437f462',
       'risk_review_id', '39218752-8b51-45b3-b1df-57b3cbcbaad6',
       'risk_review_decision', 'APPROVED'
     ),
    updated_at = now()
WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation';

-- Publish per-ticker signal evaluations for the tactical family
INSERT INTO gold.signal_evaluations (
    market, ticker, family_key, direction, potential, change_pct, note, updated_at
)
SELECT
    'US',
    ticker,
    'tactical',
    'BUY',
    score,
    0,
    'ETF Multi-Asset Tactical Allocation: inverse-vol weight; weekly rebalance; 20% single-asset cap; 1.0 max leverage; halt on drawdown > 12%',
    now()
FROM gold.strategy_ticker_scores
WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation'
ON CONFLICT (market, ticker, family_key)
DO UPDATE SET
    direction = EXCLUDED.direction,
    potential = EXCLUDED.potential,
    change_pct = EXCLUDED.change_pct,
    note = EXCLUDED.note,
    updated_at = EXCLUDED.updated_at;

COMMIT;
