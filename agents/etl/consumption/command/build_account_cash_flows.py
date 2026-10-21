#!/usr/bin/env python3
"""
Consumption: account cash-flow ledger (command-center Net Cash Flow KPI)

Kanban t_b662b4e9 (2026-08-20): Command 'My Book' KPI grid needs today + MTD
net cash flow. No deposit/withdrawal source exists anywhere in the platform
(probed information_schema: gold/consumption/silver; audit_events is empty;
gold.account_nav_daily.pnl is 0-filled so flows cannot be derived from NAV).

What this build does:
  1. Creates consumption.account_cash_flows ledger table:
       (flow_date, book, amount SIGNED numeric, kind, source, strategy_id)
       amount > 0 = cash in (DEPOSIT), amount < 0 = cash out (WITHDRAWAL).
  2. Seeds the PAPER book from REAL recorded data:
       - DEPOSIT per gold.strategy_registry row (execution_mode='PAPER',
         assigned_capital NOT NULL) at COALESCE(deployed_at, created_at)::date
       - WITHDRAWAL per retired strategy at retired_at::date
       This mirrors consumption.account_summary's canonical paper equity
       (sum of assigned_capital over ACTIVE strategies): ledger net == equity
       base, so the KPI reconciles with the rest of the Command page.
       SIMULATION-mode rows are excluded (not part of the paper book).
  3. Creates consumption.account_cash_flow_summary companion view exposing
       today_net / mtd_net per book (NULL when no flows — frontend renders
       the '—' PENDING state rather than a fake 0).

LIVE book: no cash-flow records exist (IBKR cash-transaction ingest is
scrum_master scope, out of qr_etl boundary). Live rows stay absent and the
view reports NULL for live — no fabricated values.

Idempotent: CREATE IF NOT EXISTS + INSERT ... ON CONFLICT upsert +
CREATE OR REPLACE VIEW. Registered in pipeline_manifest.json (consumption
stage, daily).
"""
import sys
sys.path.insert(0, 'shared/scripts')
from db import get_connection

DDL_TABLE = """
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
"""

SEED_PAPER = """
INSERT INTO consumption.account_cash_flows
    (flow_date, book, amount, kind, source, strategy_id)
SELECT
    COALESCE(r.deployed_at, r.created_at)::date AS flow_date,
    'paper' AS book,
    r.assigned_capital AS amount,
    'DEPOSIT' AS kind,
    'strategy_registry.assigned_capital' AS source,
    r.strategy_id
FROM gold.strategy_registry r
WHERE r.execution_mode = 'PAPER'
  AND r.assigned_capital IS NOT NULL
  AND r.assigned_capital > 0
ON CONFLICT (flow_date, book, kind, source, strategy_id)
DO UPDATE SET amount = EXCLUDED.amount, recorded_at = now();
"""

SEED_PAPER_WITHDRAWALS = """
INSERT INTO consumption.account_cash_flows
    (flow_date, book, amount, kind, source, strategy_id)
SELECT
    r.retired_at::date AS flow_date,
    'paper' AS book,
    -r.assigned_capital AS amount,
    'WITHDRAWAL' AS kind,
    'strategy_registry.retirement' AS source,
    r.strategy_id
FROM gold.strategy_registry r
WHERE r.execution_mode = 'PAPER'
  AND r.assigned_capital IS NOT NULL
  AND r.assigned_capital > 0
  AND r.retired_at IS NOT NULL
ON CONFLICT (flow_date, book, kind, source, strategy_id)
DO UPDATE SET amount = EXCLUDED.amount, recorded_at = now();
"""

DDL_VIEW = """
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
"""


def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(DDL_TABLE)
    cur.execute(SEED_PAPER)
    deposits = cur.rowcount
    cur.execute(SEED_PAPER_WITHDRAWALS)
    withdrawals = cur.rowcount
    cur.execute(DDL_VIEW)
    conn.commit()

    cur.execute("""
        SELECT book, kind, COUNT(*), SUM(amount), MIN(flow_date), MAX(flow_date)
        FROM consumption.account_cash_flows GROUP BY book, kind ORDER BY book, kind
    """)
    print("== consumption.account_cash_flows ==")
    for r in cur.fetchall():
        print(r)
    cur.execute("SELECT * FROM consumption.account_cash_flow_summary ORDER BY book")
    print("== consumption.account_cash_flow_summary ==")
    print([d[0] for d in cur.description])
    for r in cur.fetchall():
        print(r)
    conn.close()
    print(f"OK: seeded/updated {deposits} deposits, {withdrawals} withdrawals; view refreshed")


if __name__ == "__main__":
    run()
