-- 2026-10-05: silver load ledger for ThetaData incremental loads.
-- load_silver.py processes only ingest runs not yet recorded here
-- (default incremental mode); --full reprocesses everything and rebuilds
-- the ledger. One row per bronze.thetadata_ingest_runs row loaded to silver.
BEGIN;

CREATE TABLE IF NOT EXISTS silver.thetadata_load_ledger (
    ingest_run_id   uuid PRIMARY KEY REFERENCES bronze.thetadata_ingest_runs(ingest_run_id),
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    rows_inserted   integer NOT NULL DEFAULT 0,
    rows_updated    integer NOT NULL DEFAULT 0,   -- latest-revision replacements
    greeks_invalidated integer NOT NULL DEFAULT 0, -- COMPUTED greeks dropped for revised keys
    notes           text
);

COMMIT;
