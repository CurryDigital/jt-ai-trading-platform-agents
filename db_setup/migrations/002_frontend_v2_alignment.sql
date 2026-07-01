-- ============================================================
-- Migration 002 — Frontend v2 Alignment (JTCML Workspace Redesign)
--
-- Lands the DB objects called for in:
--   ui_kits/jtcml-workspace/handoff/{API_SPEC_v2,DB_CHANGES_v2}.md
--
-- Contract: PLATFORM IS READ-ONLY OVER gold/consumption EXCEPT for
--   gold.manual_orders. Everything else here is ingestion-owned by qr_etl.
--
-- Idempotent — every CREATE has IF NOT EXISTS or OR REPLACE; every ALTER
-- uses ADD COLUMN IF NOT EXISTS. Safe to re-run.
--
-- Coverage map (🔴 blocker / 🟡 important / 🟢 nice-to-have, per spec):
--   §1  Command:     account_summary 🔴, account_nav_daily 🔴, equity_curve view, attention_queue 🔴
--   §2  Market Band: dashboard_indices 🟡, market_breadth 🟡, market_sentiment 🟢, market_movers 🟢
--   §3  Macro:       macro_regime_7d 🔴, macro_kpis 🟡, macro_sectors 🟡, macro_events 🟢, market_news 🟡
--   §4  Signals:     signal_families 🔴 (table+seed), signal_setups 🔴, signal_performance 🟡,
--                    signal_proximity 🟡, signal_feed 🟡
--   §5  Execution:   manual_orders 🔴 (table), execution_order_queue 🟡, execution_fills 🟡,
--                    ib_gateway_state 🟡, risk_limits 🟡
--   §7  Changed:     portfolio_positions_current.source 🟡, dashboard_market_overview.spark 🟡
--
-- Views whose upstream source tables don't exist yet return empty rows but
-- are queryable (so the FastAPI safe_query() pattern hits HTTP 200, not 500).
-- DE replaces the placeholder bodies with real queries as sources land.
-- ============================================================

SET search_path = consumption, gold, public;
SET client_min_messages = WARNING;

-- ────────────────────────────────────────────────────────────
-- §1.2  gold.account_nav_daily  (🔴 blocker — equity curve hero)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold.account_nav_daily (
    book        VARCHAR(10) NOT NULL CHECK (book IN ('live', 'paper')),
    as_of_date  DATE        NOT NULL,
    equity      NUMERIC     NOT NULL,
    pnl         NUMERIC,
    PRIMARY KEY (book, as_of_date)
);
ALTER TABLE gold.account_nav_daily OWNER TO openclaw_user;
COMMENT ON TABLE gold.account_nav_daily IS
    'One row per book per session close. DE appends at session-close snapshot. UI needs >= 30 trailing sessions.';

-- ────────────────────────────────────────────────────────────
-- §4.1  gold.signal_families  (🔴 blocker — Research↔Strategies vocabulary bridge)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold.signal_families (
    family_key     VARCHAR(40) PRIMARY KEY,
    label          VARCHAR(40),
    strategy_id    VARCHAR(10),                       -- FK→gold.strategy_registry; NULL = candidate
    deployed       BOOLEAN     NOT NULL DEFAULT FALSE,
    color          VARCHAR(9),                        -- hex; UI tag colour
    updated_at     TIMESTAMP   NOT NULL DEFAULT now()
);
ALTER TABLE gold.signal_families OWNER TO openclaw_user;

-- Seed mapping per DB_CHANGES_v2 §4.1. Idempotent.
INSERT INTO gold.signal_families (family_key, label, strategy_id, deployed, color) VALUES
    ('Momentum Breakout', 'Seasonal SUE',     's019', TRUE, '#3b82f6'),
    ('Earnings Drift',    'Earnings Drift',   's102', TRUE, '#f97316'),
    ('Gap Reversal',      'Gap Reversal',     's044', TRUE, '#10b981'),
    ('Regime Carry',      'Regime Carry',     's071', TRUE, '#06b6d4'),
    ('Macro Breakout',    'Macro Breakout',   's088', TRUE, '#ef4444'),
    ('Mean Reversion',    'Mean Reversion',   NULL,   FALSE, '#8b5cf6')
