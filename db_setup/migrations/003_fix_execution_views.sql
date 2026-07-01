-- ============================================================
-- Migration 003 — Fix Execution Ops views to match live schema.
--
-- Migration 002's consumption.execution_order_queue and
-- consumption.execution_fills were authored against the API_SPEC_v2.md wire
-- format (order_id, side, venue, submitted_at, execution_id, fill_price,
-- broker_ref, reconciled) without the real DDL for the backing tables —
-- they weren't fully audited in db_setup/DDL_full_schema.sql at the time.
-- Hermes's verification run caught this: both views failed to create
-- because the referenced columns don't exist. Confirmed via live schema
-- query:
--
--   consumption.execution_order_queue was pointed at gold.ib_orders, which
--   has ZERO writers anywhere in agents/etl/ — an orphaned/legacy table.
--   The actively-synced table is gold.ibkr_orders, written by
--   agents/etl/gold/promote_ibkr_orders.py and agents/etl/sync_ibkr_to_gold.py.
--   It already has a real order_id column and a genuine IBKR paper-account
--   default ('DUP825942'), confirming it's the live data path.
--
--   consumption.execution_fills was pointed at the correct table
--   (gold.trade_executions) but with wrong column names: the table has
--   `id`/`price`, not `execution_id`/`fill_price`, and has no
--   broker_ref/reconciled columns at all (broker-statement reconciliation
--   isn't implemented anywhere in this codebase).
--
-- This patch is for environments that already applied 002 and hit the
-- failure — it re-creates just these two views with corrected definitions.
-- 002_frontend_v2_alignment.sql itself has also been corrected in the repo
-- so a fresh clone gets the right definitions from the start; this file is
-- the safe, minimal patch for anyone who already ran the broken version.
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
    'IBKR'::VARCHAR          AS venue,     -- every row in this table is an IBKR order — true, not fabricated
    submit_time              AS ts
FROM gold.ibkr_orders
WHERE status IN ('Submitted','PreSubmitted','PendingSubmit','ApiPending')
ORDER BY submit_time DESC;

CREATE OR REPLACE VIEW consumption.execution_fills AS
SELECT
    id::VARCHAR              AS fill_id,
    ibkr_order_id::VARCHAR    AS order_id,
    ticker,
    quantity::NUMERIC        AS qty,
    price::NUMERIC            AS price,
    NULL::VARCHAR             AS broker_ref,  -- not captured anywhere yet — honest NULL, not fabricated
    NULL::BOOLEAN             AS matched,     -- broker-statement reconciliation not implemented — honest NULL
    executed_at               AS ts
FROM gold.trade_executions
ORDER BY executed_at DESC;

GRANT SELECT ON consumption.execution_order_queue TO openclaw_user;
GRANT SELECT ON consumption.execution_fills       TO openclaw_user;

-- ────────────────────────────────────────────────────────────
-- Not fixed here — flagged for operator review, NOT dropped:
--   gold.ib_orders has zero writers anywhere in agents/etl/. It's either
--   dead schema cruft from an earlier design iteration, or something
--   outside this repo writes to it (a manual process, a different service).
--   Dropping a production table is a one-way, hard-to-reverse action — left
--   for the operator to investigate and decide, not done automatically here.
-- ────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_order_queue_rows INTEGER;
    n_fills_rows        INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_order_queue_rows FROM consumption.execution_order_queue;
    SELECT COUNT(*) INTO n_fills_rows        FROM consumption.execution_fills;
    RAISE NOTICE 'Migration 003 complete:';
    RAISE NOTICE '  execution_order_queue now reads gold.ibkr_orders (% open orders)', n_order_queue_rows;
    RAISE NOTICE '  execution_fills column names corrected (% rows)', n_fills_rows;
    RAISE NOTICE '  gold.ib_orders left in place, unwritten by any script — operator to review, not dropped.';
END $$;
