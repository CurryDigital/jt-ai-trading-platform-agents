-- 2026-10-07 (kanban t_22ef1dff): gold.regime_gate_decision_log — append-only
-- audit trail for the legacy regime-gate decisions made by
-- agents/signals/strategies/run_signals.py (BaseStrategy.is_active_today ->
-- regime_rules.STRATEGY_MAP, 7 enabled legacy strategies).
--
-- Spec: qr_research deriv_equity_enrichment_v1/REGIME_GATE_SNAPSHOT_SPEC.md.
-- Rationale: gold.regime_label is REWRITTEN nightly (HMM refit + rule override
-- re-labels history), so the label value the gate saw on any past day no longer
-- exists and gate decisions are not reproducible. This table snapshots the
-- label row as read + the STRATEGY_MAP entry used + the decision, one row per
-- strategy per run. BACKFILL: none possible (declared in spec) — historical
-- gate decisions are unrecoverable by construction; the trail starts at the
-- deploy date. Do NOT reconstruct from /tmp/etl_logs (provenance unverifiable).

BEGIN;

CREATE TABLE IF NOT EXISTS gold.regime_gate_decision_log (
    id              bigserial PRIMARY KEY,
    decision_ts     timestamptz NOT NULL DEFAULT now(),   -- when the gate decision was made
    run_id          text NOT NULL,                        -- run_signals.py invocation id: signalrun_YYYYMMDD_HHMMSS_<pid>
    strategy_id     smallint NOT NULL,                    -- numeric signal-agent id (1..20)
    strategy_name   text NOT NULL,
    label_date      date,                                 -- date of the regime_label row READ (NULL if no row)
    regime          text,                                 -- label value the gate saw
    confidence      double precision,
    severity        smallint,
    override_used   boolean,
    map_source      text NOT NULL,                        -- 'registry' | 'legacy_fallback'
    active_ids      jsonb NOT NULL,                       -- STRATEGY_MAP entry used: {regime: [ids]} snapshot
    is_active       boolean NOT NULL,                     -- the decision: strategy_id IN active_ids
    label_row       jsonb,                                -- full regime_label row as read (schema-drift-proof)
    created_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE gold.regime_gate_decision_log IS
    'Append-only audit trail of legacy regime-gate decisions (run_signals.py). One row per strategy per run. No backfill possible — gold.regime_label is rewritten nightly; trail starts 2026-10-07 deploy. Corrections are new rows, never edits.';
COMMENT ON COLUMN gold.regime_gate_decision_log.run_id IS
    'signalrun_YYYYMMDD_HHMMSS_<pid>, printed in the pipeline_b log header — joins DB rows to /tmp/etl_logs/pipeline_b_*.log.';
COMMENT ON COLUMN gold.regime_gate_decision_log.map_source IS
    'registry = STRATEGY_MAP built from strategies/registry.json; legacy_fallback = hardcoded map (registry_loader failed at import).';
COMMENT ON COLUMN gold.regime_gate_decision_log.label_date IS
    'Date of the gold.regime_label row the gate read. label_date older than T-1 on a trading day = stale-label ETL flag (drift check, spec consumer query 3).';

-- One row per strategy per run. Natural dedupe guard for retried runs that
-- reuse a run_id (writer uses ON CONFLICT DO NOTHING; never updates).
CREATE UNIQUE INDEX IF NOT EXISTS regime_gate_decision_log_uq
    ON gold.regime_gate_decision_log (run_id, strategy_id);
CREATE INDEX IF NOT EXISTS regime_gate_decision_log_decision_ts_idx
    ON gold.regime_gate_decision_log (decision_ts);
CREATE INDEX IF NOT EXISTS regime_gate_decision_log_strategy_idx
    ON gold.regime_gate_decision_log (strategy_id, decision_ts);

-- Append-only enforcement.
-- NOTE: the app role (openclaw_user) OWNS this table and Postgres table owners
-- always retain all privileges, so REVOKE UPDATE/DELETE from the app role is a
-- no-op here. Enforcement is therefore trigger-based (blocks UPDATE, DELETE and
-- TRUNCATE for every role, including the owner, short of a deliberate
-- DROP TRIGGER / session_replication_role escape).
CREATE OR REPLACE FUNCTION gold.regime_gate_decision_log_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'gold.regime_gate_decision_log is append-only: % is not allowed; corrections are new rows, never edits', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS regime_gate_decision_log_no_update ON gold.regime_gate_decision_log;
CREATE TRIGGER regime_gate_decision_log_no_update
    BEFORE UPDATE OR DELETE ON gold.regime_gate_decision_log
    FOR EACH ROW EXECUTE FUNCTION gold.regime_gate_decision_log_append_only();

DROP TRIGGER IF EXISTS regime_gate_decision_log_no_truncate ON gold.regime_gate_decision_log;
CREATE TRIGGER regime_gate_decision_log_no_truncate
    BEFORE TRUNCATE ON gold.regime_gate_decision_log
    FOR EACH STATEMENT EXECUTE FUNCTION gold.regime_gate_decision_log_append_only();

COMMIT;

-- Acceptance: table, unique index, and both append-only triggers present.
SELECT t.tgname
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'gold' AND c.relname = 'regime_gate_decision_log'
  AND NOT t.tgisinternal
ORDER BY t.tgname;