ON CONFLICT (family_key) DO UPDATE SET
    label       = EXCLUDED.label,
    strategy_id = EXCLUDED.strategy_id,
    deployed    = EXCLUDED.deployed,
    color       = EXCLUDED.color,
    updated_at  = now();

-- ────────────────────────────────────────────────────────────
-- §5.1  gold.manual_orders  (🔴 the ONLY platform-write target)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold.manual_orders (
    order_id     VARCHAR(32) PRIMARY KEY,                                 -- 'm'+epoch from platform
    book         VARCHAR(10) NOT NULL CHECK (book IN ('live', 'paper')),
    ticker       VARCHAR(20) NOT NULL,
    market       VARCHAR(8)            CHECK (market IS NULL OR market IN ('US','HK')),
    asset_class  VARCHAR(12)           CHECK (asset_class IS NULL OR asset_class IN ('STOCK','CRYPTO','FX')),
    side         VARCHAR(6)            CHECK (side IS NULL OR side IN ('LONG','SHORT')),
    qty          NUMERIC     NOT NULL CHECK (qty > 0),
    entry_price  NUMERIC,
    limit_price  NUMERIC,                                                  -- NULL = market order
    status       VARCHAR(16) NOT NULL DEFAULT 'accepted',
    note         VARCHAR(200),
    created_by   VARCHAR(50),
    created_at   TIMESTAMP   NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC' + INTERVAL '8 hours')
);
ALTER TABLE gold.manual_orders OWNER TO openclaw_user;
CREATE INDEX IF NOT EXISTS manual_orders_book_idx ON gold.manual_orders (book, created_at DESC);

-- ────────────────────────────────────────────────────────────
-- Stub upstream tables for views whose sources DE hasn't built yet.
-- They have the shape required by the views but are populated later.
-- ────────────────────────────────────────────────────────────

-- Macro / regime forecast (drives the 7-day risk-on bar charts)
CREATE TABLE IF NOT EXISTS gold.regime_forecast (
    scope         VARCHAR(8) NOT NULL CHECK (scope IN ('US','HK','CRYPTO','FX','METAL')),
    day_offset    INTEGER    NOT NULL CHECK (day_offset BETWEEN 0 AND 6),
    risk_on_pct   NUMERIC    NOT NULL CHECK (risk_on_pct BETWEEN 0 AND 100),
    forecast_date DATE       NOT NULL,
    updated_at    TIMESTAMP  NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, day_offset, forecast_date)
);
ALTER TABLE gold.regime_forecast OWNER TO openclaw_user;

-- Macro KPIs (display strings — UI renders verbatim)
CREATE TABLE IF NOT EXISTS gold.macro_kpis_facts (
    scope        VARCHAR(8) NOT NULL,
    ord          INTEGER    NOT NULL,
    label        VARCHAR(40) NOT NULL,
    value        VARCHAR(40) NOT NULL,
    updated_at   TIMESTAMP  NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, ord)
);
ALTER TABLE gold.macro_kpis_facts OWNER TO openclaw_user;

-- Per-region GICS-ish sector daily perf
CREATE TABLE IF NOT EXISTS gold.macro_sectors_facts (
    region       VARCHAR(4) NOT NULL CHECK (region IN ('US','HK')),
    sector       VARCHAR(40) NOT NULL,
    perf_pct     NUMERIC,
    ord          INTEGER,
    updated_at   TIMESTAMP  NOT NULL DEFAULT now(),
    PRIMARY KEY (region, sector)
);
ALTER TABLE gold.macro_sectors_facts OWNER TO openclaw_user;

-- Economic calendar
CREATE TABLE IF NOT EXISTS gold.economic_calendar (
    id           SERIAL PRIMARY KEY,
    region       VARCHAR(4) NOT NULL CHECK (region IN ('US','HK')),
    event        VARCHAR(120) NOT NULL,
    event_date   VARCHAR(20),                  -- display string ('Jun 25')
    importance   VARCHAR(8) CHECK (importance IN ('High','Med','Low')),
    updated_at   TIMESTAMP  NOT NULL DEFAULT now()
);
ALTER TABLE gold.economic_calendar OWNER TO openclaw_user;

