-- 2026-11-10_live_position_attribution.sql
-- kanban t_2d56f780
--
-- Per-position open-lot ledger + attribution for the LIVE book served by
-- /api/positions/live (gold.ibkr_positions_live, account DUP825942).
--
-- Fills source: gold.paper_uat_fills. Despite the name this table is the
-- ACCOUNT-WIDE fills ledger for DUP825942 — sync_paper_uat_to_gold.py upserts
-- every execution the UAT session reports (tagged 'strat:<sid>',
-- 'RECON_FLATTEN_*' -> OPS_RECON, or untagged/manual), PK (account, exec_id).
-- Ledger horizon: 2026-08-25. Fills on days the mirror sync did not run are
-- unrecoverable via the TWS API (same-day only) — qty_reconciled exposes the
-- resulting drift against the snapshot.
--
-- Semantics:
--   * FIFO lot matching, both directions (LONG book -> open BUY lots,
--     SHORT book -> open SELL lots). open_qty of an entry-side fill =
--     clamp(cum_entry_qty_through_fill - total_exit_qty, 0, fill qty).
--   * AS-OF the snapshot row's fetched_at, so entry_date/avg price are
--     internally consistent with the quantity and avg_cost the endpoint
--     displays, even when the snapshot is stale relative to the ledger.
--   * entry_date = earliest unmatched entry-side fill (open lot).
--   * strategy_id = dominant tagged strategy across open lots by open qty;
--     NULL when lots are untagged/manual (never fabricate attribution).
--   * qty_reconciled = (ledger net at snapshot == snapshot quantity).
--     FALSE => pre-ledger position history or missed fill captures.

-- ============================================================================
-- Lot-level: one row per fill with its still-open quantity, per live row.
-- ============================================================================
CREATE OR REPLACE VIEW gold.v_live_position_open_lots AS
WITH snap AS (
    SELECT account, ticker, quantity, avg_cost, fetched_at
    FROM gold.ibkr_positions_live
    WHERE quantity <> 0
),
fills AS (
    SELECT
        s.account,
        s.ticker,
        s.fetched_at          AS snapshot_fetched_at,
        f.exec_id,
        f.order_id,
        f.order_ref,
        f.strategy_id,
        f.side,
        f.qty,
        f.price,
        f.currency,
        f.fill_time,
        SUM(CASE WHEN f.side = 'BUY'  THEN f.qty ELSE 0 END)
            OVER (PARTITION BY s.account, s.ticker
                  ORDER BY f.fill_time, f.exec_id
                  ROWS UNBOUNDED PRECEDING) AS cum_buy_qty,
        SUM(CASE WHEN f.side = 'SELL' THEN f.qty ELSE 0 END)
            OVER (PARTITION BY s.account, s.ticker
                  ORDER BY f.fill_time, f.exec_id
                  ROWS UNBOUNDED PRECEDING) AS cum_sell_qty,
        SUM(CASE WHEN f.side = 'BUY'  THEN f.qty ELSE 0 END)
            OVER (PARTITION BY s.account, s.ticker) AS tot_buy_qty,
        SUM(CASE WHEN f.side = 'SELL' THEN f.qty ELSE 0 END)
            OVER (PARTITION BY s.account, s.ticker) AS tot_sell_qty
    FROM snap s
    JOIN gold.paper_uat_fills f
      ON f.account = s.account
     AND f.symbol  = s.ticker
     AND f.fill_time <= (s.fetched_at AT TIME ZONE 'UTC')
)
SELECT
    account,
    ticker,
    snapshot_fetched_at,
    exec_id,
    order_id,
    order_ref,
    strategy_id,
    side,
    qty                                                        AS fill_qty,
    price                                                      AS fill_price,
    currency,
    fill_time,
    CASE
        WHEN side = 'BUY'  THEN GREATEST(0, LEAST(qty, cum_buy_qty  - tot_sell_qty))
        WHEN side = 'SELL' THEN GREATEST(0, LEAST(qty, cum_sell_qty - tot_buy_qty))
    END                                                        AS open_qty,
    (tot_buy_qty - tot_sell_qty)                               AS ledger_net_at_snapshot
FROM fills;

