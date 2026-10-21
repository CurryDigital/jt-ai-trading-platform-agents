# PAPER_UAT reporting mirror — design decision (kanban t_b64f7302, item 3)

Date: 2026-08-25
Status: DECIDED (implementation = Phase 4, tracked as child task)

## Decision

**Separate mirror tables**, NOT a `rehearsal` flag on `gold.paper_trades`.

New gold-schema tables, populated by a qr_etl sync job from the backend UAT
session endpoints (source of truth = IBKR UAT session, account DUP825942,
127.0.0.1:14002 client 2; backend at 127.0.0.1:8000):

- `gold.paper_uat_fills`        — one row per UAT execution/fill
- `gold.paper_uat_positions`    — point-in-time UAT position snapshot (refreshed)
- `gold.paper_uat_open_orders`  — point-in-time working-order snapshot (refreshed)

Attribution: every PAPER_UAT order is fired with `orderRef = strat:{strategy_id}`
(see rebuild_paper_positions.py firing contract). Fills carry the order_ref;
`strategy_id` is derived as `substring(order_ref from '^strat:(.+)$')`. Fills
whose order_ref does not match are stored with `strategy_id = NULL` and surfaced
as unattributed (manual/foreign orders on the UAT account).

## Why separate tables (rejected: rehearsal flag on gold.paper_trades)

1. `gold.paper_trades` / `gold.paper_trades_synthetic` are SIM-ledger tables
   that qr_etl generators restate wholesale (refresh_paper_trades deletes and
   re-derives; rebuild_paper_positions --backfill truncates). Broker-truth rows
   must never live in a table another writer can wipe.
2. The two-systems boundary already exists and works: sim ledger
   (paper_trades*) vs broker mirror (ibkr_positions_live via sync_ibkr_to_gold).
   PAPER_UAT follows the broker-mirror pattern, not the sim-ledger pattern.
3. Performance/Command Center aggregators already reading paper_trades must not
   silently start double-counting broker-rehearsal rows. A separate table makes
   the paper_uat book an explicit opt-in: monthly_pnl adds it via a UNION with
   `book = 'paper_uat'`.
4. The existing `rehearsal` boolean on paper_trades stays semantic: rows
   flagged rehearsal=true are sim rows preserved across refresh; it is not a
   broker-truth marker.

## Consumption / reporting contract (Phase 4 acceptance)

- Fills attributable by `order_ref` -> strategy_id; monthly PnL per
  (strategy_id, month) computable from gold.paper_uat_fills.
- Command Center monthly_pnl gains a `paper_uat` book alongside sim/paper/live.
- Until this mirror lands: the rebalancer assumes ONE PAPER_UAT strategy per
  UAT account (account-level position aggregation caveat, see
  rebuild_paper_positions.py module header and run() warning).

## Sync sketch

- Follow `sync_ibkr_to_gold.py` shape: poll backend UAT endpoints
  (`GET /api/ib/tws/uat/positions`, `GET /api/ib/tws/uat/open-orders`,
  `GET /api/ib/tws/uat/fills`) on the existing ETL cron cadence.
- Hard-fail visibly (pipeline manifest) when the UAT session is disconnected;
  never read the primary/live session as a substitute.

## Blotter reconciliation (added 2026-08-25, kanban t_51368ec4)

The backend close-position endpoint books `gold.manual_orders` ONLY on
synchronous Filled inside the request's wait window; queued orders that fill
at the next open have no waiter and were never persisted. The sync job now
also reconciles every UAT execution into the paper_uat blotter:
`gold.manual_orders` row with `book='paper_uat'`, deterministic
`order_id='uat-<exec_id>'`, `status='filled'`, `created_by='etl_reconciler'`,
`created_at` = fill time (naive +08:00, matching the column convention).
Idempotent via `ON CONFLICT (order_id) DO NOTHING` plus a note-scan that
skips fills the backend already booked synchronously (`note` contains
`ib_order <id>`). Requires migration
`2026-08-25_manual_orders_paper_uat_book.sql` — without the widened
book/side CHECKs every paper_uat blotter insert (backend OR reconciler) is
rejected by the table constraints.