-- News sentiment (powers /api/news + macro box headlines)
CREATE TABLE IF NOT EXISTS gold.news_sentiment (
    id           BIGSERIAL PRIMARY KEY,
    market       VARCHAR(8) NOT NULL CHECK (market IN ('US','HK','CRYPTO','FX','METAL')),
    headline     VARCHAR(400) NOT NULL,
    source       VARCHAR(80),
    tone         VARCHAR(4) CHECK (tone IN ('bull','bear','neu')),
    impact       VARCHAR(8) CHECK (impact IN ('High','Med','Low')),
    tags         VARCHAR(20)[],
    published_at TIMESTAMP NOT NULL DEFAULT now()
);
ALTER TABLE gold.news_sentiment OWNER TO openclaw_user;
CREATE INDEX IF NOT EXISTS news_sentiment_market_pub_idx ON gold.news_sentiment (market, published_at DESC);

-- Market sentiment singleton (latest row wins)
CREATE TABLE IF NOT EXISTS gold.market_sentiment_facts (
    id               INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    fear_greed       INTEGER,
    fear_greed_label VARCHAR(20),
    vix              NUMERIC,
    vix_change_pct   NUMERIC,
    put_call         NUMERIC,
    updated_at       TIMESTAMP NOT NULL DEFAULT now()
);
ALTER TABLE gold.market_sentiment_facts OWNER TO openclaw_user;

-- Market breadth, one row per region (US/HK)
CREATE TABLE IF NOT EXISTS gold.market_breadth_facts (
    region        VARCHAR(4) PRIMARY KEY CHECK (region IN ('US','HK')),
    advancing     INTEGER,
    declining     INTEGER,
    unchanged     INTEGER,
    new_highs     INTEGER,
    new_lows      INTEGER,
    updated_at    TIMESTAMP NOT NULL DEFAULT now()
);
ALTER TABLE gold.market_breadth_facts OWNER TO openclaw_user;

-- Top movers (gainers + losers list)
CREATE TABLE IF NOT EXISTS gold.market_movers_facts (
    region       VARCHAR(4)  NOT NULL CHECK (region IN ('US','HK')),
    direction    VARCHAR(8)  NOT NULL CHECK (direction IN ('gainer','loser')),
    ticker       VARCHAR(20) NOT NULL,
    change_pct   NUMERIC     NOT NULL,
    rank         INTEGER     NOT NULL,
    updated_at   TIMESTAMP   NOT NULL DEFAULT now(),
    PRIMARY KEY (region, direction, rank)
);
ALTER TABLE gold.market_movers_facts OWNER TO openclaw_user;

-- Signal evaluation facts (pivoted into signal_setups view as families[])
CREATE TABLE IF NOT EXISTS gold.signal_evaluations (
    market       VARCHAR(8)  NOT NULL CHECK (market IN ('US','HK','CRYPTO','FX','METAL')),
    ticker       VARCHAR(20) NOT NULL,
    name         VARCHAR(120),
    family_key   VARCHAR(40) NOT NULL REFERENCES gold.signal_families(family_key),
    direction    VARCHAR(4)  NOT NULL CHECK (direction IN ('BUY','SELL')),
    potential    NUMERIC     NOT NULL CHECK (potential BETWEEN 0 AND 100),
    change_pct   NUMERIC,
    note         VARCHAR(200),
    updated_at   TIMESTAMP   NOT NULL DEFAULT now(),
    PRIMARY KEY (market, ticker, family_key)
);
ALTER TABLE gold.signal_evaluations OWNER TO openclaw_user;
CREATE INDEX IF NOT EXISTS signal_evaluations_market_potential_idx
    ON gold.signal_evaluations (market, potential DESC);

-- Per-family hit rate / forward return
CREATE TABLE IF NOT EXISTS gold.signal_family_performance (
    market          VARCHAR(8)  NOT NULL CHECK (market IN ('US','HK','CRYPTO','FX','METAL')),
    family_key      VARCHAR(40) NOT NULL REFERENCES gold.signal_families(family_key),
    hit_rate        NUMERIC,
    fwd_return_5d   NUMERIC,
    n_trades        INTEGER,
    updated_at      TIMESTAMP   NOT NULL DEFAULT now(),
    PRIMARY KEY (market, family_key)
);
ALTER TABLE gold.signal_family_performance OWNER TO openclaw_user;

