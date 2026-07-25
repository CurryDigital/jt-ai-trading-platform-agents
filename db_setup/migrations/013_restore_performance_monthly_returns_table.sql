-- ============================================================
-- Migration 013 — Restore consumption.performance_monthly_returns as a TABLE.
--
-- The daily ETL (consumption/performance/performance_strategy_results.py) INSERTs
-- portfolio-level monthly returns (portfolio_type, year, month, return_pct)
-- computed from gold.portfolio_snapshots into consumption.performance_monthly_
-- returns — the shape defined in db_setup/DDL_full_schema.sql.
--
-- A quarantined one-off from the 2026-07-22 drop (workspace/oneoff/tmp-2026-07-22/
-- update_monthly_view.py, see OPERATOR_NOTES flag 6) DROPPED that table and
-- replaced it with a VIEW derived from gold.trade_executions. Two problems:
--   * gold.trade_executions is EMPTY on prod (flag 6), so the view yields nothing.
--   * you cannot INSERT into a grouped view, so the daily pipeline (Pipeline A)
--     exits 1 on that step every run.
-- This reverts the drift: drop the ad-hoc view, restore the canonical table with
-- its sequence, default, PK and the UNIQUE(portfolio_type, year, month) the
-- INSERT ... ON CONFLICT depends on.
--
-- Idempotent. Only drops the object if it is currently a VIEW (leaves a correct
-- existing TABLE untouched).
-- ============================================================

SET search_path = consumption, public;
SET client_min_messages = WARNING;

-- Drop the object ONLY if the drift left it as a view/matview (DROP VIEW IF
-- EXISTS would still ERROR on a real table — IF EXISTS suppresses "missing",
-- not "wrong type" — so gate on relkind).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'consumption' AND c.relname = 'performance_monthly_returns'
          AND c.relkind IN ('v', 'm')   -- view or materialized view
    ) THEN
        EXECUTE 'DROP VIEW IF EXISTS consumption.performance_monthly_returns CASCADE';
        RAISE NOTICE 'Dropped the ad-hoc performance_monthly_returns view (schema drift).';
    END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS consumption.performance_monthly_returns_id_seq AS integer START WITH 1 INCREMENT BY 1;

CREATE TABLE IF NOT EXISTS consumption.performance_monthly_returns (
    id                   integer NOT NULL DEFAULT nextval('consumption.performance_monthly_returns_id_seq'::regclass),
    portfolio_type       character varying(20) NOT NULL,
    year                 integer NOT NULL,
    month                integer NOT NULL,
    return_pct           numeric(10,4),
    benchmark_return_pct numeric(10,4),
    excess_return_pct    numeric(10,4)
);

ALTER SEQUENCE consumption.performance_monthly_returns_id_seq OWNED BY consumption.performance_monthly_returns.id;

-- PK on id + UNIQUE(portfolio_type, year, month) for the ON CONFLICT target.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'performance_monthly_returns_pkey') THEN
        ALTER TABLE consumption.performance_monthly_returns
            ADD CONSTRAINT performance_monthly_returns_pkey PRIMARY KEY (id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'performance_monthly_returns_portfolio_type_year_month_key') THEN
        ALTER TABLE consumption.performance_monthly_returns
            ADD CONSTRAINT performance_monthly_returns_portfolio_type_year_month_key UNIQUE (portfolio_type, year, month);
    END IF;
END $$;

DO $$
DECLARE k char;
BEGIN
    SELECT c.relkind INTO k FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'consumption' AND c.relname = 'performance_monthly_returns';
    RAISE NOTICE 'Migration 013: performance_monthly_returns relkind now = % (expect r = table). '
                 'The daily performance step can INSERT again.', k;
END $$;
