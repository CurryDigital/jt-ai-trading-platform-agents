-- ============================================================
-- 003_paper_uat_execution.sql
-- Execution tab: 4th mode PAPER_UAT (IBKR paper-account session:
-- real gateway connection, real order firing, paper money).
--
--   §1  gold.ib_gateway_heartbeat becomes per-session (id=1 primary,
--       id=2 uat) with a session label column.
--   §2  consumption.ib_gateway_state unchanged (primary, id=1).
--   §3  NEW consumption.ib_gateway_state_sessions — one row per session
--       so /api/execution/gateway can surface per-session truth.
-- ============================================================

SET search_path = consumption, gold, public;
SET client_min_messages = WARNING;

-- ────────────────────────────────────────────────────────────
-- §1  Per-session heartbeat rows
-- ────────────────────────────────────────────────────────────
ALTER TABLE gold.ib_gateway_heartbeat
    DROP CONSTRAINT IF EXISTS ib_gateway_heartbeat_id_check;

ALTER TABLE gold.ib_gateway_heartbeat
    ADD COLUMN IF NOT EXISTS session VARCHAR(16) NOT NULL DEFAULT 'primary';

INSERT INTO gold.ib_gateway_heartbeat (id, session, connected)
VALUES (2, 'uat', FALSE)
ON CONFLICT (id) DO NOTHING;

-- ────────────────────────────────────────────────────────────
-- §2  consumption.ib_gateway_state — unchanged (primary session only)
-- ────────────────────────────────────────────────────────────
-- (no change: view filters WHERE id = 1)

-- ────────────────────────────────────────────────────────────
-- §3  Per-session view for the Execution Gateway panel
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW consumption.ib_gateway_state_sessions AS
SELECT session, connected, host, port, latency_ms, account, last_heartbeat
FROM gold.ib_gateway_heartbeat;

GRANT SELECT ON consumption.ib_gateway_state_sessions TO openclaw_user;

-- ────────────────────────────────────────────────────────────
-- Verification
-- ────────────────────────────────────────────────────────────
DO $$
DECLARE
    n_sessions INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_sessions FROM gold.ib_gateway_heartbeat;
    RAISE NOTICE 'gold.ib_gateway_heartbeat rows: % (expect 2: primary + uat)', n_sessions;
END $$;