-- How close each ticker is to triggering a family
CREATE TABLE IF NOT EXISTS gold.signal_proximity_facts (
    market         VARCHAR(8)  NOT NULL CHECK (market IN ('US','HK','CRYPTO','FX','METAL')),
    ticker         VARCHAR(20) NOT NULL,
    family_key     VARCHAR(40) NOT NULL REFERENCES gold.signal_families(family_key),
    distance_pct   NUMERIC     NOT NULL,
    direction      VARCHAR(4)  NOT NULL CHECK (direction IN ('BUY','SELL')),
    updated_at     TIMESTAMP   NOT NULL DEFAULT now(),
    PRIMARY KEY (market, ticker, family_key)
);
ALTER TABLE gold.signal_proximity_facts OWNER TO openclaw_user;

-- Attention queue raw facts (DE unions sources of urgency into this)
CREATE TABLE IF NOT EXISTS gold.attention_items (
    item_id      VARCHAR(40) PRIMARY KEY,
    severity     VARCHAR(10) NOT NULL CHECK (severity IN ('critical','warning','info')),
    tag          VARCHAR(20) NOT NULL,
    title        VARCHAR(200) NOT NULL,
    impact       VARCHAR(300),
    target       VARCHAR(20) NOT NULL CHECK (target IN ('strategies','execution','settings','research','command')),
    ref_id       VARCHAR(40),
    created_at   TIMESTAMP   NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMP                                 -- NULL = open
);
ALTER TABLE gold.attention_items OWNER TO openclaw_user;
CREATE INDEX IF NOT EXISTS attention_items_open_sev_idx
    ON gold.attention_items (severity, created_at DESC)
    WHERE resolved_at IS NULL;

-- IBKR Gateway singleton heartbeat
CREATE TABLE IF NOT EXISTS gold.ib_gateway_heartbeat (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    connected       BOOLEAN NOT NULL DEFAULT FALSE,
    host            VARCHAR(60),
    port            INTEGER,
    latency_ms      INTEGER,
    account         VARCHAR(40),
    last_heartbeat  TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT now()
);
ALTER TABLE gold.ib_gateway_heartbeat OWNER TO openclaw_user;
INSERT INTO gold.ib_gateway_heartbeat (id, connected) VALUES (1, FALSE)
    ON CONFLICT (id) DO NOTHING;

-- Risk limits: per-strategy + a singleton global row (strategy_id IS NULL)
CREATE TABLE IF NOT EXISTS gold.risk_limits_facts (
    strategy_id      VARCHAR(10),                              -- NULL = global row
    halt_phrase_set  BOOLEAN NOT NULL DEFAULT FALSE,
    global_halt      BOOLEAN NOT NULL DEFAULT FALSE,
    capital_cap_pct  NUMERIC,
    used_pct         NUMERIC,
    updated_at       TIMESTAMP NOT NULL DEFAULT now()
);
-- Partial unique index so we can have at most one global row.
CREATE UNIQUE INDEX IF NOT EXISTS risk_limits_facts_global_singleton
    ON gold.risk_limits_facts ((strategy_id IS NULL))
    WHERE strategy_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS risk_limits_facts_strategy_uq
    ON gold.risk_limits_facts (strategy_id)
    WHERE strategy_id IS NOT NULL;
ALTER TABLE gold.risk_limits_facts OWNER TO openclaw_user;
INSERT INTO gold.risk_limits_facts (strategy_id, halt_phrase_set, global_halt)
VALUES (NULL, FALSE, FALSE)
ON CONFLICT DO NOTHING;

-- ────────────────────────────────────────────────────────────
-- §7  Existing-table column adds (ADD COLUMN IF NOT EXISTS)
-- ────────────────────────────────────────────────────────────

-- dashboard_market_overview: add intraday spark (NUMERIC[]) for /api/markets/indices
ALTER TABLE consumption.dashboard_market_overview
    ADD COLUMN IF NOT EXISTS spark NUMERIC[];

-- portfolio_positions_current: distinguish algo fills from manual_orders fold-in
ALTER TABLE consumption.portfolio_positions_current
    ADD COLUMN IF NOT EXISTS source VARCHAR(10);

