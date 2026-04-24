-- migration_006_v6.1.sql
-- Architecture v6.1: debate agent, macro sentinel, architect, multi-frequency

BEGIN;

-- ─────────────────────────────────────────────────────────────────
-- 1. New columns on strategy_workflow
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE openclaw_researcher.strategy_workflow
  ADD COLUMN IF NOT EXISTS conviction_score REAL,
  ADD COLUMN IF NOT EXISTS debate_summary TEXT,
  ADD COLUMN IF NOT EXISTS frequency TEXT DEFAULT 'daily',
  ADD COLUMN IF NOT EXISTS strategy_description TEXT;

-- ─────────────────────────────────────────────────────────────────
-- 2. New table: macro_events
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS openclaw_researcher.macro_events (
    id              SERIAL PRIMARY KEY,
    event_date      DATE NOT NULL,
    event_type      TEXT NOT NULL,
    description     TEXT NOT NULL,
    affected_assets TEXT[],
    expected_impact TEXT,
    actual_impact   JSONB,
    confidence      REAL,
    source_url      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE openclaw_researcher.macro_events OWNER TO openclaw_user;

-- ─────────────────────────────────────────────────────────────────
-- 3. New routing rules for debate agent
-- ─────────────────────────────────────────────────────────────────

-- Change risk.evaluated target from qr_qa to qr_debate
UPDATE openclaw_researcher.routing_rules
SET target_agent = 'qr_debate', updated_at = NOW()
WHERE event_type = 'risk.evaluated' AND domain = 'quant' AND target_agent = 'qr_qa';

-- Add debate.completed → qr_qa route
INSERT INTO openclaw_researcher.routing_rules
  (event_type, domain, target_agent, enabled)
VALUES ('debate.completed', 'quant', 'qr_qa', true)
ON CONFLICT (event_type, domain, target_agent) DO UPDATE
  SET enabled = true, updated_at = NOW();

-- ─────────────────────────────────────────────────────────────────
-- 4. Frequency-aware risk_config thresholds
-- ─────────────────────────────────────────────────────────────────

INSERT INTO openclaw_researcher.risk_config (name, operator, value, description, enabled)
VALUES
  ('qa_min_trade_count_oos_weekly', 'lt', 10, 'Weekly strategies: min 10 OOS trades', true),
  ('qa_min_trade_count_oos_event', 'lt', 5, 'Event-driven: min 5 OOS events', true),
  ('qa_min_trade_count_oos_monthly', 'lt', 6, 'Monthly rebalance: min 6 months OOS', true),
  ('qa_min_conviction_score', 'lt', 0.3, 'Minimum debate conviction score', true)
ON CONFLICT (name) DO UPDATE
  SET value = EXCLUDED.value, description = EXCLUDED.description, updated_at = NOW();

-- ─────────────────────────────────────────────────────────────────
-- 5. View for debate work queue
-- ─────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW openclaw_researcher.v_debate_work AS
SELECT e.id AS event_id, e.event_type, e.strategy_id, e.domain,
       e.payload_json, e.source_agent, e.created_at,
       EXTRACT(epoch FROM now() - e.created_at) / 60 AS age_minutes
FROM openclaw_researcher.events e
LEFT JOIN openclaw_researcher.event_processing ep
  ON ep.event_id = e.id AND ep.agent_name = 'qr_debate'
WHERE e.event_type = 'risk.evaluated'
  AND e.domain = 'quant'
  AND ep.event_id IS NULL
ORDER BY e.created_at;

COMMIT;
