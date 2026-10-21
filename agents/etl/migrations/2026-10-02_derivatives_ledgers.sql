-- 2026-10-02 (kanban t_15d7e66a): Derivatives data namespace — gold.derivatives_*
-- ledgers for the Derivatives tab (plan:
-- .hermes/plans/2026-10-01_060404-derivatives-tab.md, Phase 3).
--
-- CONTAINMENT CONTRACT: these are NEW, dedicated tables. Nothing here writes to
-- gold.paper_trades*, gold.paper_uat_fills, gold.trade_executions, or
-- gold.manual_* — existing books and the /api/command/pnl-by-mode +
-- /api/execution/book-overview aggregates are untouched by construction (this
-- migration is CREATE-only, additive).
--
-- Books: deriv_sim (simulated/backtest-derived execution ledger) and
-- deriv_paper (dedicated derivatives paper session, when one exists). The book
-- CHECK constraint keeps derivatives rows inside this namespace; adding a future
-- book is an explicit ALTER, not a silent leak.
--
-- Registry coupling: qr_research t_736850c6 is still deciding whether derivative
-- strategies live in gold.strategy_registry (asset_class=OPTION/FUTURE) or a
-- separate gold.derivatives_strategies table. strategy_id is therefore a plain
-- varchar with NO foreign key; once t_736850c6 lands, an FK can be added by a
-- follow-up migration without rewriting these tables.

BEGIN;

-- ============================================================================
-- 1) gold.derivatives_backtest_runs — one row per derivatives strategy backtest
--    run. Mirrors gold.strategy_backtest_runs conventions (uuid PK, IS/OOS
--    windows, gate metrics) plus instrument/venue tagging. No book column:
--    backtests are pre-execution.
-- ============================================================================
CREATE TABLE IF NOT EXISTS gold.derivatives_backtest_runs (
    run_id                uuid         NOT NULL DEFAULT gen_random_uuid(),
    strategy_id           varchar(128) NOT NULL,
    run_number            integer      NOT NULL,
    instrument_type       varchar(8)   NOT NULL CHECK (instrument_type IN ('OPTION', 'FUTURE')),
    underlying            varchar(32)  NOT NULL,
    venue                 varchar(8)   NOT NULL CHECK (venue IN ('US', 'HK')),
    run_by                varchar(64)  DEFAULT 'research-agent',
    is_start              date         NOT NULL,
    is_end                date         NOT NULL,
    oos_start             date         NOT NULL,
    oos_end               date         NOT NULL,
    sharpe_is             numeric,
    returns_is            numeric,
    max_drawdown_is       numeric,
    trade_count_is        integer,
    win_rate_is           numeric,
    turnover_is           numeric,
    sharpe_oos            numeric,
    returns_oos           numeric,
    max_drawdown_oos      numeric,
    trade_count_oos       integer,
    win_rate_oos          numeric,
    turnover_oos          numeric,
    cvar_95_oos           numeric,
    profit_factor_oos     numeric,
    all_risk_gates_passed boolean,
    parameters_used       jsonb        DEFAULT '{}'::jsonb,
    notes                 text,
    created_at            timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id),
    UNIQUE (strategy_id, run_number)
);
COMMENT ON TABLE gold.derivatives_backtest_runs IS
    'Derivatives-tab backtest runs (options/futures). Dedicated namespace per derivatives-tab containment contract; strategy_id has no FK until qr_research t_736850c6 decides registry placement.';
COMMENT ON COLUMN gold.derivatives_backtest_runs.strategy_id IS
    'Derivative strategy key. FK deferred pending t_736850c6 (gold.strategy_registry asset_class=OPTION/FUTURE vs separate gold.derivatives_strategies).';
CREATE INDEX IF NOT EXISTS derivatives_backtest_runs_strategy_idx
    ON gold.derivatives_backtest_runs (strategy_id, created_at DESC);

-- ============================================================================
-- 2) gold.derivatives_backtest_trades — per-run simulated derivative trades.
--    Append-only child of derivatives_backtest_runs (CASCADE on run delete).
--    Contract identified by `contract` (OCC symbology for options, e.g.
--    'AAPL  260116C00200000'; root+month for futures, e.g. 'GCZ26').
-- ============================================================================
CREATE TABLE IF NOT EXISTS gold.derivatives_backtest_trades (
    id                bigserial    NOT NULL,
    run_id            uuid         NOT NULL REFERENCES gold.derivatives_backtest_runs(run_id) ON DELETE CASCADE,
    strategy_id       varchar(128) NOT NULL,
    instrument_type   varchar(8)   NOT NULL CHECK (instrument_type IN ('OPTION', 'FUTURE')),
    underlying        varchar(32)  NOT NULL,
    contract          varchar(64)  NOT NULL,
    option_right      varchar(4)   CHECK (option_right IN ('CALL', 'PUT')),
    strike            numeric,
    expiry            date,
    side              varchar(8)   NOT NULL CHECK (side IN ('BUY', 'SELL')),
    qty               numeric      NOT NULL,
    multiplier        numeric      NOT NULL DEFAULT 1,
    entry_date        date         NOT NULL,
    entry_price       numeric      NOT NULL,
    exit_date         date,
    exit_price        numeric,
    fees              numeric      NOT NULL DEFAULT 0,
    pnl               numeric,
    pnl_pct           numeric,
    status            varchar(16)  NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'EXPIRED', 'ASSIGNED', 'CANCELLED')),
    created_at        timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
