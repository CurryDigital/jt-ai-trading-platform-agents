-- 2026-10-02_deriv_kat_events.sql
-- Scope: deriv schema only. Assignment/exercise event log for KAT runs
-- (EEP-1 early-assignment fix, ENGINE_SPEC section 4, user directive 2026-10-02).
-- The KAT tables carry run_id lineage (no strategy_id/position_group_id exist
-- at KAT phase); strategy-phase stock legs inherit those IDs per SCHEMA §4.
BEGIN;

CREATE TABLE IF NOT EXISTS deriv.kat_events (
    event_id      bigserial    NOT NULL PRIMARY KEY,
    run_id        uuid         NOT NULL REFERENCES deriv.kat_runs(run_id),
    event_date    date         NOT NULL,
    event_type    text         NOT NULL CHECK (event_type IN
                    ('ASSIGN_CALL_EXDIV', 'ASSIGN_PUT_CARRY')),
    contract_id   bigint,
    option_right  text         NOT NULL,
    strike        numeric(12,4) NOT NULL,
    spot          numeric(14,6) NOT NULL,
    intrinsic     numeric(14,6) NOT NULL,
    time_value    numeric(14,6) NOT NULL,
    trigger_value numeric(14,6) NOT NULL,  -- dividend amount (calls) or carry $ (puts)
    detail        jsonb        NOT NULL DEFAULT '{}',
    created_at    timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kat_events_run_idx ON deriv.kat_events (run_id);
COMMENT ON TABLE deriv.kat_events IS
    'Early-assignment events for KAT runs (EEP-1). Calls: assigned at close of the last trading day before ex-date when dividend > call time value and ITM. Puts: assigned when ITM and time value < strike*DTB3*T_remaining (carry rule).';

COMMIT;