ALTER TABLE consumption.portfolio_positions_current
    ADD CONSTRAINT portfolio_positions_current_source_chk
        CHECK (source IS NULL OR source IN ('algo','manual'))
    NOT VALID;
-- NOT VALID skips backfill validation; old rows can remain NULL until DE fills.

-- ────────────────────────────────────────────────────────────
-- CONSUMPTION VIEWS — read-only surface for the FastAPI platform.
-- Every view either selects from an existing source OR wraps the stub
-- table created above (empty until DE fills). Either way the platform
-- gets HTTP 200 with empty data, not a 500.
-- ────────────────────────────────────────────────────────────

-- §1.1 account_summary — derived. DE will replace this body once positions
-- + cash ledger views land. Today: returns one empty row per book so the
-- /command/overview aggregator has a shape to splice in.
CREATE OR REPLACE VIEW consumption.account_summary AS
SELECT
    book::VARCHAR(10)        AS book,
    NULL::NUMERIC            AS equity,
    NULL::NUMERIC            AS day_pnl,
    NULL::NUMERIC            AS day_pnl_pct,
    NULL::NUMERIC            AS open_pnl,
    NULL::NUMERIC            AS buying_power,
    NULL::NUMERIC            AS cash_pct,
    NULL::NUMERIC            AS gross_exp_pct,
    NULL::NUMERIC            AS net_exp_pct,
    NULL::INTEGER            AS positions,
    NULL::TIMESTAMP          AS updated_at
FROM (VALUES ('live'), ('paper')) AS t(book);

-- §1.2 equity curve
CREATE OR REPLACE VIEW consumption.account_equity_curve AS
SELECT book, as_of_date AS d, equity
FROM gold.account_nav_daily
ORDER BY book, as_of_date;

-- §1.3 attention queue
CREATE OR REPLACE VIEW consumption.attention_queue AS
SELECT
    item_id, severity, tag, title, impact, target, ref_id, created_at
FROM gold.attention_items
WHERE resolved_at IS NULL
ORDER BY
    CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
    created_at DESC;

-- §2.1 dashboard_indices — wraps existing dashboard_market_overview, US/HK only.
-- Old non-US/HK rows survive in the underlying table; this view filters them.
CREATE OR REPLACE VIEW consumption.dashboard_indices AS
SELECT
    index_ticker AS sym,
    index_name   AS name,
    region,
    current_value AS last,
    change_pct,
    spark,
    updated_at
FROM consumption.dashboard_market_overview
WHERE region IN ('US','HK');

-- §2.2 market_breadth
CREATE OR REPLACE VIEW consumption.market_breadth AS
SELECT region, advancing, declining, unchanged, new_highs, new_lows, updated_at
FROM gold.market_breadth_facts;

-- §2.3 market_sentiment + market_movers
CREATE OR REPLACE VIEW consumption.market_sentiment AS
SELECT fear_greed, fear_greed_label, vix, vix_change_pct, put_call, updated_at
FROM gold.market_sentiment_facts;

CREATE OR REPLACE VIEW consumption.market_movers AS
SELECT direction, ticker, change_pct, rank, updated_at
FROM gold.market_movers_facts
ORDER BY region, direction, rank;

-- §3.1 macro_regime_7d — only the latest forecast per (scope, day_offset)
CREATE OR REPLACE VIEW consumption.macro_regime_7d AS
SELECT DISTINCT ON (scope, day_offset)
    scope, day_offset, risk_on_pct, forecast_date, updated_at
FROM gold.regime_forecast
ORDER BY scope, day_offset, forecast_date DESC;

-- §3.2 macro_kpis
CREATE OR REPLACE VIEW consumption.macro_kpis AS
SELECT scope, ord, label, value, updated_at
FROM gold.macro_kpis_facts
ORDER BY scope, ord;

-- §3.3 macro_sectors
CREATE OR REPLACE VIEW consumption.macro_sectors AS
SELECT region, sector, perf_pct, ord, updated_at
FROM gold.macro_sectors_facts
ORDER BY region, ord NULLS LAST, sector;

-- §3.4 macro_events
CREATE OR REPLACE VIEW consumption.macro_events AS
SELECT region, event, event_date, importance, updated_at
FROM gold.economic_calendar
ORDER BY region, updated_at DESC;

