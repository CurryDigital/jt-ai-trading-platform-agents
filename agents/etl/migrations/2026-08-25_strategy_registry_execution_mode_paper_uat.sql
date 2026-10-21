-- 2026-08-25: widen gold.strategy_registry execution_mode CHECK to include 'PAPER_UAT'
-- Part of the 4-book lifecycle (SIM / PAPER / PAPER_UAT / LIVE).
-- PAPER_UAT = broker-rehearsal stage: real IBKR order routing to the UAT
-- session (paper money, account DUP825942, 127.0.0.1:14002 client 2).
-- Replaces strategy_registry_execution_mode_check in place; existing rows
-- (SIMULATION / PAPER) remain valid under the widened definition.

BEGIN;

ALTER TABLE gold.strategy_registry
    DROP CONSTRAINT strategy_registry_execution_mode_check;

ALTER TABLE gold.strategy_registry
    ADD CONSTRAINT strategy_registry_execution_mode_check
    CHECK (execution_mode IN ('SIMULATION', 'PAPER', 'PAPER_UAT', 'LIVE'));

COMMIT;

-- Acceptance verification
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM   pg_constraint
WHERE  conrelid = 'gold.strategy_registry'::regclass
  AND  conname  = 'strategy_registry_execution_mode_check';
