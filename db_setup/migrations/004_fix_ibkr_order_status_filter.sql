-- ============================================================
-- Migration 004 — Correct the IBKR order-status filter on
-- consumption.execution_order_queue.
--
-- Migration 003 fixed execution_order_queue to read gold.ibkr_orders, but
-- the status filter it used — ('Submitted','PreSubmitted','PendingSubmit',
-- 'ApiPending') — included a fabricated value: 'ApiPending' is not a real
-- IBKR TWS API OrderStatus. Hermes ran the live distinct-status query and
-- confirmed the real values present are: Cancelled, PendingCancel,
-- PreSubmitted (only PreSubmitted matched the old filter).
--
-- Corrected filter uses IBKR's actual OrderStatus enum:
--   PendingSubmit  — sent to TWS, not yet at the exchange (open)
--   PendingCancel  — cancel requested, not yet confirmed (STILL open —
--                    the order may fill before the cancel takes effect;
--                    excluding it would hide "why hasn't my cancel gone
--                    through" from the operator, the opposite of what an
--                    Order Queue panel is for)
--   PreSubmitted   — held by TWS pending conditions (open)
--   Submitted       — working at the exchange (open)
-- Excluded (terminal states — not "open"):
--   Cancelled, ApiCancelled, Filled (see execution_fills instead), Inactive
--
-- Idempotent: CREATE OR REPLACE VIEW. Safe to re-run.
-- ============================================================

SET search_path = consumption, gold, public;
SET client_min_messages = WARNING;

CREATE OR REPLACE VIEW consumption.execution_order_queue AS
SELECT
    order_id,
    ticker,
    action                  AS side,
    quantity::NUMERIC       AS qty,
    order_type,
    status,
    'IBKR'::VARCHAR          AS venue,
    submit_time              AS ts
FROM gold.ibkr_orders
WHERE status IN ('PendingSubmit','PendingCancel','PreSubmitted','Submitted')
ORDER BY submit_time DESC;

GRANT SELECT ON consumption.execution_order_queue TO openclaw_user;

DO $$
DECLARE
    n_rows INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_rows FROM consumption.execution_order_queue;
    RAISE NOTICE 'Migration 004 complete: execution_order_queue status filter corrected (% open orders)', n_rows;
END $$;