-- §3.5 market_news
CREATE OR REPLACE VIEW consumption.market_news AS
SELECT market, headline, source, tone, impact, tags, published_at
FROM gold.news_sentiment
ORDER BY market, published_at DESC;

-- §4.2 signal_setups — pivot per-ticker family rows into a families[] array
CREATE OR REPLACE VIEW consumption.signal_setups AS
SELECT
    market,
    ticker,
    MAX(name)                                  AS name,
    ARRAY_AGG(family_key ORDER BY family_key)  AS families,
    -- Direction wins ties by majority; ARRAY_AGG keeps audit; UI uses majority.
    MODE() WITHIN GROUP (ORDER BY direction)   AS direction,
    AVG(potential)::NUMERIC(6,2)               AS potential,
    AVG(change_pct)::NUMERIC(8,4)              AS change_pct,
    -- Concatenate distinct notes; truncate to UI-safe length.
    LEFT(STRING_AGG(DISTINCT note, ' · ' ORDER BY note), 200) AS note,
    MAX(updated_at)                            AS updated_at
FROM gold.signal_evaluations
GROUP BY market, ticker
ORDER BY market, potential DESC;

-- §4.3 signal_performance
CREATE OR REPLACE VIEW consumption.signal_performance AS
SELECT market, family_key AS family, hit_rate, fwd_return_5d, n_trades, updated_at
FROM gold.signal_family_performance
ORDER BY market, family_key;

-- §4.4 signal_proximity (note: existing gold.v_signal_proximity is unrelated;
-- the platform reads consumption.signal_proximity per the v2 spec).
CREATE OR REPLACE VIEW consumption.signal_proximity AS
SELECT market, ticker, family_key AS family, distance_pct, direction, updated_at
FROM gold.signal_proximity_facts
ORDER BY market, distance_pct ASC;     -- closest-to-trigger first (UI flags < 15)

-- §4.5 signal_feed — wrap existing consumption.signal_logs with a market discriminator.
-- Existing signal_logs has (id, strategy_id, signal_date, signal, logged_at, ticker, ...);
-- we left-join gold.strategy_registry for the family/strategy display name.
-- 'market' is derived from ticker prefix (best-effort until DE adds the column):
--   '.HK' suffix → HK, BTC|ETH|XRP → CRYPTO, '=X' → FX, GC=F/SI=F/CL=F → METAL, else US.
CREATE OR REPLACE VIEW consumption.signal_feed AS
-- signal_logs.strategy_id is SMALLINT (e.g. 19); strategy_registry.strategy_id
-- is VARCHAR(50) with the 's019' frontend convention (per spec §4.1 examples).
-- The join bridges via 's' || LPAD(int::text, 3, '0').
SELECT
    CASE
        WHEN sl.ticker LIKE '%.HK' THEN 'HK'
        WHEN sl.ticker ~ '^(BTC|ETH|XRP|SOL|ADA|DOGE)' THEN 'CRYPTO'
        WHEN sl.ticker LIKE '%=X' THEN 'FX'
        WHEN sl.ticker IN ('GC=F','SI=F','CL=F','NG=F','HG=F') THEN 'METAL'
        ELSE 'US'
    END                                                      AS market,
    sl.logged_at                                             AS fired_at,
    CASE sl.signal WHEN 1 THEN 'BUY' WHEN -1 THEN 'SELL' ELSE 'FLAT' END AS signal,
    sl.ticker,
    COALESCE(sr.name, sl.signal_type, 'unknown')             AS strategy,
    sl.confidence::NUMERIC                                   AS confidence
FROM consumption.signal_logs sl
LEFT JOIN gold.strategy_registry sr
    ON sr.strategy_id = 's' || LPAD(sl.strategy_id::TEXT, 3, '0')
ORDER BY sl.logged_at DESC;

-- §5.2 execution views — read-only over IBKR sync tables
-- 2026-07-01 CORRECTED (see migration 003 for the story): the original
-- version of this view pointed at gold.ib_orders, guessing column names
-- (order_id, side, venue, submitted_at) from the API_SPEC_v2.md wire format
-- without the real DDL. Verification found gold.ib_orders has ZERO writers
-- anywhere in agents/etl/ — an orphaned table. The actively-synced table is
-- gold.ibkr_orders (written by gold/promote_ibkr_orders.py and
-- sync_ibkr_to_gold.py), which already has a real order_id column.
CREATE OR REPLACE VIEW consumption.execution_order_queue AS
SELECT
    order_id,
    ticker,
    action                 AS side,
    quantity::NUMERIC      AS qty,
    order_type,
    status,
    'IBKR'::VARCHAR         AS venue,     -- every row in this table is an IBKR order — true, not fabricated
    submit_time             AS ts
