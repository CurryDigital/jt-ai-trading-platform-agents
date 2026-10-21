-- 2026-10-15_price_adjustment_factors.sql
-- Adjustment-factor registry (user directive 2026-10-16, kanban t_8866358c):
-- every price back-adjustment must be recorded here with evidence, and every
-- affected gold/silver row snapshotted (see bak_ref) before any write.
-- boundary_date = first post-split trading day IN OUR DATA (yf action dates
-- can lag the price boundary by 1-9 days; the price series is authoritative).

CREATE TABLE IF NOT EXISTS gold.price_adjustment_factors (
    id bigserial PRIMARY KEY,
    ticker text NOT NULL,
    boundary_date date NOT NULL,
    factor numeric NOT NULL,          -- new shares per 1 old share
    split_type text NOT NULL,         -- split | reverse_split | spinoff | data_error
    source text NOT NULL,             -- e.g. 'yfinance'
    evidence text,
    applied boolean NOT NULL DEFAULT false,
    applied_at timestamptz,
    applied_by text,
    bak_ref text,
    kanban_task text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ticker, boundary_date)
);
