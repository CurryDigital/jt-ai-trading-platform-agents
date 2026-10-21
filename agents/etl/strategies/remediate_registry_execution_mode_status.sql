-- Remediation: align gold.strategy_registry execution_mode/status with actual
-- paper-monitoring state. Only HK_Quality_BlueChips is actively tracked in
-- consumption.portfolio_positions_current, so all other registry rows must be
-- SIMULATION (non-paper). Also backfills signal_logic/exit_logic for the two
-- HK_LowVol strategies so the Strategy Lab UI can render them without backend
-- workarounds.
--
-- Constraints respected:
--   execution_mode check -> {SIMULATION, PAPER, LIVE}
--   status check         -> {paper, live, paused, retired}

BEGIN;

-- 1. Demote every PAPER/paper row except the active paper strategy to SIMULATION/paused.
UPDATE gold.strategy_registry
SET execution_mode = 'SIMULATION',
    status         = 'paused',
    updated_at     = NOW()
WHERE execution_mode = 'PAPER'
  AND status = 'paper'
  AND strategy_id != 'HK_Quality_BlueChips';

-- 2. Ensure the one actively-monitored paper strategy stays PAPER/paper.
UPDATE gold.strategy_registry
SET execution_mode = 'PAPER',
    status         = 'paper',
    updated_at     = NOW()
WHERE strategy_id = 'HK_Quality_BlueChips';

-- 3. Retired rows should not advertise PAPER execution_mode either.
UPDATE gold.strategy_registry
SET execution_mode = 'SIMULATION',
    updated_at     = NOW()
WHERE execution_mode = 'PAPER'
  AND status = 'retired';

-- 4. Backfill missing signal_logic / exit_logic for HK low-volatility strategies.
UPDATE gold.strategy_registry
SET signal_logic = 'entry_basis=next_open;weights_are_target_portfolio=True',
    exit_logic   = 'Weekly rebalance with 5-trading-day signal lag. Selects the 5 HK stocks with the lowest 63-day realized volatility; full rebalance replaces positions at the next signal.',
    updated_at   = NOW()
WHERE strategy_id = 'HK_LowVol_Weekly'
  AND COALESCE(signal_logic, '') = '';

UPDATE gold.strategy_registry
SET signal_logic = 'entry_basis=next_open;weights_are_target_portfolio=True',
    exit_logic   = 'Weekly rebalance with 5-trading-day signal lag. Selects the 5 HK stocks with the lowest 63-day realized volatility; moves to 100% 2800.HK when 2800.HK 126-day total return is negative.',
    updated_at   = NOW()
WHERE strategy_id = 'HK_LowVol_TrendFilter_Weekly'
  AND COALESCE(signal_logic, '') = '';

COMMIT;

-- 5. Acceptance verification.
SELECT execution_mode,
       status,
       COUNT(*) AS n_strategies
FROM   gold.strategy_registry
GROUP BY execution_mode, status
ORDER BY execution_mode, status;
