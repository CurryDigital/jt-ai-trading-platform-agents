-- ============================================================================
-- 2026-10-07_thetadata_completeness_status.sql
-- Per-date completeness status for ThetaData option endpoints.
-- User directive 2026-10-07: keep the 0.95 completeness-gate threshold, add an
-- acceptance path — a SHORT date whose row_count AND distinct_contracts are
-- identical across two pulls >=4h apart is accepted as VERIFIED_THIN instead
-- of being retried/alerted nightly forever. Only unstable counts stay SHORT.
-- Engine + audit read this table to distinguish genuinely thin days
-- (VERIFIED_THIN) from unverified shortfalls (SHORT) and clean days (VERIFIED).
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS silver.thetadata_date_completeness (
    symbol                text        NOT NULL,
    endpoint              text        NOT NULL DEFAULT 'eod',
    trade_date            date        NOT NULL,
    status                text        NOT NULL
        CHECK (status IN ('VERIFIED', 'VERIFIED_THIN', 'SHORT')),
    -- latest observed counts (post client-side DTE filter)
    row_count             integer,
    distinct_contracts    integer,
    -- gate baseline snapshot at last decision
    baseline_med_rows     numeric,
    baseline_med_contracts numeric,
    baseline_n            integer,
    -- stability tracking: first SHORT observation (pull 1 of the >=4h pair)
    first_short_at        timestamptz,
    first_short_rows      integer,
    first_short_contracts integer,
    last_checked_at       timestamptz NOT NULL DEFAULT now(),
    decided_by            text,        -- ingest_run_id or script/audit label
    note                  text,
    PRIMARY KEY (symbol, endpoint, trade_date)
);

COMMENT ON TABLE silver.thetadata_date_completeness IS
    'Completeness-gate verdict per symbol/endpoint/trade_date. '
    'VERIFIED = passed >=0.95 trailing-20-median gate at pull time; '
    'VERIFIED_THIN = below gate but stable (identical row_count and '
    'distinct_contracts across two pulls >=4h apart) — legitimate thin chain; '
    'SHORT = below gate and not yet proven stable — retried, alerts.';

COMMIT;
