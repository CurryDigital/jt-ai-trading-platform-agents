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
-- t_82a67ac5: potential = continuous 12w-momentum percentile strength (same
-- computation as the ticker_scores write below), not the raw static weight.
WITH px AS (
  SELECT DISTINCT ON (ticker, date)
         ticker, date, close
  FROM silver.unified_prices
  WHERE ticker IN ('JEPI','JEPQ','QYLD','XYLD','PBP','TLTW')
    AND close IS NOT NULL
  ORDER BY ticker, date, CASE market WHEN 'GLOBAL' THEN 0 ELSE 1 END
),
ranked_px AS (
  SELECT ticker, close,
         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
  FROM px
),
mom AS (
  SELECT ticker,
         MAX(CASE WHEN rn = 1 THEN close END)
           / NULLIF(MAX(CASE WHEN rn = 63 THEN close END), 0) - 1 AS r12w
  FROM ranked_px
  WHERE rn <= 63
  GROUP BY ticker
),
strength AS (
  SELECT ticker,
         ROUND((100.0 * (COUNT(*) OVER () - RANK() OVER (ORDER BY r12w DESC) + 0.5)
                / COUNT(*) OVER ())::numeric, 2) AS signal_strength
  FROM mom
)
INSERT INTO gold.signal_evaluations (
    market, ticker, name, family_key, direction, potential, change_pct, note, updated_at
)
SELECT
    'US',
    u.ticker,
    u.ticker,
    'tactical',
    'BUY',
    s.signal_strength,
    0,
    'Covered-Call Income ETF Rotation: static allocation; weekly rebalance; max single-asset 50%; 1.0 max leverage; halt on drawdown > 12%',
    now()
FROM UNNEST(ARRAY['JEPI', 'JEPQ', 'TLTW']) AS u(ticker)
JOIN strength s ON s.ticker = u.ticker
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
--
-- t_82a67ac5: also publish `signal_strength`, a continuous 0-100 cross-sectional
-- strength = midpoint percentile of 12w (63 trading day) momentum across the
-- covered-call income universe. The static allocation has no entry signal, so
-- momentum percentile is the honest continuous strength proxy; the previous
-- hardcoded 50.0/0.0 put raw weights into the UI's `potential` field.
WITH px AS (
  SELECT DISTINCT ON (ticker, date)
         ticker, date, close
  FROM silver.unified_prices
  WHERE ticker IN ('JEPI','JEPQ','QYLD','XYLD','PBP','TLTW')
    AND close IS NOT NULL
  ORDER BY ticker, date, CASE market WHEN 'GLOBAL' THEN 0 ELSE 1 END
),
ranked_px AS (
  SELECT ticker, close,
         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
  FROM px
),
mom AS (
  SELECT ticker,
         MAX(CASE WHEN rn = 1 THEN close END)
           / NULLIF(MAX(CASE WHEN rn = 63 THEN close END), 0) - 1 AS r12w
  FROM ranked_px
  WHERE rn <= 63
  GROUP BY ticker
),
strength AS (
  SELECT ticker,
         ROUND((100.0 * (COUNT(*) OVER () - RANK() OVER (ORDER BY r12w DESC) + 0.5)
                / COUNT(*) OVER ())::numeric, 2) AS signal_strength
  FROM mom
)
INSERT INTO gold.strategy_ticker_scores
  (strategy_id, ticker, score, signal_action, entry_score, exit_score,
   criteria_met, position_status, deployed_at, updated_at, signal_strength)
SELECT
    'ETF_Covered_Call_Income_Rotation',
    u.ticker,
    CASE u.ticker
      WHEN 'JEPI' THEN 50.0
      WHEN 'JEPQ' THEN 50.0
      ELSE 0.0
    END,
    'BUY',
    CASE u.ticker
      WHEN 'JEPI' THEN 50.0
      WHEN 'JEPQ' THEN 50.0
      ELSE 0.0
    END,
    0.0,
    jsonb_build_object(
      'execution_mode', 'PAPER',
      'weight', CASE u.ticker
                  WHEN 'JEPI' THEN 0.50
                  WHEN 'JEPQ' THEN 0.50
                  ELSE 0.0
                END,
      'rebalance', 'weekly',
      'max_leverage', 1.0,
      'drawdown_halt', 0.12,
      'risk_review_decision', 'APPROVED',
      'strength_method', 'midpoint_percentile_momentum_12w'
    ),
    'ACTIVE',
    now(),
    now(),
    s.signal_strength
FROM UNNEST(ARRAY['JEPI', 'JEPQ', 'TLTW']) AS u(ticker)
LEFT JOIN strength s ON s.ticker = u.ticker
ON CONFLICT (strategy_id, ticker)
DO UPDATE SET
    score = EXCLUDED.score,
    signal_action = EXCLUDED.signal_action,
    entry_score = EXCLUDED.entry_score,
    criteria_met = EXCLUDED.criteria_met,
    position_status = EXCLUDED.position_status,
    signal_strength = EXCLUDED.signal_strength,
    updated_at = EXCLUDED.updated_at;

COMMIT;
