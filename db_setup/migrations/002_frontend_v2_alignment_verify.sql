-- ============================================================
-- Verify Migration 002 — JTCML Workspace Redesign alignment.
-- Read-only. Run AFTER 002_frontend_v2_alignment.sql.
--
-- Usage:
--   psql "$DB_URL" -f db_setup/migrations/002_frontend_v2_alignment_verify.sql
-- ============================================================

\echo === Verifying Migration 002 ===

-- §1 Required objects present (matches §8 of DB_CHANGES_v2.md)
\echo
\echo --- New consumption views ---
SELECT table_schema, table_name
FROM   information_schema.views
WHERE  (table_schema, table_name) IN (
    ('consumption','account_summary'),
    ('consumption','account_equity_curve'),
    ('consumption','attention_queue'),
    ('consumption','dashboard_indices'),
    ('consumption','market_breadth'),
    ('consumption','market_sentiment'),
    ('consumption','market_movers'),
    ('consumption','macro_regime_7d'),
    ('consumption','macro_kpis'),
    ('consumption','macro_sectors'),
    ('consumption','macro_events'),
    ('consumption','market_news'),
    ('consumption','signal_setups'),
    ('consumption','signal_performance'),
    ('consumption','signal_proximity'),
    ('consumption','signal_feed'),
    ('consumption','execution_order_queue'),
    ('consumption','execution_fills'),
    ('consumption','ib_gateway_state'),
    ('consumption','risk_limits')
)
ORDER BY 1, 2;

\echo
\echo --- New gold tables ---
SELECT table_schema, table_name
FROM   information_schema.tables
WHERE  (table_schema, table_name) IN (
    ('gold','account_nav_daily'),
    ('gold','signal_families'),
    ('gold','manual_orders'),
    ('gold','regime_forecast'),
    ('gold','macro_kpis_facts'),
    ('gold','macro_sectors_facts'),
    ('gold','economic_calendar'),
    ('gold','news_sentiment'),
    ('gold','market_sentiment_facts'),
    ('gold','market_breadth_facts'),
    ('gold','market_movers_facts'),
    ('gold','signal_evaluations'),
    ('gold','signal_family_performance'),
    ('gold','signal_proximity_facts'),
    ('gold','attention_items'),
    ('gold','ib_gateway_heartbeat'),
    ('gold','risk_limits_facts')
)
ORDER BY 1, 2;

\echo
\echo --- Altered columns: dashboard_market_overview.spark, portfolio_positions_current.source ---
SELECT table_schema, table_name, column_name, data_type
FROM   information_schema.columns
WHERE  (table_schema, table_name, column_name) IN (
    ('consumption','dashboard_market_overview','spark'),
    ('consumption','portfolio_positions_current','source')
);

\echo
\echo --- signal_families seed (must be 6 rows: 5 deployed + 1 candidate) ---
SELECT family_key, label, strategy_id, deployed, color FROM gold.signal_families ORDER BY family_key;

\echo
\echo --- Smoke test: every consumption view returns HTTP 200 shape ---
-- The platform's safe_query() pattern expects these to either return rows or
-- the empty set without erroring. We just count.
SELECT 'attention_queue'    AS view, COUNT(*) AS n FROM consumption.attention_queue
UNION ALL SELECT 'dashboard_indices',     COUNT(*) FROM consumption.dashboard_indices
UNION ALL SELECT 'market_breadth',        COUNT(*) FROM consumption.market_breadth
UNION ALL SELECT 'market_sentiment',      COUNT(*) FROM consumption.market_sentiment
UNION ALL SELECT 'market_movers',         COUNT(*) FROM consumption.market_movers
UNION ALL SELECT 'macro_regime_7d',       COUNT(*) FROM consumption.macro_regime_7d
UNION ALL SELECT 'macro_kpis',            COUNT(*) FROM consumption.macro_kpis
UNION ALL SELECT 'macro_sectors',         COUNT(*) FROM consumption.macro_sectors
UNION ALL SELECT 'macro_events',          COUNT(*) FROM consumption.macro_events
UNION ALL SELECT 'market_news',           COUNT(*) FROM consumption.market_news
UNION ALL SELECT 'signal_setups',         COUNT(*) FROM consumption.signal_setups
UNION ALL SELECT 'signal_performance',    COUNT(*) FROM consumption.signal_performance
UNION ALL SELECT 'signal_proximity',      COUNT(*) FROM consumption.signal_proximity
UNION ALL SELECT 'signal_feed',           COUNT(*) FROM consumption.signal_feed
UNION ALL SELECT 'execution_order_queue', COUNT(*) FROM consumption.execution_order_queue
UNION ALL SELECT 'execution_fills',       COUNT(*) FROM consumption.execution_fills
UNION ALL SELECT 'ib_gateway_state',      COUNT(*) FROM consumption.ib_gateway_state
UNION ALL SELECT 'risk_limits',           COUNT(*) FROM consumption.risk_limits
UNION ALL SELECT 'account_summary',       COUNT(*) FROM consumption.account_summary
UNION ALL SELECT 'account_equity_curve',  COUNT(*) FROM consumption.account_equity_curve;

\echo
\echo --- Manual-order write contract: required CHECK constraints exist ---
SELECT conname, pg_get_constraintdef(oid)
FROM   pg_constraint
WHERE  conrelid = 'gold.manual_orders'::regclass
  AND  contype = 'c'
ORDER  BY conname;

\echo === DONE ===
