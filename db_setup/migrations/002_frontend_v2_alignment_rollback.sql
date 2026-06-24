-- ============================================================
-- Rollback for Migration 002 — JTCML Workspace Redesign alignment.
--
-- ⚠️  DROPS objects created by 002. Run only if you need to revert.
-- Empties seeded data — there is no DATA-preservation step here because
-- the v2 migration only added empty/seed structures.
--
-- DOES NOT drop existing-table columns (spark, source) — those are
-- additive and harmless; the rollback leaves them so old non-v2
-- frontends still work.
-- ============================================================

SET search_path = consumption, gold, public;
SET client_min_messages = WARNING;

-- Views (CONSUMPTION)
DROP VIEW IF EXISTS consumption.account_summary        CASCADE;
DROP VIEW IF EXISTS consumption.account_equity_curve   CASCADE;
DROP VIEW IF EXISTS consumption.attention_queue        CASCADE;
DROP VIEW IF EXISTS consumption.dashboard_indices      CASCADE;
DROP VIEW IF EXISTS consumption.market_breadth         CASCADE;
DROP VIEW IF EXISTS consumption.market_sentiment       CASCADE;
DROP VIEW IF EXISTS consumption.market_movers          CASCADE;
DROP VIEW IF EXISTS consumption.macro_regime_7d        CASCADE;
DROP VIEW IF EXISTS consumption.macro_kpis             CASCADE;
DROP VIEW IF EXISTS consumption.macro_sectors          CASCADE;
DROP VIEW IF EXISTS consumption.macro_events           CASCADE;
DROP VIEW IF EXISTS consumption.market_news            CASCADE;
DROP VIEW IF EXISTS consumption.signal_setups          CASCADE;
DROP VIEW IF EXISTS consumption.signal_performance     CASCADE;
DROP VIEW IF EXISTS consumption.signal_proximity       CASCADE;
DROP VIEW IF EXISTS consumption.signal_feed            CASCADE;
DROP VIEW IF EXISTS consumption.execution_order_queue  CASCADE;
DROP VIEW IF EXISTS consumption.execution_fills        CASCADE;
DROP VIEW IF EXISTS consumption.ib_gateway_state       CASCADE;
DROP VIEW IF EXISTS consumption.risk_limits            CASCADE;

-- Gold tables (data and structure)
DROP TABLE IF EXISTS gold.signal_proximity_facts       CASCADE;
DROP TABLE IF EXISTS gold.signal_family_performance    CASCADE;
DROP TABLE IF EXISTS gold.signal_evaluations           CASCADE;
DROP TABLE IF EXISTS gold.signal_families              CASCADE;
DROP TABLE IF EXISTS gold.market_movers_facts          CASCADE;
DROP TABLE IF EXISTS gold.market_breadth_facts         CASCADE;
DROP TABLE IF EXISTS gold.market_sentiment_facts       CASCADE;
DROP TABLE IF EXISTS gold.news_sentiment               CASCADE;
DROP TABLE IF EXISTS gold.economic_calendar            CASCADE;
DROP TABLE IF EXISTS gold.macro_sectors_facts          CASCADE;
DROP TABLE IF EXISTS gold.macro_kpis_facts             CASCADE;
DROP TABLE IF EXISTS gold.regime_forecast              CASCADE;
DROP TABLE IF EXISTS gold.attention_items              CASCADE;
DROP TABLE IF EXISTS gold.ib_gateway_heartbeat         CASCADE;
DROP TABLE IF EXISTS gold.risk_limits_facts            CASCADE;
DROP TABLE IF EXISTS gold.manual_orders                CASCADE;
DROP TABLE IF EXISTS gold.account_nav_daily            CASCADE;

-- Constraints added to existing tables (additive columns left in place).
ALTER TABLE consumption.portfolio_positions_current
    DROP CONSTRAINT IF EXISTS portfolio_positions_current_source_chk;

DO $$
BEGIN
    RAISE NOTICE 'Migration 002 rolled back. spark / source columns retained as harmless additions.';
END $$;
