-- 2026-08-17 — Paper engine fill-price convention (kanban t_3454cc76)
--
-- Problem: rebuild_paper_positions.py priced entries/exits from the latest
-- silver.unified_prices CLOSE with entry_date=today. The cycle runs ~09:16
-- UTC (pre-US-close), so fills were priced at the signal-date close but
-- date-stamped +1 day — violating strategies' declared 'entry at next open'
-- (e.g. ETF_US_Sector_Relative_Momentum XLK 2026-08-13 @ 188.86 = 08-12 close).
--
-- Fix:
--   1. Ledger exposes the fill-price basis:
--      entry_price_source_date / entry_price_basis and
--      exit_price_source_date / exit_price_basis on gold.paper_trades_synthetic.
--   2. New gold.paper_pending_orders table: NEXT_OPEN convention is
--      implemented as deferred fills — an order is booked at signal time and
--      settled at the OPEN of the first bar with date > signal_date.
--   3. consumption.strategy_paper_pending_current: UI surface for pending fills.
--   4. Legacy rows are backfilled best-effort: entry_price_source_date =
--      latest bar date <= entry_date whose close equals entry_price
--      (basis 'SIGNAL_CLOSE'); unmatched rows get basis 'LEGACY'.

-- ── 1. Ledger fill-basis columns ────────────────────────────────────────────
ALTER TABLE gold.paper_trades_synthetic
    ADD COLUMN IF NOT EXISTS entry_price_source_date DATE,
    ADD COLUMN IF NOT EXISTS entry_price_basis TEXT,
    ADD COLUMN IF NOT EXISTS exit_price_source_date DATE,
    ADD COLUMN IF NOT EXISTS exit_price_basis TEXT;

-- ── 2. Pending (deferred) orders ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gold.paper_pending_orders (
    id               BIGSERIAL PRIMARY KEY,
    strategy_id      TEXT NOT NULL,
    ticker           TEXT NOT NULL,
    order_kind       TEXT NOT NULL CHECK (order_kind IN ('OPEN', 'CLOSE')),
    signal_date      DATE NOT NULL,          -- bar date whose close generated the signal
    position_id      INTEGER,                -- CLOSE orders: paper_trades_synthetic.id
    n_shares         NUMERIC,                -- OPEN orders: shares sized at order time
    signal_weight    NUMERIC,
    assigned_capital NUMERIC,
    score            NUMERIC,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'filled', 'cancelled')),
    fill_date        DATE,                   -- bar date of the actual fill
    fill_price       NUMERIC,                -- actual fill price (bar open)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at        TIMESTAMPTZ
);

-- One pending OPEN per (strategy, ticker); one pending CLOSE per position.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_paper_pending_open_strategy_ticker
    ON gold.paper_pending_orders (strategy_id, ticker)
    WHERE status = 'pending' AND order_kind = 'OPEN';

CREATE UNIQUE INDEX IF NOT EXISTS uniq_paper_pending_close_position
    ON gold.paper_pending_orders (position_id)
    WHERE status = 'pending' AND order_kind = 'CLOSE';

CREATE INDEX IF NOT EXISTS idx_paper_pending_orders_status
    ON gold.paper_pending_orders (status, strategy_id);

-- ── 3. UI surface: current pending fills ────────────────────────────────────
CREATE TABLE IF NOT EXISTS consumption.strategy_paper_pending_current (
    strategy_id      TEXT NOT NULL,
    ticker           TEXT NOT NULL,
    order_kind       TEXT NOT NULL,
    signal_date      DATE NOT NULL,
    n_shares         NUMERIC,
    signal_weight    NUMERIC,
    assigned_capital NUMERIC,
    score            NUMERIC,
    expected_fill    TEXT NOT NULL DEFAULT 'next_open',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uniq_strategy_paper_pending_current_sid_ticker_kind
        UNIQUE (strategy_id, ticker, order_kind)
);

-- ── 4. Backfill legacy fill basis (best effort, price-equality match) ───────
UPDATE gold.paper_trades_synthetic p
SET entry_price_source_date = sub.d,
    entry_price_basis       = 'SIGNAL_CLOSE'
FROM (
    SELECT p2.id, MAX(u.date) AS d
    FROM gold.paper_trades_synthetic p2
    JOIN silver.unified_prices u
      ON u.ticker = p2.ticker
     AND u.close  = p2.entry_price
     AND u.date  <= p2.entry_date
    GROUP BY p2.id
) sub
WHERE p.id = sub.id
  AND p.entry_price_source_date IS NULL;

UPDATE gold.paper_trades_synthetic p
SET exit_price_source_date = sub.d,
    exit_price_basis       = 'SIGNAL_CLOSE'
FROM (
    SELECT p2.id, MAX(u.date) AS d
    FROM gold.paper_trades_synthetic p2
    JOIN silver.unified_prices u
      ON u.ticker = p2.ticker
     AND u.close  = p2.exit_price
     AND u.date  <= p2.exit_date
    WHERE p2.exit_price IS NOT NULL
    GROUP BY p2.id
) sub
WHERE p.id = sub.id
  AND p.exit_price IS NOT NULL
  AND p.exit_price_source_date IS NULL;

-- Rows with no price match: label honestly, leave source date NULL.
UPDATE gold.paper_trades_synthetic
SET entry_price_basis = 'LEGACY'
WHERE entry_price_source_date IS NULL
  AND entry_price_basis IS NULL;

UPDATE gold.paper_trades_synthetic
SET exit_price_basis = 'LEGACY'
WHERE exit_price IS NOT NULL
  AND exit_price_source_date IS NULL
  AND exit_price_basis IS NULL;
