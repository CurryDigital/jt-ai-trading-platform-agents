-- 2026-08-25 (kanban t_db5ffc20): PAPER_UAT mirror tables — Phase 4 of the
-- PAPER_UAT lifecycle (parent t_b64f7302, decision doc
-- agents/etl/docs/PAPER_UAT_MIRROR_DECISION.md).
--
-- Broker-truth mirror of the dedicated IBKR UAT paper session
-- (account DUP825942, 127.0.0.1:14002 client 2) exposed via the backend at
-- 127.0.0.1:8000 (/api/ib/tws/uat/positions|open-orders|fills).
-- Populated by agents/etl/sync_paper_uat_to_gold.py. These are SEPARATE tables
-- (not a rehearsal flag on gold.paper_trades): broker-truth rows must never
-- live in wholesale-restated sim-ledger tables, and the paper_uat book is an
-- explicit opt-in for Command Center aggregators (UNION with book='paper_uat').
--
-- Attribution: every PAPER_UAT order is fired with orderRef = strat:<strategy_id>
-- (rebuild_paper_positions.py firing contract). strategy_id is derived in the
-- sync as substring(order_ref from '^strat:(.+)$'); unmatched refs stay NULL
-- and are surfaced as unattributed (manual/foreign orders on the UAT account).

BEGIN;

-- One row per UAT execution/fill. Append-only, upserted on (account, exec_id).
CREATE TABLE IF NOT EXISTS gold.paper_uat_fills (
    account         varchar(32)  NOT NULL,
    exec_id         varchar(64)  NOT NULL,
    order_id        bigint,
    perm_id         bigint,
    order_ref       varchar(64),
    strategy_id     varchar(128),
    symbol          varchar(32)  NOT NULL,
    local_symbol    varchar(32),
    side            varchar(8)   NOT NULL CHECK (side IN ('BUY', 'SELL')),
    qty             numeric      NOT NULL,
    price           numeric      NOT NULL,
    currency        varchar(8),
    fill_time       timestamptz,
    as_of           timestamptz  NOT NULL,
    synced_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (account, exec_id)
);
COMMENT ON TABLE gold.paper_uat_fills IS
    'PAPER_UAT broker-truth fills from the IBKR UAT paper session (backend /api/ib/tws/uat/fills). strategy_id derived from order_ref strat:<sid>; NULL = unattributed.';
COMMENT ON COLUMN gold.paper_uat_fills.strategy_id IS
    'substring(order_ref from ''^strat:(.+)$''); NULL for manual/foreign orders on the UAT account — surface as unattributed.';
-- Btree on (strategy_id, fill_time) serves per-(strategy_id, month) PnL scans;
-- date_trunc() on timestamptz is not immutable and cannot be indexed directly.
CREATE INDEX IF NOT EXISTS paper_uat_fills_strategy_time_idx
    ON gold.paper_uat_fills (strategy_id, fill_time);
CREATE INDEX IF NOT EXISTS paper_uat_fills_fill_time_idx
    ON gold.paper_uat_fills (fill_time);

-- Point-in-time UAT position snapshot. Refreshed (truncate+reload) each sync;
-- never written when the UAT session is disconnected.
CREATE TABLE IF NOT EXISTS gold.paper_uat_positions (
    account         varchar(32)  NOT NULL,
    ticker          varchar(32)  NOT NULL,
    symbol          varchar(32),
    sec_type        varchar(16),
    exchange        varchar(32),
    currency        varchar(8),
    qty             numeric      NOT NULL,
    avg_cost        numeric,
    market_price    numeric,
    market_value    numeric,
    unrealized_pnl  numeric,
    realized_pnl    numeric,
    as_of           timestamptz  NOT NULL,
    synced_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (account, ticker)
);
COMMENT ON TABLE gold.paper_uat_positions IS
    'PAPER_UAT point-in-time position snapshot from the IBKR UAT paper session (backend /api/ib/tws/uat/positions). Refreshed whole each sync; rows are as of as_of.';

-- Point-in-time working-order snapshot. Refreshed (truncate+reload) each sync.
CREATE TABLE IF NOT EXISTS gold.paper_uat_open_orders (
    account         varchar(32)  NOT NULL,
    order_id        bigint       NOT NULL,
    perm_id         bigint,
    symbol          varchar(32)  NOT NULL,
    local_symbol    varchar(32),
    action          varchar(8)   NOT NULL,
    qty             numeric      NOT NULL,
    order_type      varchar(16),
    status          varchar(32),
    filled          numeric,
    remaining       numeric,
    as_of           timestamptz  NOT NULL,
    synced_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (account, order_id)
);
COMMENT ON TABLE gold.paper_uat_open_orders IS
    'PAPER_UAT point-in-time working-order snapshot from the IBKR UAT paper session (backend /api/ib/tws/uat/open-orders). Refreshed whole each sync.';

COMMIT;

-- Acceptance verification
SELECT table_name FROM information_schema.tables
WHERE  table_schema = 'gold'
  AND  table_name IN ('paper_uat_fills', 'paper_uat_positions', 'paper_uat_open_orders')
ORDER  BY table_name;