COMMENT ON TABLE gold.derivatives_backtest_trades IS
    'Per-run simulated derivative trades for the Derivatives tab Backtest subtab. Append-only child of gold.derivatives_backtest_runs.';
CREATE INDEX IF NOT EXISTS derivatives_backtest_trades_run_idx
    ON gold.derivatives_backtest_trades (run_id);
CREATE INDEX IF NOT EXISTS derivatives_backtest_trades_strategy_idx
    ON gold.derivatives_backtest_trades (strategy_id, entry_date);

-- ============================================================================
-- 3) gold.derivatives_positions — point-in-time position snapshot PER BOOK
--    (deriv_sim / deriv_paper). Refreshed whole per book by the owning sync
--    job; rows are as of as_of. strategy_id NULL = unattributed (manual or
--    foreign contract on the book).
-- ============================================================================
CREATE TABLE IF NOT EXISTS gold.derivatives_positions (
    id                bigserial    NOT NULL,
    book              varchar(16)  NOT NULL CHECK (book IN ('deriv_sim', 'deriv_paper')),
    strategy_id       varchar(128),
    instrument_type   varchar(8)   NOT NULL CHECK (instrument_type IN ('OPTION', 'FUTURE')),
    underlying        varchar(32)  NOT NULL,
    contract          varchar(64)  NOT NULL,
    option_right      varchar(4)   CHECK (option_right IN ('CALL', 'PUT')),
    strike            numeric,
    expiry            date,
    exchange          varchar(32),
    currency          varchar(8),
    qty               numeric      NOT NULL,
    avg_cost          numeric,
    market_price      numeric,
    market_value      numeric,
    unrealized_pnl    numeric,
    realized_pnl      numeric,
    as_of             timestamptz  NOT NULL,
    synced_at         timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
COMMENT ON TABLE gold.derivatives_positions IS
    'Derivatives-tab point-in-time position snapshot per book (deriv_sim, deriv_paper). Refreshed whole per book by the owning sync; strategy_id NULL = unattributed.';
COMMENT ON COLUMN gold.derivatives_positions.book IS
    'Derivatives execution book: deriv_sim (simulated) or deriv_paper (dedicated derivatives paper session). Never an existing book name.';
-- One row per (book, strategy, contract); NULLS NOT DISTINCT so unattributed
-- (NULL strategy_id) rows still dedupe per contract.
CREATE UNIQUE INDEX IF NOT EXISTS derivatives_positions_book_strat_contract_uidx
    ON gold.derivatives_positions (book, strategy_id, contract) NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS derivatives_positions_book_idx
    ON gold.derivatives_positions (book, as_of DESC);

-- ============================================================================
-- 4) gold.derivatives_fills — append-only execution ledger PER BOOK. Mirrors
--    gold.paper_uat_fills attribution contract: order_ref carries
--    'strat:<strategy_id>' for strategy-attributed fills; unmatched refs keep
--    strategy_id NULL and surface as unattributed.
-- ============================================================================
CREATE TABLE IF NOT EXISTS gold.derivatives_fills (
    id                bigserial    NOT NULL,
    book              varchar(16)  NOT NULL CHECK (book IN ('deriv_sim', 'deriv_paper')),
    exec_id           varchar(64)  NOT NULL,
    order_id          bigint,
    perm_id           bigint,
    order_ref         varchar(64),
    strategy_id       varchar(128),
    instrument_type   varchar(8)   NOT NULL CHECK (instrument_type IN ('OPTION', 'FUTURE')),
    underlying        varchar(32)  NOT NULL,
    contract          varchar(64)  NOT NULL,
    option_right      varchar(4)   CHECK (option_right IN ('CALL', 'PUT')),
    strike            numeric,
    expiry            date,
    side              varchar(8)   NOT NULL CHECK (side IN ('BUY', 'SELL')),
    qty               numeric      NOT NULL,
    price             numeric      NOT NULL,
    multiplier        numeric      NOT NULL DEFAULT 1,
    currency          varchar(8),
    fill_time         timestamptz,
    as_of             timestamptz  NOT NULL,
    synced_at         timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
COMMENT ON TABLE gold.derivatives_fills IS
    'Derivatives-tab append-only fill ledger per book (deriv_sim, deriv_paper). strategy_id derived from order_ref strat:<sid>; NULL = unattributed.';
COMMENT ON COLUMN gold.derivatives_fills.strategy_id IS
    'substring(order_ref from ''^strat:(.+)$''); NULL for manual/foreign fills on the book — surface as unattributed.';
-- Idempotent upsert target per book, mirroring paper_uat_fills (account, exec_id).
CREATE UNIQUE INDEX IF NOT EXISTS derivatives_fills_book_exec_uidx
    ON gold.derivatives_fills (book, exec_id);
-- Btree on (strategy_id, fill_time) serves per-(strategy, month) PnL scans;
-- date_trunc() on timestamptz is not immutable and cannot be indexed directly.
CREATE INDEX IF NOT EXISTS derivatives_fills_strategy_time_idx
    ON gold.derivatives_fills (strategy_id, fill_time);
CREATE INDEX IF NOT EXISTS derivatives_fills_fill_time_idx
    ON gold.derivatives_fills (fill_time);

COMMIT;

-- Acceptance verification
SELECT table_name FROM information_schema.tables
WHERE  table_schema = 'gold'
  AND  table_name IN ('derivatives_backtest_runs', 'derivatives_backtest_trades',
                      'derivatives_positions', 'derivatives_fills')
ORDER  BY table_name;
