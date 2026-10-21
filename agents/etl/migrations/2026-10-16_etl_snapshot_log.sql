-- 2026-10-16_etl_snapshot_log.sql
-- Snapshot/run-id log for full-history restates (user directive 2026-10-16).
-- clean_unified_prices.py refuses to run without a snapshot id and logs
-- pre/post row counts here. Scheduled pipeline runs get an ETL_RUN_SNAPSHOT_ID
-- from run_stage.py or the wrapper; out-of-band restates must create their
-- backups first and pass that snapshot id explicitly.

CREATE TABLE IF NOT EXISTS gold.etl_snapshot_log (
    snapshot_id text PRIMARY KEY,
    scope text NOT NULL,
    script text NOT NULL,
    pre_rows bigint,
    pre_max_date date,
    post_rows bigint,
    post_max_date date,
    note text,
    created_at timestamptz NOT NULL DEFAULT now()
);