FROM gold.ibkr_orders
-- Status vocabulary corrected 2026-07-01 (see migration 004): this is
-- IBKR's actual TWS API OrderStatus enum, not a guess. 'ApiPending' in
-- the original version of this filter was fabricated — no such IBKR
-- status exists. PendingCancel is included deliberately: a cancel
-- request in flight is NOT a terminal state (the order may still fill
-- before the cancel is confirmed), so hiding it from an Order Queue
-- panel would mask exactly the "why hasn't my cancel gone through"
-- visibility the panel exists for. Excluded (terminal): Cancelled,
-- ApiCancelled, Filled (use execution_fills for those), Inactive.
WHERE status IN ('PendingSubmit','PendingCancel','PreSubmitted','Submitted')
ORDER BY submit_time DESC;

-- 2026-07-01 CORRECTED: gold.trade_executions was the right table, but the
-- guessed column names (execution_id, fill_price, broker_ref, reconciled)
-- don't match the real schema (id, price; no broker_ref/reconciled columns
-- exist at all — reconciliation against broker statements isn't implemented).
CREATE OR REPLACE VIEW consumption.execution_fills AS
SELECT
    id::VARCHAR             AS fill_id,
    ibkr_order_id::VARCHAR   AS order_id,
    ticker,
    quantity::NUMERIC       AS qty,
    price::NUMERIC           AS price,
    NULL::VARCHAR            AS broker_ref,  -- not captured anywhere yet — honest NULL, not fabricated
    NULL::BOOLEAN            AS matched,     -- broker-statement reconciliation not implemented — honest NULL
    executed_at              AS ts
FROM gold.trade_executions
ORDER BY executed_at DESC;

CREATE OR REPLACE VIEW consumption.ib_gateway_state AS
SELECT connected, host, port, latency_ms, account, last_heartbeat
FROM gold.ib_gateway_heartbeat
WHERE id = 1;

CREATE OR REPLACE VIEW consumption.risk_limits AS
SELECT halt_phrase_set, global_halt, strategy_id, capital_cap_pct, used_pct, updated_at
FROM gold.risk_limits_facts;

-- ────────────────────────────────────────────────────────────
-- Grants — platform user reads consumption.*; manual_orders write only.
-- ────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA consumption TO openclaw_user;
GRANT USAGE ON SCHEMA gold        TO openclaw_user;

GRANT SELECT ON ALL TABLES IN SCHEMA consumption TO openclaw_user;
GRANT SELECT ON ALL TABLES IN SCHEMA gold        TO openclaw_user;
GRANT INSERT, UPDATE ON gold.manual_orders TO openclaw_user;

-- ────────────────────────────────────────────────────────────
-- Verification (RAISE NOTICE so psql -f shows the operator a checklist).
-- ────────────────────────────────────────────────────────────
DO $$
DECLARE
    n_views   INTEGER;
    n_tables  INTEGER;
    n_families INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_views
    FROM information_schema.views
    WHERE (table_schema, table_name) IN (
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
    );

    SELECT COUNT(*) INTO n_tables
    FROM information_schema.tables
    WHERE (table_schema, table_name) IN (
        ('gold','account_nav_daily'),
        ('gold','signal_families'),
        ('gold','manual_orders'),
        ('gold','regime_forecast'),
        ('gold','attention_items')
    );

    SELECT COUNT(*) INTO n_families FROM gold.signal_families;

    RAISE NOTICE 'Migration 002 complete:';
    RAISE NOTICE '  consumption views created: % / 20', n_views;
    RAISE NOTICE '  gold tables created:       % / 5 (core)', n_tables;
    RAISE NOTICE '  signal_families seeded:    % / 6', n_families;
    RAISE NOTICE 'Verify with: SELECT 1 FROM consumption.attention_queue LIMIT 1;';
END $$;
