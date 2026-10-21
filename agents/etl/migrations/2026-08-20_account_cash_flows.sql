-- 2026-08-20: account cash-flow ledger for Command 'My Book' Net Cash Flow KPI
-- Kanban t_b662b4e9. Applied via consumption/command/build_account_cash_flows.py
-- (idempotent; registered in pipeline_manifest.json, consumption stage, daily).

CREATE TABLE IF NOT EXISTS consumption.account_cash_flows (
    id           BIGSERIAL PRIMARY KEY,
    flow_date    DATE        NOT NULL,
    book         VARCHAR(10) NOT NULL,
    amount       NUMERIC     NOT NULL,   -- signed: + inflow, - outflow
    kind         VARCHAR(20) NOT NULL CHECK (kind IN ('DEPOSIT','WITHDRAWAL','TRANSFER')),
    source       TEXT        NOT NULL,
    strategy_id  VARCHAR(64),
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT account_cash_flows_natural_key
        UNIQUE NULLS NOT DISTINCT (flow_date, book, kind, source, strategy_id)
);

CREATE OR REPLACE VIEW consumption.account_cash_flow_summary AS
WITH books AS (
    SELECT 'live'::character varying(10) AS book
    UNION ALL
    SELECT 'paper'::character varying(10)
),
agg AS (
    SELECT
        book,
        SUM(amount) FILTER (WHERE flow_date = CURRENT_DATE) AS today_net,
        SUM(amount) FILTER (
            WHERE flow_date >= date_trunc('month', CURRENT_DATE)::date
        ) AS mtd_net,
        COUNT(*) FILTER (WHERE flow_date = CURRENT_DATE)::integer AS flows_today_count,
        COUNT(*) FILTER (
            WHERE flow_date >= date_trunc('month', CURRENT_DATE)::date
        )::integer AS flows_mtd_count,
        MAX(flow_date) AS last_flow_date,
        SUM(amount) AS net_all_time
    FROM consumption.account_cash_flows
    GROUP BY book
)
SELECT
    b.book,
    a.today_net,
    a.mtd_net,
    COALESCE(a.flows_today_count, 0) AS flows_today_count,
    COALESCE(a.flows_mtd_count, 0)   AS flows_mtd_count,
    a.last_flow_date,
    a.net_all_time,
    NOW()::timestamp without time zone AS updated_at
FROM books b
LEFT JOIN agg a ON a.book = b.book;
