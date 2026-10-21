-- 2026-08-25: widen gold.manual_orders CHECKs for the paper_uat blotter
-- (kanban t_51368ec4 — UAT async fills never persisted).
--
-- Root cause surfaced while building the UAT fill reconciler: the backend
-- UAT close-position endpoint (ibkr.py) books fills with book='paper_uat'
-- and side='BUY'/'SELL', but the existing CHECKs only allow
-- book IN ('live','paper') and side IN ('LONG','SHORT'). Every paper_uat
-- blotter insert — synchronous OR reconciled — violates a CHECK and is
-- swallowed by the endpoint's except/rollback, so gold.manual_orders
-- book='paper_uat' could NEVER have rows. Widening both CHECKs repairs the
-- backend synchronous path AND unblocks the ETL reconciler
-- (sync_paper_uat_to_gold.py), which books async fills with
-- book='paper_uat', side=BUY/SELL (execution semantics, matching
-- gold.paper_uat_fills.side).
--
-- Existing rows remain valid under the widened definitions (there are
-- currently zero rows in gold.manual_orders).

BEGIN;

ALTER TABLE gold.manual_orders
    DROP CONSTRAINT manual_orders_book_check;

ALTER TABLE gold.manual_orders
    ADD CONSTRAINT manual_orders_book_check
    CHECK (book IN ('live', 'paper', 'paper_uat'));

ALTER TABLE gold.manual_orders
    DROP CONSTRAINT manual_orders_side_check;

ALTER TABLE gold.manual_orders
    ADD CONSTRAINT manual_orders_side_check
    CHECK (side IS NULL OR side IN ('LONG', 'SHORT', 'BUY', 'SELL'));

COMMIT;

-- Acceptance verification
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM   pg_constraint
WHERE  conrelid = 'gold.manual_orders'::regclass
  AND  conname IN ('manual_orders_book_check', 'manual_orders_side_check');
