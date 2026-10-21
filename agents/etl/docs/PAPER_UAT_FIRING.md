# PAPER_UAT Firing Contract (kanban t_2027d985)

Status: LIVE as of 2026-08-31. First live strategy: `crisis_safe_haven_vt_19`
(promoted PAPER -> PAPER_UAT 2026-08-31 ~22:05 UTC for end-to-end verification).

## What fires, when

The per-strategy UAT firing path lives in
`gold/strategy/rebuild_paper_positions.py` (the generic position-aware paper
rebalancer), invoked by `run_signal_cycle.sh` via cron
`qr_etl.pipeline_b_signals` (09:15 UTC Mon-Fri). No separate executor process
exists — firing is a branch of the rebalancer.

- Strategies with `gold.strategy_registry.execution_mode='PAPER_UAT'` keep
  qr_etl signal/sizing ownership (scores -> `compute_target` lot rounding ->
  `consumption.strategies_signals_current`), but order deltas are FIRED to the
  broker-rehearsal book: `POST /api/ib/place-order` with
  `book='paper_uat'`, `strategy_id=<sid>`, `order_ref='strat:<sid>'`.
  The DB paper ledger (`gold.paper_trades_synthetic`, `gold.paper_pending_orders`)
  is NEVER written for PAPER_UAT strategies.
- Cadence = the strategy's normal rebalance cadence (`gold.strategy_registry.
  frequency`): daily/event strategies evaluate every pipeline B run;
  weekly/monthly strategies fire only on the first run of a new ISO week /
  calendar month (gate state in `gold.strategy_rebalance_state`).
  `--force-rebalance` is the ops escape hatch.
- UAT session state is the source of truth for held/working (read live from
  the backend UAT endpoints every firing pass) — NOT the DB ledger.
- HARD FAIL semantics: disconnected UAT session, HTTP error, or a response not
  confirmed with `session='uat'` raises `PaperUatFireError`; the strategy does
  not fire that run, no DB-ledger fallback, process exits non-zero (pipeline B
  shows `last_status: error`). Signals are still published before the raise.
- `PAPER_UAT_HTTP_TIMEOUT` (default 45s, env-overridable) must EXCEED the
  backend's synchronous fill wait (`ib_service.submit_order` waits up to 35s;
  queued MKT orders outside market hours return success with
  status=PreSubmitted after ~30s). A shorter client timeout misreports an
  accepted broker-resting order as a failure (observed 2026-08-31 with the
  old 15s default: IEF BUY 357 landed PreSubmitted while the client raised
  timeout).

## Dedupe key (platform blotter reconciliation)

- Order-level attribution: `order_ref = 'strat:<strategy_id>'`, stamped onto
  TWS `order.orderRef` (50-char limit), echoed on fills.
- Fill-level dedupe in the mirror (`sync_paper_uat_to_gold.py`):
  `gold.paper_uat_fills` upserts on `(account, exec_id)`; blotter rows use
  deterministic `order_id='uat-<exec_id>'` + ON CONFLICT DO NOTHING.
- Fire-level dedupe in the rebalancer: an order is not re-fired if the UAT
  session shows it (a) already held (positions) or (b) already working
  (open-orders, keyed on `(symbol|localSymbol, action)`). One open position
  per (strategy_id, ticker) is therefore enforced by broker state + the
  one-strategy-per-UAT-book limitation below.
- SELL exits fire only for UAT-held tickers in the strategy's OWN universe
  that dropped out of the BUY set — a strategy can never exit a foreign
  ticker.

## Mirror / reporting tables

`sync_paper_uat_to_gold.py` (pipeline A manifest, daily 08:30 UTC; also wired
into `yf_us_postclose_topup.sh` 22:30 UTC Mon-Fri so same-day US-session fills
land the same evening, and `pipeline_d_ibkr_sync.sh` when run manually):

- `gold.paper_uat_fills` (append-only, `strategy_id` parsed from order_ref)
- `gold.paper_uat_positions` / `gold.paper_uat_open_orders` (snapshots)
- `gold.manual_orders` paper_uat blotter rows

## Monitoring regression (fixed 2026-09-26, kanban t_a44c50e1)

Migration 2026-07-25 synced `gold.strategy_paper_monitoring.is_active` with
STRICT `execution_mode='PAPER'`. Promoting a strategy PAPER -> PAPER_UAT
auto-darkened its monitoring (observed 2026-08-31 22:04 UTC on
crisis_safe_haven_vt_19), which later motivated flipping the registry to
SIMULATION to 'match' while the UAT account still held $52k (t_fcfe5f4f /
t_fbbde37e). Fix: migration
`2026-09-26_strategy_paper_monitoring_paper_uat.sql` — the trigger now treats
`execution_mode IN ('PAPER','PAPER_UAT')` as monitored. PAPER_UAT is a live
rehearsal track: it needs MORE monitoring, not less. Regression rule: any
future edit to `gold.trg_sync_strategy_paper_monitoring()` must keep PAPER_UAT
in the monitored set.

## Recurrence guard (added 2026-09-26, kanban t_a44c50e1)

Cron `qr_etl.uat_registry_crosscheck` (daily 09:05 UTC, after pipeline A
08:30 mirror sync; script `~/.hermes/profiles/qr_etl/scripts/uat_registry_crosscheck.sh`)
asserts UAT-book/registry consistency from the gold mirror: orphan positions/
orders with no active PAPER_UAT strategy, >1 active PAPER_UAT strategy, recent
fills attributed to non-PAPER_UAT strategies, unattributed fills, stale mirror.
Signal separation: exit 0 = guard ran (ORPHAN alerts via stdout -> Telegram +
gold.agent_events); exit 2 = guard dead (cron last_status=error). Never
collapse ORPHAN into a non-zero exit — a dead guard must not look like an alert.

## Known limitation

UAT positions/open-orders are ACCOUNT-LEVEL aggregates on DUP825942. Until the
Phase 4 per-strategy attribution ledger lands, the UAT book hosts ONE
PAPER_UAT strategy at a time; the rebalancer prints a WARNING when more than
one is active. DB tickers that match neither IBKR `symbol` nor `localSymbol`
(e.g. `.HK` suffix forms) do not match UAT state — US/ETF universes are the
safe promotion candidates.

## Ops runbook

Promote a strategy:
`UPDATE gold.strategy_registry SET execution_mode='PAPER_UAT' WHERE strategy_id='<sid>';`

Preview without firing:
`python3 gold/strategy/rebuild_paper_positions.py --strategy-id <sid> --force-rebalance --dry-run`

Fire now (bypass cadence gate):
`python3 gold/strategy/rebuild_paper_positions.py --strategy-id <sid> --force-rebalance`

Demote (after flattening the UAT book — the rebalancer does NOT auto-flatten
on demotion):
`UPDATE gold.strategy_registry SET execution_mode='PAPER' WHERE strategy_id='<sid>';`

Unit tests: `gold/strategy/test_paper_uat_firing.py` (20 checks: delta firing,
working-order dedup, disconnect hard-fail, dry-run, non-UAT response
rejection, universe-restricted sells).