COMMENT ON VIEW gold.v_live_position_open_lots IS
'FIFO open-lot reconstruction for each row of gold.ibkr_positions_live, '
'matched AS-OF the snapshot fetched_at from gold.paper_uat_fills '
'(account-wide DUP825942 fills ledger, horizon 2026-08-25). '
'open_qty = still-unmatched portion of the fill; exit-side fills always '
'net to 0. See migration 2026-11-10_live_position_attribution.sql.';

-- ============================================================================
-- Position rollup: one row per live snapshot row, API-ready.
-- ============================================================================
CREATE OR REPLACE VIEW gold.v_live_position_attribution AS
WITH lots AS (
    SELECT *
    FROM gold.v_live_position_open_lots
    WHERE open_qty > 0
),
agg AS (
    SELECT
        account,
        ticker,
        snapshot_fetched_at,
        MIN(fill_time)                                AS entry_ts,
        COUNT(*)                                      AS open_lots,
        SUM(open_qty * fill_price) / SUM(open_qty)    AS open_lots_avg_price,
        SUM(open_qty)                                 AS open_qty_total,
        SUM(open_qty) FILTER (WHERE strategy_id IS NOT NULL) AS tagged_open_qty,
        MAX(ledger_net_at_snapshot)                   AS ledger_net_at_snapshot
    FROM lots
    GROUP BY account, ticker, snapshot_fetched_at
),
dominant AS (
    -- dominant tagged strategy across open lots, by open qty (ties: earliest fill)
    SELECT DISTINCT ON (account, ticker)
        account, ticker, strategy_id
    FROM lots
    WHERE strategy_id IS NOT NULL
    ORDER BY account, ticker, open_qty DESC, fill_time ASC, exec_id ASC
),
coverage AS (
    SELECT account, MIN(fill_time) AS fills_coverage_from
    FROM gold.paper_uat_fills
    GROUP BY account
)
SELECT
    p.account,
    p.ticker,
    p.quantity                                    AS snapshot_qty,
    p.side                                          AS snapshot_side,
    p.avg_cost                                      AS snapshot_avg_cost,
    p.fetched_at                                    AS snapshot_fetched_at,
    a.entry_ts,
    (a.entry_ts AT TIME ZONE 'UTC')::date           AS entry_date,
    a.open_lots,
    ROUND(a.open_lots_avg_price, 4)                 AS open_lots_avg_price,
    a.ledger_net_at_snapshot,
    (COALESCE(a.ledger_net_at_snapshot, 0) = p.quantity) AS qty_reconciled,
    d.strategy_id,
    sr.name                                         AS strategy_name,
    CASE
        WHEN a.open_qty_total IS NULL OR a.open_qty_total = 0 THEN NULL
        ELSE ROUND(a.tagged_open_qty / a.open_qty_total, 4)
    END                                             AS tagged_open_pct,
    c.fills_coverage_from,
    'gold.paper_uat_fills'::text                    AS fills_source
FROM gold.ibkr_positions_live p
LEFT JOIN agg a      ON a.account = p.account AND a.ticker = p.ticker
LEFT JOIN dominant d ON d.account = p.account AND d.ticker = p.ticker
LEFT JOIN gold.strategy_registry sr ON sr.strategy_id = d.strategy_id
LEFT JOIN coverage c ON c.account = p.account
WHERE p.quantity <> 0;

COMMENT ON VIEW gold.v_live_position_attribution IS
'Per-position entry date + strategy attribution for /api/positions/live. '
'entry_date = earliest unmatched entry-side FIFO lot from the DUP825942 '
'fills ledger (gold.paper_uat_fills), as-of the snapshot row. strategy_id '
'= dominant tagged strategy across open lots; NULL = manual/untagged. '
'qty_reconciled=FALSE means the ledger net disagrees with the snapshot '
'(pre-ledger history or missed captures) — treat entry_date as best-effort.';

-- ============================================================================
-- Verification queries (run manually):
--   SELECT ticker, snapshot_qty, entry_date, open_lots, open_lots_avg_price,
--          ledger_net_at_snapshot, qty_reconciled, strategy_id, tagged_open_pct
--   FROM gold.v_live_position_attribution;
-- ============================================================================
