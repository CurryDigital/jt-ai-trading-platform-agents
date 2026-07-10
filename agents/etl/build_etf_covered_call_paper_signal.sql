BEGIN;

-- Promote the strategy registry execution mode to PAPER and allocate notional capital
UPDATE gold.strategy_registry
SET execution_mode = 'PAPER',
    in_market_capital = assigned_capital,
    updated_at = now()
WHERE strategy_id = 'ETF_Covered_Call_Income_Rotation'
  AND execution_mode <> 'PAPER';

-- Publish per-ticker signal evaluations for the covered-call income family.
-- The target live weights are the research-approved static allocation:
--   JEPI 50%, JEPQ 50%
-- TLTW is part of the universe but receives a 0.0 explicit weight because
-- the live signal file only deploys JEPI/JEPQ today.
INSERT INTO gold.signal_evaluations (
    market, ticker, name, family_key, direction, potential, change_pct, note, updated_at
)
SELECT
    'US',
    ticker,
    ticker,
    'tactical',
    'BUY',
    CASE ticker
      WHEN 'JEPI' THEN 50.0
      WHEN 'JEPQ' THEN 50.0
      ELSE 0.0
    END,
    0,
    'Covered-Call Income ETF Rotation: static allocation; weekly rebalance; max single-asset 50%; 1.0 max leverage; halt on drawdown > 12%',
    now()
FROM UNNEST(ARRAY['JEPI', 'JEPQ', 'TLTW']) AS ticker
ON CONFLICT (market, ticker, family_key)
DO UPDATE SET
    name = EXCLUDED.name,
    direction = EXCLUDED.direction,
    potential = EXCLUDED.potential,
    change_pct = EXCLUDED.change_pct,
    note = EXCLUDED.note,
    updated_at = EXCLUDED.updated_at;

-- Persist per-ticker scores so downstream paper runner and dashboard can read weights.
-- Scores are the static allocation percentages; the runner will floor shares to capital.
INSERT INTO gold.strategy_ticker_scores
  (strategy_id, ticker, score, signal_action, entry_score, exit_score,
   criteria_met, position_status, deployed_at, updated_at)
SELECT
    'ETF_Covered_Call_Income_Rotation',
    ticker,
    CASE ticker
      WHEN 'JEPI' THEN 50.0
      WHEN 'JEPQ' THEN 50.0
      ELSE 0.0
    END,
    'BUY',
    CASE ticker
      WHEN 'JEPI' THEN 50.0
      WHEN 'JEPQ' THEN 50.0
      ELSE 0.0
    END,
    0.0,
    jsonb_build_object(
      'execution_mode', 'PAPER',
      'weight', CASE ticker
                  WHEN 'JEPI' THEN 0.50
                  WHEN 'JEPQ' THEN 0.50
                  ELSE 0.0
                END,
      'rebalance', 'weekly',
      'max_leverage', 1.0,
      'drawdown_halt', 0.12,
      'risk_review_decision', 'APPROVED'
    ),
    'ACTIVE',
    now(),
    now()
FROM UNNEST(ARRAY['JEPI', 'JEPQ', 'TLTW']) AS ticker
ON CONFLICT (strategy_id, ticker)
DO UPDATE SET
    score = EXCLUDED.score,
    signal_action = EXCLUDED.signal_action,
    entry_score = EXCLUDED.entry_score,
    criteria_met = EXCLUDED.criteria_met,
    position_status = EXCLUDED.position_status,
    updated_at = EXCLUDED.updated_at;

COMMIT;
