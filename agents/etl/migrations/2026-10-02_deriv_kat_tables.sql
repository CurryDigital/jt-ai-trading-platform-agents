-- 2026-10-02_deriv_kat_tables.sql
-- Scope: deriv schema only. Engine KAT artifacts (runs, daily series, trades).
BEGIN;

CREATE TABLE IF NOT EXISTS deriv.kat_runs (
    run_id       uuid        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    index_name   text        NOT NULL,           -- BXM / PUT
    params       jsonb       NOT NULL,           -- fill_frac, mark_mode, window, tolerances
    status       text        NOT NULL DEFAULT 'RUNNING',
    metrics      jsonb,                          -- computed at completion
    verdict      text,                           -- PASS / FAIL per pre-declared tolerances
    created_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

CREATE TABLE IF NOT EXISTS deriv.kat_daily (
    run_id       uuid        NOT NULL REFERENCES deriv.kat_runs(run_id),
    trade_date   date        NOT NULL,
    nav          numeric(20,6) NOT NULL,
    engine_level numeric(20,6) NOT NULL,
    ref_level    numeric(20,6),
    ret_engine   numeric(14,8),
    ret_ref      numeric(14,8),
    note         text,                            -- e.g. INTRINSIC_MARK days
    PRIMARY KEY (run_id, trade_date)
);

CREATE TABLE IF NOT EXISTS deriv.kat_trades (
    run_id       uuid        NOT NULL REFERENCES deriv.kat_runs(run_id),
    roll_date    date        NOT NULL,
    expiry       date        NOT NULL,
    strike       numeric(12,4) NOT NULL,
    option_right text        NOT NULL,
    contract_id  bigint,
    fill_price   numeric(14,6) NOT NULL,
    settle_value numeric(14,6),                   -- intrinsic at expiry close
    commission   numeric(10,4) NOT NULL,
    note         text,
    PRIMARY KEY (run_id, roll_date)
);

COMMIT;
