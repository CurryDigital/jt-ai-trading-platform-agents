#!/usr/bin/env python3
"""
Generic position-aware paper rebalancer.

Reads:
- gold.strategy_registry (active PAPER/SIMULATION strategies + universe + capital)
- gold.strategy_ticker_scores (latest BUY/HOLD signals per ticker)
- silver.unified_prices (latest close prices)

Writes:
- consumption.strategies_signals_current (latest signal, strength, confidence, price)
- gold.paper_trades_synthetic (open positions, no more than one open row per ticker per strategy)
- gold.paper_trade_skip_log (append-only audit of zero-size BUY skips)
- consumption.strategy_paper_skips_current (current skip state per strategy/ticker, for the UI)

Behaviour:
- One open position per (strategy_id, ticker).
- Sells (closes) a position when the ticker drops out of the current BUY set.
- Buys (opens) a position when a ticker enters the current BUY set and none exists.
- Does nothing for a ticker already held that is still a BUY signal.
- PnL is calculated on close using real exit price vs entry price.
- Signals are published from strategy_ticker_scores; signal_strength and confidence are derived from the score.

Cadence gate (2026-08-17, t_68b07c59):
- Signal generation stays DAILY and idempotent: strategies_signals_current
  and the skip surface are refreshed on every run regardless of cadence.
- Position mutations (closes/opens) are gated on the strategy's declared
  cadence from gold.strategy_registry.frequency:
    daily    -> every run rebalances (unchanged legacy behaviour)
    weekly   -> rebalance on the first run of each ISO week
    monthly  -> rebalance on the first run of each calendar month
    event / NULL / unknown -> signal-change-driven, ungated
- Gate state lives in gold.strategy_rebalance_state (period-key per
  strategy). Period-key comparison (not calendar-date equality) makes the
  gate robust to missed runs: a monthly strategy whose pipeline was down on
  the 1st rebalances on the first successful run of that month.
- First run under the gate SEEDS the current period for weekly/monthly
  strategies (no surprise mid-period rebalance of books built before the
  gate existed); natural cadence resumes at the next period boundary.
- On gated (non-rebalance) days, new BUY targets that would have opened are
  surfaced as CADENCE_GATE skips; held positions are never touched.
- --force-rebalance and --backfill bypass the gate (ops escape hatches).

Delta-mode deployment clamp (2026-09-18, t_5f69e8c0):
- Delta mode preserves existing position sizes, so NEW entries are sized
  against the deployable budget remaining after retained positions' cost
  basis (deployable_budget + clamp_new_opens), not the full sleeve.
  Sum of open cost basis therefore stays <= assigned capital; a new BUY
  that no longer fits one lot in the remaining budget is surfaced as an
  OVER_DEPLOYED skip. Backfill (closes all first) and PAPER_UAT (broker
  truth) are not clamped.

Concentration cap:
- No single ticker may exceed max_position_pct of assigned capital (global
  default 0.20 via --max-position-pct; 0 disables).
- Per-strategy cap precedence (t_ee1ab601 — never a SILENT global default;
  the source is resolved and logged for every strategy on every run):
  1. explicit gold.strategy_configs override: config_key='max_position_pct'
     with a numeric jsonb config_value (0 < pct <= 1). Used for audited
     rotation sleeves whose thesis requires >20% single-name exposure
     (e.g. vix_scaled 60% SPY).
  2. design-derived cap: gold.strategy_configs config_key='paper_design'
     jsonb with design_max_position_pct (e.g. US Sector top-3 equal weight
     -> 0.34). Declared per strategy by migration
     2026-08-17_strategy_paper_design.sql.
  3. global default when a paper_design row exists but declares no cap
     (logged as a declared fallback).
  4. global default with no paper_design row at all (logged as a WARNING —
     undeclared; add a paper_design row).
  Invalid values are ignored with a warning (never silently disable the
  guardrail). paper_design also declares slot_count (design position slots,
  the UI slot-display input) and residual_cash_policy.

Residual-cash policy (declared; implemented by compute_target):
- Freed slot capital from unsizable signals is redistributed pro-rata by
  score to the remaining fillable BUYs; residual cash (freed capital +
  lot-rounding remainders) is then deployed round-robin in rank order as
  whole lots, bounded by the concentration cap; any undeployable remainder
  parks in cash. This policy string is printed on every run and stored per
  strategy in gold.strategy_configs (config_key='paper_design').

Modes:
- default: incremental update (preserves history, only trades deltas).
- --backfill: truncates stale data and rebuilds a clean current state.

PAPER_UAT firing contract (kanban t_b64f7302, 2026-08-25):
- Strategies with execution_mode='PAPER_UAT' keep qr_etl signal/allocation
  ownership: signals are still published to consumption.strategies_signals_current
  and sizing still runs through compute_target (lot rounding + caps).
- Their order deltas are FIRED to the broker-rehearsal book via the backend
  POST /api/ib/place-order with book='paper_uat' and orderRef="strat:<sid>" —
  NEVER written to the DB paper ledger (gold.paper_trades_synthetic /
  gold.paper_pending_orders). The backend routes paper_uat orders to the
  dedicated UAT session only (paper account DUP825942, 127.0.0.1:14002
  client 2), hard-fails 503 when disconnected, and never falls back to live.
- Position state for the firing pass is read from the UAT session itself
  (source of truth) via the backend live endpoints, not from the DB ledger.
- HARD FAIL semantics: any UAT fire failure (disconnected, HTTP error,
  response not confirmed on the UAT session) aborts that strategy's firing
  for the run — loud log, non-zero process exit, no DB-ledger fallback.
- KNOWN LIMITATION (until the Phase 4 attribution mirror): UAT positions /
  open-orders are ACCOUNT-LEVEL aggregates. Delta firing assumes the UAT
  account hosts one PAPER_UAT strategy's book at a time; run() prints a
  WARNING when more than one is active. SELLs are restricted to tickers in
  the strategy's own universe so a strategy can never exit a foreign ticker.
  IBKR symbols are matched on both contract symbol and localSymbol; DB
  tickers that map to neither (e.g. '.HK' suffix forms) simply won't match.

Fill-price convention (2026-08-17, kanban t_3454cc76):
- Default NEXT_OPEN: orders are booked as deferred fills in
  gold.paper_pending_orders with signal_date = the latest price-bar date at
  order time (the close the signal was computed from). Each run first SETTLES
  pending orders: an order fills at the OPEN of the first bar with
  date > signal_date; entry_date/exit_date = that bar's date. This matches the
  declared 'entry at next open' convention — the previous behaviour priced
  fills at the signal-date close but date-stamped them +1 day (same-bar
  lookahead with a misleading stamp).
- Per-strategy opt-out: gold.strategy_configs config_key='fill_convention'
  = 'SIGNAL_CLOSE' fills immediately at the signal-date close with
  entry_date = signal bar date (honest stamping for strategies that declare
  close-of-signal-date fills).
- The ledger exposes the basis of every fill: entry_price_source_date /
  entry_price_basis and exit_price_source_date / exit_price_basis on
  gold.paper_trades_synthetic. consumption.strategy_paper_pending_current
  surfaces unfilled orders to the UI.

All paths live under the Hermes ETL workspace: agents/etl/gold/strategy/.
"""
import sys, os, argparse, math, json
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path: sys.path.insert(0, _ETL_SHARED)

from db import get_connection


SQL_DROP_SIGNAL_CONSTRAINTS = """
SELECT conname
FROM pg_constraint
JOIN pg_class t ON t.oid = conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'consumption' AND t.relname = 'strategies_signals_current'
  AND contype = 'u'
  AND conname LIKE 'uniq_strategies_signals_current%';
"""

SQL_ADD_SIGNAL_CONSTRAINT = """
ALTER TABLE consumption.strategies_signals_current
ADD CONSTRAINT uniq_strategies_signals_current_strategy_ticker
UNIQUE (strategy_id, ticker);
"""

SQL_DROP_OPEN_POSITION_INDEX = """
SELECT indexname
FROM pg_indexes
WHERE schemaname = 'gold' AND tablename = 'paper_trades_synthetic'
  AND indexname = 'uniq_paper_trades_synthetic_open_strategy_ticker';
"""

SQL_ADD_OPEN_POSITION_INDEX = """
CREATE UNIQUE INDEX uniq_paper_trades_synthetic_open_strategy_ticker
ON gold.paper_trades_synthetic (strategy_id, ticker)
WHERE status = 'open';
"""

SQL_FETCH_ACTIVE_STRATEGIES = """
SELECT
  strategy_id,
  name,
  execution_mode,
  assigned_capital,
  universe_tickers,
  frequency
FROM gold.strategy_registry
WHERE retired_at IS NULL
  AND execution_mode IN ('PAPER', 'SIMULATION', 'PAPER_UAT')
  AND COALESCE(disable_paper_rebuild, FALSE) = FALSE
  AND universe_tickers IS NOT NULL
  AND array_length(universe_tickers, 1) > 0
ORDER BY strategy_id;
"""

SQL_FETCH_LATEST_SCORES = """
SELECT strategy_id, ticker, score, signal_action
FROM gold.strategy_ticker_scores
WHERE strategy_id = ANY(%s);
"""

SQL_FETCH_LATEST_PRICES = """
SELECT DISTINCT ON (ticker)
  ticker,
  date AS price_date,
  open,
  close AS price
FROM silver.unified_prices
WHERE ticker = ANY(%s)
ORDER BY ticker, date DESC;
"""

SQL_FETCH_FILL_BAR = """
SELECT date, open, close, market
FROM silver.unified_prices
WHERE ticker = %s AND date > %s
ORDER BY date ASC
LIMIT 1;
"""

SQL_FETCH_LOT_SIZES = """
SELECT ticker, lot_size
FROM silver.asset_registry
WHERE ticker = ANY(%s)
  AND lot_size IS NOT NULL
  AND lot_size > 0;
"""

SQL_FETCH_OPEN_POSITIONS = """
SELECT id, strategy_id, ticker, direction, entry_date, entry_price, n_shares, status
FROM gold.paper_trades_synthetic
WHERE strategy_id = ANY(%s)
  AND status = 'open';
"""

SQL_FETCH_CAP_OVERRIDES = """
SELECT strategy_id, config_value
FROM gold.strategy_configs
WHERE strategy_id = ANY(%s)
  AND config_key = 'max_position_pct';
"""

SQL_FETCH_PAPER_DESIGNS = """
SELECT strategy_id, config_value
FROM gold.strategy_configs
WHERE strategy_id = ANY(%s)
  AND config_key = 'paper_design';
"""

SQL_FETCH_FILL_CONVENTIONS = """
SELECT strategy_id, config_value
FROM gold.strategy_configs
WHERE strategy_id = ANY(%s)
  AND config_key = 'fill_convention';
"""

# ── Cadence gate state (t_68b07c59) ─────────────────────────────────────
# One row per cadence-gated strategy (weekly/monthly). last_period_key is
# the period of the most recent EXECUTED rebalance; compared against the
# period key of the run date to decide whether today is a rebalance date.
SQL_CREATE_REBALANCE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS gold.strategy_rebalance_state (
  strategy_id         TEXT PRIMARY KEY,
  frequency           TEXT NOT NULL,
  last_period_key     TEXT NOT NULL,
  last_rebalance_date DATE,
  seeded              BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SQL_FETCH_REBALANCE_STATE = """
SELECT strategy_id, frequency, last_period_key, last_rebalance_date
FROM gold.strategy_rebalance_state
WHERE strategy_id = ANY(%s);
"""

SQL_SEED_REBALANCE_STATE = """
INSERT INTO gold.strategy_rebalance_state
  (strategy_id, frequency, last_period_key, last_rebalance_date, seeded, updated_at)
VALUES (%s, %s, %s, NULL, TRUE, NOW())
ON CONFLICT (strategy_id) DO NOTHING;
"""

SQL_TOUCH_REBALANCE_STATE = """
INSERT INTO gold.strategy_rebalance_state
  (strategy_id, frequency, last_period_key, last_rebalance_date, seeded, updated_at)
VALUES (%s, %s, %s, %s, FALSE, NOW())
ON CONFLICT (strategy_id) DO UPDATE SET
  frequency           = EXCLUDED.frequency,
  last_period_key     = EXCLUDED.last_period_key,
  last_rebalance_date = EXCLUDED.last_rebalance_date,
  seeded              = FALSE,
  updated_at          = NOW();
"""

SQL_TRUNCATE_STALE = """
TRUNCATE TABLE gold.paper_trades_synthetic, consumption.strategies_signals_current;
"""

SQL_CLOSE_POSITIONS = """
UPDATE gold.paper_trades_synthetic
SET status = 'closed',
    exit_date = %s,
    exit_price = %s,
    exit_price_source_date = %s,
    exit_price_basis = %s,
    pnl = (%s - entry_price) * n_shares,
    pnl_pct = CASE WHEN entry_price = 0 OR entry_price IS NULL THEN 0
                   ELSE ((%s - entry_price) / entry_price) * 100 END,
    updated_at = NOW()
WHERE id = ANY(%s)
  AND status = 'open';
"""

SQL_OPEN_POSITIONS = """
INSERT INTO gold.paper_trades_synthetic
  (strategy_id, ticker, direction, entry_date, entry_price, n_shares, status,
   signal_weight, assigned_capital, pnl, pnl_pct,
   entry_price_source_date, entry_price_basis, created_at, updated_at)
VALUES %s;
"""

SQL_UPSERT_SIGNALS = """
INSERT INTO consumption.strategies_signals_current
  (strategy_id, ticker, signal, signal_strength, confidence_score, current_price, updated_at)
VALUES %s
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
  signal = EXCLUDED.signal,
  signal_strength = EXCLUDED.signal_strength,
  confidence_score = EXCLUDED.confidence_score,
  current_price = EXCLUDED.current_price,
  updated_at = EXCLUDED.updated_at;
"""

# t_bc9e8d3c: strategies_signals_current.win_rate is a canonical copy of
# gold.strategy_registry.win_rate_oos (backend /api/signals/1 selects it).
# Refreshed after every signal upsert so registry updates propagate.
SQL_REFRESH_SIGNAL_WIN_RATE = """
UPDATE consumption.strategies_signals_current s
SET    win_rate = r.win_rate_oos
FROM   gold.strategy_registry r
WHERE  s.strategy_id = r.strategy_id
  AND  s.strategy_id = %s;
"""


SQL_CREATE_SKIP_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS gold.paper_trade_skip_log (
  id            BIGSERIAL PRIMARY KEY,
  strategy_id   TEXT NOT NULL,
  ticker        TEXT NOT NULL,
  signal_action TEXT NOT NULL,
  score         NUMERIC,
  weight        NUMERIC,
  slot_notional NUMERIC,
  price         NUMERIC,
  lot_size      NUMERIC,
  lot_cost      NUMERIC,
  skip_kind     TEXT NOT NULL,
  reason        TEXT NOT NULL,
  skip_date     DATE NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SQL_CREATE_SKIP_LOG_INDEX = """
CREATE INDEX IF NOT EXISTS idx_paper_trade_skip_log_strategy_date
ON gold.paper_trade_skip_log (strategy_id, skip_date DESC);
"""

SQL_CREATE_SKIP_CURRENT_TABLE = """
CREATE TABLE IF NOT EXISTS consumption.strategy_paper_skips_current (
  strategy_id   TEXT NOT NULL,
  ticker        TEXT NOT NULL,
  signal_action TEXT NOT NULL,
  score         NUMERIC,
  weight        NUMERIC,
  slot_notional NUMERIC,
  price         NUMERIC,
  lot_size      NUMERIC,
  lot_cost      NUMERIC,
  skip_kind     TEXT NOT NULL,
  reason        TEXT NOT NULL,
  skip_date     DATE NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uniq_strategy_paper_skips_current_strategy_ticker UNIQUE (strategy_id, ticker)
);
"""

SQL_DELETE_CURRENT_SKIPS = """
DELETE FROM consumption.strategy_paper_skips_current WHERE strategy_id = %s;
"""

SQL_DELETE_STALE_CURRENT_SKIPS = """
DELETE FROM consumption.strategy_paper_skips_current WHERE strategy_id <> ALL(%s);
"""

SQL_INSERT_SKIP_LOG = """
INSERT INTO gold.paper_trade_skip_log
  (strategy_id, ticker, signal_action, score, weight, slot_notional,
   price, lot_size, lot_cost, skip_kind, reason, skip_date, created_at)
VALUES %s;
"""

SQL_INSERT_SKIP_CURRENT = """
INSERT INTO consumption.strategy_paper_skips_current
  (strategy_id, ticker, signal_action, score, weight, slot_notional,
   price, lot_size, lot_cost, skip_kind, reason, skip_date, updated_at)
VALUES %s
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
  signal_action = EXCLUDED.signal_action,
  score = EXCLUDED.score,
  weight = EXCLUDED.weight,
  slot_notional = EXCLUDED.slot_notional,
  price = EXCLUDED.price,
  lot_size = EXCLUDED.lot_size,
  lot_cost = EXCLUDED.lot_cost,
  skip_kind = EXCLUDED.skip_kind,
  reason = EXCLUDED.reason,
  skip_date = EXCLUDED.skip_date,
  updated_at = EXCLUDED.updated_at;
"""

# ── Deferred fill orders (NEXT_OPEN convention, t_3454cc76) ──────────────
# Orders are booked with signal_date = the bar date whose close generated the
# signal, and settled at the OPEN of the first bar with date > signal_date.
SQL_CREATE_PENDING_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS gold.paper_pending_orders (
  id               BIGSERIAL PRIMARY KEY,
  strategy_id      TEXT NOT NULL,
  ticker           TEXT NOT NULL,
  order_kind       TEXT NOT NULL CHECK (order_kind IN ('OPEN', 'CLOSE')),
  signal_date      DATE NOT NULL,
  position_id      INTEGER,
  n_shares         NUMERIC,
  signal_weight    NUMERIC,
  assigned_capital NUMERIC,
  score            NUMERIC,
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'filled', 'cancelled')),
  fill_date        DATE,
  fill_price       NUMERIC,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  filled_at        TIMESTAMPTZ
);
"""

SQL_CREATE_PENDING_OPEN_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uniq_paper_pending_open_strategy_ticker
ON gold.paper_pending_orders (strategy_id, ticker)
WHERE status = 'pending' AND order_kind = 'OPEN';
"""

SQL_CREATE_PENDING_CLOSE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uniq_paper_pending_close_position
ON gold.paper_pending_orders (position_id)
WHERE status = 'pending' AND order_kind = 'CLOSE';
"""

SQL_CREATE_PENDING_CURRENT_TABLE = """
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
"""

SQL_FETCH_PENDING_ORDERS = """
SELECT id, strategy_id, ticker, order_kind, signal_date, position_id,
       n_shares, signal_weight, assigned_capital, score
FROM gold.paper_pending_orders
WHERE status = 'pending'
  AND strategy_id = ANY(%s)
ORDER BY id;
"""

SQL_INSERT_PENDING_ORDERS = """
INSERT INTO gold.paper_pending_orders
  (strategy_id, ticker, order_kind, signal_date, position_id, n_shares,
   signal_weight, assigned_capital, score, status, created_at)
VALUES %s;
"""

SQL_MARK_ORDER_FILLED = """
UPDATE gold.paper_pending_orders
SET status = 'filled', filled_at = NOW(), fill_date = %s, fill_price = %s
WHERE id = %s AND status = 'pending';
"""

SQL_CANCEL_ORDER = """
UPDATE gold.paper_pending_orders
SET status = 'cancelled', filled_at = NOW()
WHERE id = %s AND status = 'pending';
"""

SQL_CANCEL_PENDING_INACTIVE = """
UPDATE gold.paper_pending_orders
SET status = 'cancelled', filled_at = NOW()
WHERE status = 'pending' AND strategy_id <> ALL(%s);
"""

SQL_DELETE_PENDING_MIRROR_SCOPED = """
DELETE FROM consumption.strategy_paper_pending_current WHERE strategy_id = %s;
"""

SQL_DELETE_PENDING_MIRROR_STALE = """
DELETE FROM consumption.strategy_paper_pending_current WHERE strategy_id <> ALL(%s);
"""

SQL_REFRESH_PENDING_MIRROR = """
INSERT INTO consumption.strategy_paper_pending_current
  (strategy_id, ticker, order_kind, signal_date, n_shares, signal_weight,
   assigned_capital, score, expected_fill, updated_at)
SELECT strategy_id, ticker, order_kind, signal_date, n_shares, signal_weight,
       assigned_capital, score, 'next_open', NOW()
FROM gold.paper_pending_orders
WHERE status = 'pending' AND strategy_id = %s
ON CONFLICT (strategy_id, ticker, order_kind) DO UPDATE SET
  signal_date      = EXCLUDED.signal_date,
  n_shares         = EXCLUDED.n_shares,
  signal_weight    = EXCLUDED.signal_weight,
  assigned_capital = EXCLUDED.assigned_capital,
  score            = EXCLUDED.score,
  expected_fill    = EXCLUDED.expected_fill,
  updated_at       = EXCLUDED.updated_at;
"""

SQL_CHECK_OPEN_POSITION = """
SELECT id FROM gold.paper_trades_synthetic
WHERE strategy_id = %s AND ticker = %s AND status = 'open';
"""


# ---------------------------------------------------------------------------
# PAPER_UAT firing helpers (kanban t_b64f7302, 2026-08-25)
# ---------------------------------------------------------------------------
PAPER_UAT_API_BASE = os.environ.get('PAPER_UAT_API_BASE', 'http://127.0.0.1:8000')
# Must EXCEED the backend's synchronous fill wait: services/ib_service.py
# _process_order_request waits up to 30s for a fill and submit_order up to
# 35s before returning success with status=PreSubmitted (queued MKT orders
# outside market hours). A shorter timeout here misreports an accepted,
# broker-resting order as a fire failure (seen 2026-08-31: IEF BUY 357
# landed PreSubmitted while the client had already raised on a 15s timeout).
PAPER_UAT_HTTP_TIMEOUT = float(os.environ.get('PAPER_UAT_HTTP_TIMEOUT', '45'))


class PaperUatFireError(RuntimeError):
    """Hard failure of the PAPER_UAT firing path. Never falls back to the DB
    paper ledger — the strategy simply does not fire this run."""


def _uat_http(method, path, payload=None):
    url = PAPER_UAT_API_BASE.rstrip('/') + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=PAPER_UAT_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')[:500]
        raise PaperUatFireError(f"{method} {path} -> HTTP {e.code}: {body}")
    except PaperUatFireError:
        raise
    except Exception as e:
        raise PaperUatFireError(f"{method} {path} failed: {e}")


def fetch_uat_positions():
    """{ticker: qty} held on the UAT session (source of truth), keyed by BOTH
    the IBKR contract symbol and localSymbol so DB tickers match either form."""
    r = _uat_http('GET', '/api/ib/tws/uat/positions')
    if not r.get('connected') or r.get('data') is None:
        raise PaperUatFireError(
            f"UAT session not connected (positions): {r.get('error') or 'connected=false'}")
    held = {}
    for p in r['data']:
        qty = float(p.get('qty') or 0)
        for key in {p.get('symbol'), p.get('ticker')} - {None}:
            held[key] = qty
    return held


def fetch_uat_working_orders():
    """{(symbol, action)} of working (unfilled) orders on the UAT session,
    keyed by both symbol and localSymbol. Used to suppress re-firing an order
    that is already resting at the broker."""
    r = _uat_http('GET', '/api/ib/tws/uat/open-orders')
    if not r.get('connected') or r.get('data') is None:
        raise PaperUatFireError(
            f"UAT session not connected (open-orders): {r.get('error') or 'connected=false'}")
    working = set()
    for o in r['data']:
        act = (o.get('action') or '').upper()
        if not act:
            continue
        for key in {o.get('symbol'), o.get('local_symbol')} - {None}:
            working.add((key, act))
    return working


def fire_paper_uat_order(sid, ticker, action, quantity, dry_run=False):
    """Fire ONE order to the PAPER_UAT book via the backend place-order
    endpoint. Hard-fails (PaperUatFireError) on any non-success or on any
    response that did not route through the UAT session — a PAPER_UAT order
    must never land on the live/primary session or be silently simulated."""
    qty = int(quantity)
    if qty <= 0:
        raise PaperUatFireError(
            f"refusing to fire {action} {ticker} x{quantity} (non-positive qty)")
    if dry_run:
        print(f"  {sid}: DRY RUN would fire PAPER_UAT {action} {ticker} x{qty} "
              f"(book=paper_uat, orderRef=strat:{sid})")
        return {'dry_run': True}
    r = _uat_http('POST', '/api/ib/place-order', {
        'symbol': ticker, 'action': action, 'quantity': qty,
        'order_type': 'MKT', 'book': 'paper_uat',
        'strategy_id': sid, 'order_ref': f'strat:{sid}',
    })
    if not r.get('success') or r.get('simulated') or r.get('session') != 'uat':
        raise PaperUatFireError(
            f"place-order for {action} {ticker} x{qty} was NOT confirmed on the "
            f"UAT session (response: {json.dumps(r)[:400]}) — treating as not fired")
    return r


def ensure_constraints(cur):
    """Add idempotency constraints if not already present."""
    cur.execute(SQL_DROP_SIGNAL_CONSTRAINTS)
    exists = cur.fetchone()
    if not exists:
        cur.execute(SQL_ADD_SIGNAL_CONSTRAINT)
        print("  Added unique constraint on consumption.strategies_signals_current(strategy_id, ticker)")

    cur.execute(SQL_DROP_OPEN_POSITION_INDEX)
    exists = cur.fetchone()
    if not exists:
        cur.execute(SQL_ADD_OPEN_POSITION_INDEX)
        print("  Added partial unique index on gold.paper_trades_synthetic open positions")


def ensure_skip_tables(cur):
    """Create the zero-size skip-surface tables if they do not exist yet."""
    cur.execute(SQL_CREATE_SKIP_LOG_TABLE)
    cur.execute(SQL_CREATE_SKIP_LOG_INDEX)
    cur.execute(SQL_CREATE_SKIP_CURRENT_TABLE)


def ensure_pending_tables(cur):
    """Create the deferred-fill (NEXT_OPEN) order tables if they do not exist."""
    cur.execute(SQL_CREATE_PENDING_ORDERS_TABLE)
    cur.execute(SQL_CREATE_PENDING_OPEN_INDEX)
    cur.execute(SQL_CREATE_PENDING_CLOSE_INDEX)
    cur.execute(SQL_CREATE_PENDING_CURRENT_TABLE)


FILL_CONVENTIONS = ('NEXT_OPEN', 'SIGNAL_CLOSE')


def fetch_fill_conventions(cur, strategy_ids):
    """Per-strategy fill convention from gold.strategy_configs.

    config_key='fill_convention', config_value jsonb: plain string
    ('"SIGNAL_CLOSE"') or {"value": "SIGNAL_CLOSE"}. Default NEXT_OPEN;
    invalid values are dropped with a warning so a bad config row can never
    silently change the fill convention.
    """
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_FILL_CONVENTIONS, (strategy_ids,))
    conventions = {}
    for sid, val in cur.fetchall():
        if isinstance(val, dict):
            val = val.get('value')
        conv = str(val).strip().upper() if val is not None else ''
        if conv not in FILL_CONVENTIONS:
            print(f"  {sid}: WARNING invalid fill_convention config {val!r}; "
                  f"falling back to NEXT_OPEN")
            continue
        conventions[sid] = conv
    return conventions


def resolve_fill_convention(conventions, strategy_id):
    """Effective fill convention: per-strategy override, else NEXT_OPEN."""
    if conventions and strategy_id in conventions:
        return conventions[strategy_id]
    return 'NEXT_OPEN'


def fetch_pending_maps(cur, strategy_ids):
    """Pending-order dedupe maps: ({sid: {ticker}}, {position_id}).

    OPEN map prevents double-booking a pending entry; CLOSE map prevents
    double-booking an exit for a position that already has a resting close.
    """
    open_tickers = {}
    close_posids = set()
    if not strategy_ids:
        return open_tickers, close_posids
    cur.execute(SQL_FETCH_PENDING_ORDERS, (strategy_ids,))
    for r in cur.fetchall():
        if r[3] == 'OPEN':
            open_tickers.setdefault(r[1], set()).add(r[2])
        elif r[5] is not None:
            close_posids.add(r[5])
    return open_tickers, close_posids


def queue_pending_orders(cur, rows):
    """Book deferred orders. rows: (strategy_id, ticker, order_kind,
    signal_date, position_id, n_shares, signal_weight, assigned_capital, score)."""
    if not rows:
        return 0
    from psycopg2.extras import execute_values
    execute_values(
        cur, SQL_INSERT_PENDING_ORDERS, rows,
        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', NOW())"
    )
    return cur.rowcount


def fetch_fill_bar(cur, ticker, signal_date):
    """First bar strictly after the signal bar — the NEXT_OPEN fill bar."""
    cur.execute(SQL_FETCH_FILL_BAR, (ticker, signal_date))
    return cur.fetchone()


# ── Fill-bar finality gate (t_823e0bbf) ─────────────────────────────────────
# 2026-09-23: settle_pending_orders filled GLD OPEN orders at 402.45 from a
# PROVISIONAL premarket bar (05:15 ET) that the post-close refresh later
# revised to open=400.48. silver.unified_prices upserts in place on
# (ticker,date), so a bar dated "today" in its market's timezone may still be
# intraday/premarket when the 09:15 UTC signal cycle settles. Fill only on
# bars whose market day has CLOSED in market-local time; provisional bars
# leave the order resting until a later cycle (fill date is still the bar
# date, so the ledger keeps the true entry date — only the booking cycle moves).
#
# (tz, close_local, day_offset): bar dated D is final at
# datetime.combine(D + day_offset, close_local) in tz.
MARKET_CLOSE_LOCAL = {
    'US':     ('America/New_York',  dtime(16, 0), 0),
    'HK':     ('Asia/Hong_Kong',    dtime(16, 0), 0),
    'CN':     ('Asia/Shanghai',     dtime(15, 0), 0),
    'SG':     ('Asia/Singapore',    dtime(17, 0), 0),
    'FX':     ('America/New_York',  dtime(17, 0), 0),  # NY close convention
    # GLOBAL mixes CME futures (US trade-date bars) and 24/7 crypto — take the
    # conservative bound for both: final only once the UTC day has ended.
    'GLOBAL': ('UTC',               dtime(0, 0),  1),
    # INDEX rows are regime inputs, never paper fill bars; per-ticker close.
    'INDEX':  ('America/New_York',  dtime(16, 0), 0),
}
INDEX_TICKER_CLOSE = {
    '^HSI':   ('Asia/Hong_Kong',    dtime(16, 0), 0),
    '^N225':  ('Asia/Tokyo',        dtime(15, 0), 0),
    '^FTSE':  ('Europe/London',     dtime(16, 30), 0),
    '^FCHI':  ('Europe/Paris',      dtime(17, 30), 0),
    '^GDAXI': ('Europe/Berlin',     dtime(17, 30), 0),
}
# Unknown/NULL market: conservative — bar final only from the next UTC day.
_FALLBACK_CLOSE = ('UTC', dtime(0, 0), 1)


def bar_is_final(bar_date, market, ticker=None, now_utc=None):
    """True when bar_date's market session has closed in market-local time.

    now_utc injectable for tests. A False result means the bar may still be
    revised (premarket/intraday provisional) and must not anchor a fill.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if market == 'INDEX' and ticker in INDEX_TICKER_CLOSE:
        tz_name, close_t, day_off = INDEX_TICKER_CLOSE[ticker]
    else:
        tz_name, close_t, day_off = MARKET_CLOSE_LOCAL.get(market, _FALLBACK_CLOSE)
    final_at = datetime.combine(bar_date + timedelta(days=day_off),
                                close_t, tzinfo=ZoneInfo(tz_name))
    return now_utc >= final_at


def settle_pending_orders(cur, today, strategy_ids, now_utc=None):
    """Fill due deferred orders at the open of the first bar after signal_date.

    Runs at the START of every rebalancer run, before open positions are
    fetched, so freshly filled entries are visible to the rebalance logic.
    A resting order fills regardless of the current signal — it was placed
    when the signal fired and would have executed at that next open.

    now_utc: injectable wall clock for the fill-bar finality gate
    (t_823e0bbf); defaults to datetime.now(timezone.utc) inside bar_is_final.
    """
    if not strategy_ids:
        return {'filled_open': 0, 'filled_close': 0, 'waiting': 0}
    cur.execute(SQL_FETCH_PENDING_ORDERS, (strategy_ids,))
    orders = cur.fetchall()
    filled_open = filled_close = waiting = 0
    for (oid, sid, ticker, kind, signal_date, position_id,
         n_shares, weight, cap, score) in orders:
        bar = fetch_fill_bar(cur, ticker, signal_date)
        if not bar:
            waiting += 1
            print(f"  {sid}: PENDING {kind} {ticker} (signal {signal_date}) - "
                  f"no newer bar yet; order rests")
            continue
        bar_date, bar_open, bar_close, bar_market = bar
        # Fill-bar finality gate (t_823e0bbf): a bar dated "today" in its
        # market's timezone may be a provisional premarket/intraday bar that
        # the post-close refresh will revise in place. Never anchor a fill to
        # it — the order rests until the bar's session has closed.
        if not bar_is_final(bar_date, bar_market, ticker=ticker, now_utc=now_utc):
            waiting += 1
            print(f"  {sid}: PENDING {kind} {ticker} (signal {signal_date}) - "
                  f"fill bar {bar_date} market={bar_market} still provisional "
                  f"(session not closed); order rests")
            continue
        if bar_open is not None and float(bar_open) > 0:
            price, basis = bar_open, 'NEXT_OPEN'
        elif bar_close is not None and float(bar_close) > 0:
            price, basis = bar_close, 'NEXT_OPEN_CLOSE_FALLBACK'
        else:
            waiting += 1
            print(f"  {sid}: PENDING {kind} {ticker} - fill bar {bar_date} has "
                  f"no usable open/close; order rests")
            continue
        if kind == 'OPEN':
            cur.execute(SQL_CHECK_OPEN_POSITION, (sid, ticker))
            if cur.fetchone():
                # A position appeared while the order rested (e.g. manual
                # booking); cancel the duplicate rather than breach the
                # one-open-position invariant.
                cur.execute(SQL_CANCEL_ORDER, (oid,))
                print(f"  {sid}: CANCEL pending OPEN {ticker} - position already open")
                continue
            open_new_positions(cur, [(
                sid, ticker, bar_date, price, n_shares, weight, cap,
                bar_date, basis
            )])
            filled_open += 1
        else:
            close_positions(cur, bar_date, [position_id], price,
                            source_date=bar_date, basis=basis)
            filled_close += 1
        cur.execute(SQL_MARK_ORDER_FILLED, (bar_date, price, oid))
        print(f"  {sid}: FILLED {kind} {ticker} @ {price} ({basis}, "
              f"bar {bar_date}, signal {signal_date})")
    return {'filled_open': filled_open, 'filled_close': filled_close,
            'waiting': waiting}


def refresh_pending_mirror(cur, sid):
    """Refresh the UI surface of pending fills for one strategy."""
    cur.execute(SQL_DELETE_PENDING_MIRROR_SCOPED, (sid,))
    cur.execute(SQL_REFRESH_PENDING_MIRROR, (sid,))


def fetch_active_strategies(cur, strategy_id=None):
    params = ()
    strategy_filter = ""
    if strategy_id:
        strategy_filter = "AND strategy_id = %s"
        params = (strategy_id,)
    cur.execute(f"""
        SELECT
          strategy_id,
          name,
          execution_mode,
          assigned_capital,
          universe_tickers,
          frequency
        FROM gold.strategy_registry
        WHERE retired_at IS NULL
          AND execution_mode IN ('PAPER', 'SIMULATION', 'PAPER_UAT')
          AND COALESCE(disable_paper_rebuild, FALSE) = FALSE
          AND universe_tickers IS NOT NULL
          AND array_length(universe_tickers, 1) > 0
          {strategy_filter}
        ORDER BY strategy_id;
    """, params)
    rows = cur.fetchall()
    return [
        {
            'strategy_id': r[0],
            'name': r[1],
            'mode': r[2],
            'capital': r[3] or 0,
            'universe': r[4] or [],
            'frequency': r[5],
        }
        for r in rows
    ]


def fetch_prices(cur, tickers):
    """Latest bar per ticker: {ticker: {'date': date, 'open': o, 'close': c}}.

    The fill-convention work (t_3454cc76) needs the bar DATE and OPEN, not
    just the close: signal_date = latest bar date, and NEXT_OPEN fills use
    the open of the first bar after it.
    """
    if not tickers:
        return {}
    cur.execute(SQL_FETCH_LATEST_PRICES, (tickers,))
    return {r[0]: {'date': r[1], 'open': r[2], 'close': r[3]} for r in cur.fetchall()}


def close_map_of(prices):
    """{ticker: latest close} — sizing/signal-publish view of the bar map."""
    return {t: b['close'] for t, b in prices.items()}


def fetch_scores(cur, strategy_ids):
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_LATEST_SCORES, (strategy_ids,))
    rows = cur.fetchall()
    # grouped by strategy_id
    scores = {}
    for r in rows:
        sid = r[0]
        scores.setdefault(sid, []).append({
            'ticker': r[1],
            'score': r[2] or 0,
            'action': r[3],
        })
    return scores


def fetch_open_positions(cur, strategy_ids):
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_OPEN_POSITIONS, (strategy_ids,))
    rows = cur.fetchall()
    positions = {}
    for r in rows:
        sid = r[1]
        positions.setdefault(sid, {})[r[2]] = {
            'id': r[0],
            'direction': r[3],
            'entry_date': r[4],
            'entry_price': r[5] or 0,
            'n_shares': r[6] or 0,
            'status': r[7],
        }
    return positions


def fetch_lot_sizes(cur, tickers):
    """Board/round lot sizes from the asset registry (silver.asset_registry.lot_size)."""
    if not tickers:
        return {}
    cur.execute(SQL_FETCH_LOT_SIZES, (tickers,))
    return {r[0]: float(r[1]) for r in cur.fetchall()}


def fetch_cap_overrides(cur, strategy_ids):
    """Per-strategy concentration-cap overrides from gold.strategy_configs.

    config_key='max_position_pct', config_value jsonb: plain number (0.6) or
    {"value": 0.6}. Returns {strategy_id: float} for valid entries only
    (0 < pct <= 1.0); invalid entries are dropped with a warning so a bad
    config row can never silently disable or zero the guardrail.
    """
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_CAP_OVERRIDES, (strategy_ids,))
    overrides = {}
    for sid, val in cur.fetchall():
        if isinstance(val, dict):
            val = val.get('value')
        try:
            pct = float(val)
        except (TypeError, ValueError):
            print(f"  {sid}: WARNING invalid max_position_pct config {val!r}; "
                  f"falling back to default cap")
            continue
        if not (0 < pct <= 1.0):
            print(f"  {sid}: WARNING max_position_pct config {pct} out of range "
                  f"(0, 1]; falling back to default cap")
            continue
        overrides[sid] = pct
    return overrides


def resolve_max_position_pct(overrides, strategy_id, default_pct):
    """Effective concentration cap for a strategy: per-strategy override from
    gold.strategy_configs when present, else the global default (CLI arg)."""
    if overrides and strategy_id in overrides:
        return overrides[strategy_id]
    return default_pct


def fetch_paper_designs(cur, strategy_ids):
    """Declared paper-design metadata from gold.strategy_configs (t_ee1ab601).

    config_key='paper_design', config_value jsonb object with (at least):
      slot_count              design position slots (UI display input)
      weighting               design weighting scheme (human-readable)
      design_max_position_pct cap derived from the declared design, or null
      residual_cash_policy    declared engine residual-cash policy
      design_source           where the design is declared (audit trail)

    Returns {strategy_id: {'cap': float|None, 'slot_count': int|None,
    'design': dict}}. An out-of-range design_max_position_pct is dropped
    with a warning (a bad design row can never silently disable the
    guardrail).
    """
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_PAPER_DESIGNS, (strategy_ids,))
    designs = {}
    for sid, val in cur.fetchall():
        if not isinstance(val, dict):
            print(f"  {sid}: WARNING invalid paper_design config {val!r}; "
                  f"treating as undeclared")
            continue
        cap = val.get('design_max_position_pct')
        if cap is not None:
            try:
                cap = float(cap)
            except (TypeError, ValueError):
                print(f"  {sid}: WARNING invalid paper_design "
                      f"design_max_position_pct {cap!r}; ignoring design cap")
                cap = None
            else:
                if not (0 < cap <= 1.0):
                    print(f"  {sid}: WARNING paper_design "
                          f"design_max_position_pct {cap} out of range (0, 1]; "
                          f"ignoring design cap")
                    cap = None
        designs[sid] = {
            'cap': cap,
            'slot_count': val.get('slot_count'),
            'design': val,
        }
    return designs


def resolve_cap_with_source(overrides, designs, strategy_id, default_pct):
    """Effective concentration cap AND its declaration source (t_ee1ab601).

    Precedence (no more silent global default):
      1. explicit gold.strategy_configs max_position_pct override -> 'override'
      2. paper_design.design_max_position_pct (design-derived)    -> 'design'
      3. global default with a paper_design row present           -> 'declared_fallback'
      4. global default with NO paper_design row                  -> 'undeclared_default'

    Returns (pct, source).
    """
    if overrides and strategy_id in overrides:
        return overrides[strategy_id], 'override'
    if designs and strategy_id in designs:
        cap = designs[strategy_id].get('cap')
        if cap is not None:
            return cap, 'design'
        return default_pct, 'declared_fallback'
    return default_pct, 'undeclared_default'


# ── Cadence gate helpers (t_68b07c59) ───────────────────────────────────
GATED_FREQUENCIES = ('weekly', 'monthly')


def normalize_frequency(frequency):
    """Registry frequency, lower-cased and stripped ('DAILY' -> 'daily')."""
    return (frequency or '').strip().lower()


def is_gated_frequency(frequency):
    """Only weekly/monthly strategies are cadence-gated. Daily strategies
    keep legacy every-run behaviour; event/NULL/unknown strategies are
    signal-change-driven (their declared cadence IS the signal)."""
    return normalize_frequency(frequency) in GATED_FREQUENCIES


def period_key_for(frequency, d):
    """Period key for the run date under the strategy's cadence.

    weekly  -> 'W:<iso_year>-<iso_week>' (first run of the ISO week wins)
    monthly -> 'M:<year>-<month>'
    anything else -> None (ungated)

    Comparing period keys instead of calendar dates makes the gate robust
    to missed runs: if the pipeline was down on the 1st, the first
    successful run of the month still counts as the monthly rebalance.
    """
    f = normalize_frequency(frequency)
    if f == 'weekly':
        iso = d.isocalendar()
        return f"W:{iso[0]}-{iso[1]:02d}"
    if f == 'monthly':
        return f"M:{d.year}-{d.month:02d}"
    return None


def decide_rebalance(frequency, today, state, backfill=False, force_rebalance=False):
    """Should position mutations execute for this strategy on `today`?

    Returns (execute, period_key, reason). Pure function — unit-tested
    without a DB. Only meaningful for gated frequencies; callers skip the
    decision entirely for daily/event strategies.

    - backfill / force_rebalance always execute (ops escape hatches).
    - No state row: first run under the gate -> seed the current period,
      do NOT rebalance (books built pre-gate are left untouched until the
      next natural period boundary).
    - Stored frequency differs from the registry's current frequency:
      cadence changed -> rebalance and re-key the state.
    - Period key changed -> rebalance date.
    """
    key = period_key_for(frequency, today)
    if key is None:
        return True, None, 'ungated frequency'
    if backfill:
        return True, key, 'backfill override'
    if force_rebalance:
        return True, key, 'force-rebalance override'
    if state is None:
        return False, key, 'seed: first gated run, period seeded without rebalancing'
    if normalize_frequency(state.get('frequency')) != normalize_frequency(frequency):
        return True, key, 'cadence changed in registry'
    if state.get('last_period_key') != key:
        return True, key, f"new period (last {state.get('last_period_key')})"
    return False, key, f"period {key} already rebalanced {state.get('last_rebalance_date')}"


def ensure_rebalance_state_table(cur):
    cur.execute(SQL_CREATE_REBALANCE_STATE_TABLE)


def fetch_rebalance_state(cur, strategy_ids):
    if not strategy_ids:
        return {}
    cur.execute(SQL_FETCH_REBALANCE_STATE, (strategy_ids,))
    return {
        r[0]: {'frequency': r[1], 'last_period_key': r[2], 'last_rebalance_date': r[3]}
        for r in cur.fetchall()
    }


def lot_size_for(ticker, lots):
    """Round-lot size for position sizing.

    DECISION 2026-08-17 (t_928a4e7d, docs/decisions/2026-08-17_lot_convention.md):
    US-listed equities/ETFs trade in WHOLE SHARES (lot = 1), not 100-share
    round lots. IBKR — the venue this paper engine mirrors — supports
    fractional US shares, so a 1-share minimum is conservative-realistic.
    The previous hardcoded 100-share rule was never a recorded platform
    policy, and it silently excluded high-priced core legs from the book
    (e.g. SPY ~$778/share needed a $77.8K slot to afford one lot, so the
    tsmom strategy could never hold its core equity leg; BELOW_ONE_LOT
    skips fired daily 2026-08-05..08-14).

    - US-listed equities/ETFs (bare symbols): 1 share. A populated
      silver.asset_registry.lot_size row overrides (registry-first).
    - HK tickers (.HK): board lot from silver.asset_registry.lot_size when
      populated, else 1 (no rounding) until the registry is filled in.
    - SG tickers (.SI): SGX board lot 100 (registry override when populated).
    - Futures and other non-share instruments (e.g. GC=F): 1 (not lot-rounded).
    """
    if ticker.endswith('.HK'):
        return lots.get(ticker, 1)
    if '=' in ticker:
        return 1
    if ticker.endswith('.SI'):
        return lots.get(ticker, 100)
    return lots.get(ticker, 1)


def compute_target(signals, capital, prices, lots, max_position_pct=0.20):
    """Lot-aware target allocation. Returns (targets, skipped).

    targets: list of {ticker, price, weight, shares, score} for BUY tickers
    to hold, sized in whole lots in rank order (highest score first).

    skipped: list of dicts for BUY signals that produce no position (or that
    hit a sizing guardrail). Each skip is explicit and carries: ticker,
    signal_action, score, weight, slot_notional, price, lot_size, lot_cost,
    skip_kind, reason.

    skip_kind:
    - 'BELOW_ONE_LOT': slot capital cannot afford one lot (equities/HK).
    - 'UNSUPPORTED_ASSET_CLASS': futures ('=' ticker) sized to 0 units; the
      paper ledger has no contract multiplier and fractional contracts are
      disabled, so the signal is not expressible at this slot capital.
    - 'NO_PRICE': no usable latest price in silver.unified_prices.
    - 'CONCENTRATION_CAP': position or residual deployment would exceed
      max_position_pct of assigned capital. When the ticker still holds a
      (capped) position, this row documents that residual cash was NOT
      deployed into it.

    Freed slot capital from sized skips is redistributed to the remaining
    fillable signals (larger lots) so assigned capital is deployed instead
    of parking in cash. NO_PRICE skips do not redistribute (conservative).

    Concentration cap: no single ticker may exceed max_position_pct
    (default 0.20) of assigned capital. The cap is applied AFTER slot sizing
    and freed-capital redistribution but BEFORE the residual-cash
    round-robin, and the round-robin skips any ticker whose next lot would
    breach the cap (trying the next ticker instead).

    Only BUY signals are traded. A CASH signal (HOLD action) is counted in
    the total score so that the residual cash target is respected: the
    deployable budget is cap * (sum BUY scores / total score), and only
    freed slot capital from skipped signals is redistributed.
    """
    if not signals:
        return [], []
    buy_signals = [s for s in signals if s['action'] == 'BUY']
    cash_signal = next((s for s in signals if s['ticker'] == 'CASH'), None)
    buy_score_sum = sum(max(0, float(s['score'])) for s in buy_signals)
    total_score = buy_score_sum
    if cash_signal:
        total_score += max(0, float(cash_signal['score']))
    if total_score <= 0:
        return [], []

    cap = float(capital)
    budget = cap * (buy_score_sum / total_score)  # respects CASH residual
    # NOTE: deployable_budget() mirrors this formula for the delta-mode
    # clamp — keep the two in sync.

    # Rank order: highest score first (ticker as deterministic tiebreak).
    candidates = []
    skipped = []
    for s in buy_signals:
        ticker = s['ticker']
        score = max(0, float(s['score']))
        weight = score / total_score
        slot_notional = cap * weight
        price = prices.get(ticker)
        if price is None or float(price) <= 0:
            # A BUY with no usable price is an explicit skip, not a silent
            # drop: the UI must see why no position exists for this signal.
            skipped.append({
                'ticker': ticker,
                'signal_action': 'BUY',
                'score': score,
                'weight': round(weight, 6),
                'slot_notional': round(slot_notional, 2),
                'price': None,
                'lot_size': None,
                'lot_cost': None,
                'skip_kind': 'NO_PRICE',
                'reason': 'no latest price in silver.unified_prices',
            })
            continue
        price_f = float(price)
        candidates.append({
            'ticker': ticker,
            'price': price,
            'price_f': price_f,
            'score': score,
            'weight': weight,
            'lot': lot_size_for(ticker, lots),
            'slot_notional': slot_notional,
        })
    candidates.sort(key=lambda c: (-c['score'], c['ticker']))

    # First pass: whole lots per signal in rank order. Signals that cannot
    # afford one lot at their slot capital are skipped EXPLICITLY.
    fillable = []
    freed = 0.0
    for c in candidates:
        lot_cost = c['price_f'] * c['lot']
        shares = math.floor(c['slot_notional'] / lot_cost) * c['lot']
        if shares > 0:
            c['shares'] = shares
            fillable.append(c)
        else:
            freed += c['slot_notional']
            if '=' in c['ticker']:
                # Futures are unit-sized (lot=1) with no contract multiplier
                # in the paper ledger; a zero-size skip on a futures ticker
                # means the asset class is not expressible at this capital.
                skip_kind = 'UNSUPPORTED_ASSET_CLASS'
                reason = ('futures contract sizing unsupported: slot capital '
                          'cannot afford 1 unit and the paper ledger has no '
                          'contract multiplier (fractional contracts disabled)')
            else:
                skip_kind = 'BELOW_ONE_LOT'
                reason = 'below 1 lot at slot capital'
            skipped.append({
                'ticker': c['ticker'],
                'signal_action': 'BUY',
                'score': c['score'],
                'weight': round(c['weight'], 6),
                'slot_notional': round(c['slot_notional'], 2),
                'price': c['price'],
                'lot_size': c['lot'],
                'lot_cost': round(lot_cost, 2),
                'skip_kind': skip_kind,
                'reason': reason,
            })

    # Second pass: redistribute freed slot capital to the remaining fillable
    # signals in proportion to their scores (larger lots).
    if freed > 0 and fillable:
        fill_score_sum = sum(c['score'] for c in fillable)
        for c in fillable:
            extra = freed * (c['score'] / fill_score_sum) if fill_score_sum > 0 else 0
            lot_cost = c['price_f'] * c['lot']
            c['shares'] = math.floor((c['slot_notional'] + extra) / lot_cost) * c['lot']

    # Concentration cap: no single ticker may exceed max_position_pct of
    # assigned capital. Applied BEFORE the residual round-robin so the cap
    # binds on both redistributed slot capital and residual deployment.
    # A ticker capped to zero shares becomes an explicit CONCENTRATION_CAP
    # skip; a ticker capped to a smaller whole-lot position keeps that
    # position AND gets a CONCENTRATION_CAP note so the audit surface shows
    # the residual was not deployed into it.
    cap_enabled = bool(max_position_pct) and max_position_pct > 0
    # Only read when cap_enabled; 0.0 placeholder keeps the type non-optional.
    max_notional = cap * max_position_pct if cap_enabled else 0.0
    cap_noted = set()

    def note_concentration_cap(c, reason):
        if c['ticker'] in cap_noted:
            return
        cap_noted.add(c['ticker'])
        skipped.append({
            'ticker': c['ticker'],
            'signal_action': 'BUY',
            'score': c['score'],
            'weight': round(c['weight'], 6),
            'slot_notional': round(c['slot_notional'], 2),
            'price': c['price'],
            'lot_size': c['lot'],
            'lot_cost': round(c['price_f'] * c['lot'], 2),
            'skip_kind': 'CONCENTRATION_CAP',
            'reason': reason,
        })

    if cap_enabled and fillable:
        still_fillable = []
        for c in fillable:
            lot_cost = c['price_f'] * c['lot']
            max_shares = math.floor((max_notional + 1e-9) / lot_cost) * c['lot']
            if c['shares'] > max_shares:
                capped_notional = max_shares * c['price_f']
                note_concentration_cap(c, (
                    f"position capped at {max_position_pct:.0%} of assigned capital: "
                    f"{c['shares']} -> {max_shares} shares "
                    f"(${c['shares'] * c['price_f']:,.2f} -> ${capped_notional:,.2f}; "
                    f"cap ${max_notional:,.2f})"
                ))
                c['shares'] = max_shares
            if c['shares'] > 0:
                still_fillable.append(c)
        fillable = still_fillable

    # Final pass: deploy residual cash (freed capital + lot-rounding
    # remainders) as extra whole lots, round-robin in rank order, so the
    # budget is fully deployed instead of parking in cash. A ticker whose
    # next lot would breach the concentration cap is skipped and the
    # round-robin tries the next ticker.
    if fillable:
        cash_left = budget - sum(c['shares'] * c['price_f'] for c in fillable)
        while cash_left > 0:
            added = False
            for c in fillable:
                lot_cost = c['price_f'] * c['lot']
                if lot_cost > cash_left + 1e-9:
                    continue
                if cap_enabled and (c['shares'] + c['lot']) * c['price_f'] > max_notional + 1e-9:
                    note_concentration_cap(c, (
                        f"residual cash deployment capped at {max_position_pct:.0%} of "
                        f"assigned capital: next lot ${lot_cost:,.2f} would take "
                        f"{c['ticker']} to ${(c['shares'] + c['lot']) * c['price_f']:,.2f} "
                        f"> cap ${max_notional:,.2f}"
                    ))
                    continue
                c['shares'] += c['lot']
                cash_left -= lot_cost
                added = True
            if not added:
                break

    targets = [{
        'ticker': c['ticker'],
        'price': c['price'],
        'weight': c['weight'],
        'shares': c['shares'],
        'score': c['score'],
    } for c in fillable]
    return targets, skipped


def deployable_budget(signals, capital):
    """Deployable budget for the current signal set.

    Mirrors the budget formula in compute_target (cap * sum BUY scores /
    (sum BUY scores + CASH score)). KEEP IN SYNC with compute_target —
    it owns the canonical sizing; this helper exists so delta mode can
    clamp NEW entries against the budget without re-running full sizing.
    """
    buy_score_sum = sum(max(0, float(s['score'])) for s in signals
                        if s['action'] == 'BUY')
    cash_signal = next((s for s in signals if s['ticker'] == 'CASH'), None)
    total_score = buy_score_sum
    if cash_signal:
        total_score += max(0, float(cash_signal['score']))
    if total_score <= 0:
        return 0.0
    return float(capital) * (buy_score_sum / total_score)


def clamp_new_opens(targets, open_tickers, retained_cost, budget, lots,
                    pend_open_tickers=frozenset()):
    """Delta-mode deployment clamp (2026-09-18, t_5f69e8c0).

    Delta mode preserves existing position sizes, so NEW entries must be
    sized against the budget still uncommitted after retained positions'
    cost basis — not the full sleeve. Without this clamp a fresh BUY
    stacked its whole compute_target slot on top of a near-full book
    (us_stk_sue_mom_01_v2 reached in_market 464.5k vs 400k assigned).

    Pure function. Returns (clamped_targets, extra_skips):
    - targets for tickers already held pass through untouched;
    - targets with a resting pending OPEN pass through untouched but
      consume budget (their settle will deploy that capital);
    - new entries are filled in rank order (compute_target order),
      each floored to whole lots at min(target notional, remaining);
    - a new entry that cannot afford one lot within the remaining budget
      is dropped and reported as an OVER_DEPLOYED skip.

    Known limits: retained_cost uses entry (cost) basis, not mark-to-
    market; NEXT_OPEN fills may gap a few dollars past the cap. Both are
    conservative-vs-honest tradeoffs, not leverage.
    """
    remaining = float(budget) - float(retained_cost)
    clamped = []
    extra_skips = []
    for t in targets:
        tk = t['ticker']
        if tk in open_tickers:
            clamped.append(t)  # retained position; not a new deployment
            continue
        price_f = float(t['price'])
        lot = lot_size_for(tk, lots)
        lot_cost = price_f * lot
        if tk in pend_open_tickers:
            # Resting entry already booked: it will consume budget on
            # settle, so debit it here to avoid double-deploying.
            remaining -= t['shares'] * price_f
            clamped.append(t)
            continue
        alloc = min(t['shares'] * price_f, max(0.0, remaining))
        shares = math.floor((alloc + 1e-9) / lot_cost) * lot
        if shares <= 0:
            extra_skips.append({
                'ticker': tk,
                'signal_action': 'BUY',
                'score': t['score'],
                'weight': round(t['weight'], 6),
                'slot_notional': round(t['shares'] * price_f, 2),
                'price': t['price'],
                'lot_size': lot,
                'lot_cost': round(lot_cost, 2),
                'skip_kind': 'OVER_DEPLOYED',
                'reason': ('no budget left after retained positions: '
                           f'remaining ${max(0.0, remaining):,.2f} of '
                           f'${float(budget):,.2f} deployable (retained cost '
                           f'${float(retained_cost):,.2f}); 1 lot ${lot_cost:,.2f}'),
            })
            continue
        if shares < t['shares']:
            t = dict(t, shares=shares)
        remaining -= shares * price_f
        clamped.append(t)
    return clamped, extra_skips


def close_positions(cur, exit_date, close_ids, close_price, source_date=None, basis=None):
    if not close_ids:
        return 0
    cur.execute(SQL_CLOSE_POSITIONS, (
        exit_date, close_price, source_date, basis,
        close_price, close_price, close_ids
    ))
    return cur.rowcount


def open_new_positions(cur, open_values):
    """open_values rows: (strategy_id, ticker, entry_date, entry_price,
    n_shares, signal_weight, assigned_capital, entry_price_source_date,
    entry_price_basis)."""
    if not open_values:
        return 0
    from psycopg2.extras import execute_values
    execute_values(
        cur, SQL_OPEN_POSITIONS,
        open_values,
        # t_8b58b2bc: open rows carry pnl/pnl_pct NULL until close. A hardcoded
        # 0 made every open row look like a losing closed trade to any reader
        # filtering on `pnl IS NOT NULL` (e.g. the evaluation endpoint),
        # corrupting WR/PF/trade counts (memo 2026-08-17 section 2.3).
        template="(%s, %s, 'LONG', %s, %s, %s, 'open', %s, %s, NULL, NULL, %s, %s, NOW(), NOW())"
    )
    return cur.rowcount


def upsert_signals(cur, signal_values):
    if not signal_values:
        return 0
    from psycopg2.extras import execute_values
    execute_values(
        cur, SQL_UPSERT_SIGNALS,
        signal_values,
        template="(%s, %s, %s, %s, %s, %s, NOW())"
    )
    return cur.rowcount


def write_skips(cur, today, sid, skipped):
    """Persist zero-size BUY skips so the paper book is never silently flat.

    - gold.paper_trade_skip_log: append-only audit of every skip event.
    - consumption.strategy_paper_skips_current: one row per (strategy_id,
      ticker), refreshed each run; the UI reads this to explain why a BUY
      signal has no open paper position. Rows for this strategy are deleted
      first so skips that no longer apply (signal flipped, position now
      fillable) disappear instead of going stale.
    """
    cur.execute(SQL_DELETE_CURRENT_SKIPS, (sid,))
    if not skipped:
        return
    from psycopg2.extras import execute_values
    rows = [(
        sid, sk['ticker'], sk['signal_action'], sk['score'], sk['weight'],
        sk['slot_notional'], sk['price'], sk['lot_size'], sk['lot_cost'],
        sk['skip_kind'], sk['reason'], today,
    ) for sk in skipped]
    execute_values(
        cur, SQL_INSERT_SKIP_LOG, rows,
        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())"
    )
    # The current-skip surface upserts on (strategy_id, ticker): dedupe the
    # batch (first skip wins) so a ticker with two skip kinds in one run
    # cannot raise CardinalityViolation. The audit log above keeps every row.
    seen_tickers = set()
    current_rows = []
    for row in rows:
        if row[1] in seen_tickers:
            continue
        seen_tickers.add(row[1])
        current_rows.append(row)
    execute_values(
        cur, SQL_INSERT_SKIP_CURRENT, current_rows,
        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())"
    )


def rebalance_strategy(cur, today, strategy, prices, signals, open_positions, lots, backfill=False, max_position_pct=0.20, execute_rebalance=True, gate_reason='', convention='NEXT_OPEN', pend_open_tickers=None, pend_close_posids=None, dry_run=False):
    sid = strategy['strategy_id']
    capital = strategy['capital'] or 0
    current_signals = signals.get(sid, [])
    close_map = close_map_of(prices)
    pend_open_tickers = pend_open_tickers or frozenset()
    pend_close_posids = pend_close_posids or frozenset()

    # Map all tickers in universe to current signal state (BUY or HOLD)
    # For signals table, publish every ticker in universe so UI sees HOLD too.
    universe = sorted(set(strategy['universe']))
    score_map = {s['ticker']: s['score'] for s in current_signals}
    action_map = {s['ticker']: s['action'] for s in current_signals}

    # Target positions for BUY tickers only
    # Determine target allocations from the full scoring engine output
    # (including CASH/HOLD), then open only the BUY tickers.
    # Sizing uses the latest CLOSE as the proxy price; the actual fill under
    # NEXT_OPEN happens later at the fill bar's open.
    targets, skipped = compute_target(current_signals, capital, close_map, lots, max_position_pct=max_position_pct)
    buy_signals = [s for s in current_signals if s['action'] == 'BUY']
    target_tickers = {t['ticker'] for t in targets}

    open_by_ticker = open_positions.get(sid, {})
    open_tickers = set(open_by_ticker.keys())

    # Delta-mode deployment clamp (2026-09-18, t_5f69e8c0): existing
    # positions keep their sizes in delta mode, so NEW entries are sized
    # against the budget left after retained positions' cost basis. This
    # keeps sum(open cost basis) <= assigned capital. Backfill closes the
    # whole book first and PAPER_UAT sizes against broker truth, so
    # neither is clamped here.
    if execute_rebalance and not backfill and strategy.get('mode') != 'PAPER_UAT':
        buy_set_pre = {s['ticker'] for s in buy_signals}
        if convention == 'SIGNAL_CLOSE':
            # The SIGNAL_CLOSE branch's same-day round-trip guard keeps
            # today's entries open even when the signal flipped — count
            # them as retained so their cost is not re-deployed.
            retained_tickers = {tk for tk in open_tickers
                                if tk in buy_set_pre
                                or open_by_ticker[tk]['entry_date'] == today}
        else:
            retained_tickers = open_tickers & buy_set_pre
        retained_cost = sum(
            float(open_by_ticker[tk]['n_shares'])
            * float(open_by_ticker[tk]['entry_price'])
            for tk in retained_tickers)
        targets, clamp_skips = clamp_new_opens(
            targets, open_tickers, retained_cost,
            deployable_budget(current_signals, capital), lots,
            pend_open_tickers=pend_open_tickers)
        skipped.extend(clamp_skips)

    # Cadence gate (t_68b07c59): on non-rebalance days no positions are
    # opened or closed. New BUY targets that would have opened are surfaced
    # as CADENCE_GATE skips so the UI/audit can explain why a fresh BUY
    # signal has no position until the next rebalance date. Held positions
    # (including tickers whose signal flipped HOLD mid-period) are left
    # untouched; deferred exits are logged to stdout only.
    if not execute_rebalance:
        # A target that already produced a sizing skip (e.g. CONCENTRATION_CAP)
        # must not ALSO get a CADENCE_GATE row: the skip-current upsert keys on
        # (strategy_id, ticker) and duplicate keys in one batch raise
        # CardinalityViolation.
        already_skipped = {sk['ticker'] for sk in skipped}
        gated_new = [t for t in targets if t['ticker'] not in open_tickers
                     and t['ticker'] not in already_skipped]
        for t in gated_new:
            skipped.append({
                'ticker': t['ticker'],
                'signal_action': 'BUY',
                'score': t['score'],
                'weight': round(t['weight'], 6),
                'slot_notional': round(float(capital) * t['weight'], 2),
                'price': t['price'],
                'lot_size': lot_size_for(t['ticker'], lots),
                'lot_cost': round(float(t['price']) * lot_size_for(t['ticker'], lots), 2),
                'skip_kind': 'CADENCE_GATE',
                'reason': f"entry deferred by cadence gate ({gate_reason})",
            })
        buy_set = {s['ticker'] for s in buy_signals}
        deferred_exits = sorted(t for t in open_tickers if t not in buy_set
                                and open_by_ticker[t]['entry_date'] != today)
        print(f"  {sid}: CADENCE GATE active ({gate_reason}) - signals published, "
              f"positions unchanged ({len(gated_new)} entries deferred"
              + (f", {len(deferred_exits)} exits deferred: {', '.join(deferred_exits)}"
                 if deferred_exits else "") + ")")

    # Explicit skip surface: a BUY signal that cannot be sized is never
    # silently dropped. Every skip is printed, appended to
    # gold.paper_trade_skip_log (audit) and refreshed in
    # consumption.strategy_paper_skips_current (UI surface) so the frontend
    # can render why the paper book is flat for this signal. Freed slot
    # capital was already redistributed to the fillable signals by
    # compute_target.
    for sk in skipped:
        if sk['skip_kind'] == 'NO_PRICE':
            print(f"  {sid}: SKIP {sk['ticker']} [NO_PRICE] - {sk['reason']} "
                  f"(slot ${sk['slot_notional']:,.2f} undeployable)")
        elif sk['skip_kind'] in ('CONCENTRATION_CAP', 'CADENCE_GATE', 'OVER_DEPLOYED'):
            print(f"  {sid}: SKIP {sk['ticker']} [{sk['skip_kind']}] - {sk['reason']}")
        else:
            print(f"  {sid}: SKIP {sk['ticker']} [{sk['skip_kind']}] - {sk['reason']} "
                  f"(slot ${sk['slot_notional']:,.2f} < 1 lot ${sk['lot_cost']:,.2f})")
    write_skips(cur, today, sid, skipped)

    close_count = 0
    open_count = 0
    booked_open = 0
    booked_close = 0
    uat_error = None  # deferred PAPER_UAT hard-fail (raised after signal publish)
    if execute_rebalance:
        if strategy.get('mode') == 'PAPER_UAT':
            # PAPER_UAT firing contract (t_b64f7302): order deltas go to the
            # UAT session via the backend place-order endpoint; the DB paper
            # ledger is NEVER written for this mode. Broker session state is
            # the source of truth for what is held/working. Any failure
            # raises PaperUatFireError -> hard fail, no ledger fallback.
            # NOTE: `backfill` is deliberately ignored here — a DB-side
            # backfill must never translate into mass broker sells.
            # On fire failure the exception is DEFERRED until after signal
            # publication below (qr_etl owns signal state even when the
            # broker session is down), then re-raised as the hard fail.
            uat_error = None
            try:
                uat_held = fetch_uat_positions()          # raises when disconnected
                uat_working = fetch_uat_working_orders()  # raises when disconnected
            except PaperUatFireError as e:
                uat_error = e
                uat_held, uat_working = {}, set()
            if uat_error is None:
                held_uat = {t for t, q in uat_held.items() if q > 0}
                buy_set = {s['ticker'] for s in buy_signals}

                # Exits: UAT-held tickers in THIS strategy's universe that dropped
                # out of the BUY set. The universe restriction means a strategy
                # can only exit tickers it could itself have bought (account-level
                # UAT state caveat documented in the module header).
                fired_sells = set()
                for t in sorted(t for t in (held_uat & set(universe)) if t not in buy_set):
                    if (t, 'SELL') in uat_working:
                        print(f"  {sid}: PAPER_UAT exit {t} already working at UAT - not re-firing")
                        continue
                    fire_paper_uat_order(sid, t, 'SELL', uat_held[t], dry_run=dry_run)
                    fired_sells.add(t)
                    close_count += 1
                    if not dry_run:
                        print(f"  {sid}: FIRED PAPER_UAT SELL {t} x{int(uat_held[t])} "
                              f"(orderRef=strat:{sid})")

                # Entries: sized BUY targets not held at UAT and not resting.
                held_after = held_uat - fired_sells
                open_seen = set()
                for t in targets:
                    tk = t['ticker']
                    if tk in held_after or tk in open_seen:
                        continue
                    open_seen.add(tk)
                    if (tk, 'BUY') in uat_working:
                        print(f"  {sid}: PAPER_UAT entry {tk} already working at UAT - not re-firing")
                        continue
                    fire_paper_uat_order(sid, tk, 'BUY', t['shares'], dry_run=dry_run)
                    open_count += 1
                    if not dry_run:
                        print(f"  {sid}: FIRED PAPER_UAT BUY {tk} x{t['shares']} "
                              f"(weight {t['weight'] * 100:.2f}%, orderRef=strat:{sid})")
        elif backfill:
            # Close ALL existing positions, then open the target ones fresh
            to_close = open_tickers
        else:
            # Close positions whose ticker dropped out of the BUY set.
            # 2026-08-13 (t_84d61124): previously this closed open_tickers -
            # target_tickers, which also closed positions whose BUY signal was
            # merely UNSIZED today (BELOW_ONE_LOT / NO_PRICE / cap-to-zero) —
            # e.g. etf_comm_trend_basket_15 GLD: 1 lot crossed above the slot
            # after a +4.1% day, the position was closed mid-month with no
            # signal change, and the slot could never re-afford the lot. That
            # violates the engine contract ("sells when the ticker drops out of
            # the BUY set"). A BUY that cannot be sized is still a BUY: keep
            # the existing position; sizing skips only gate NEW opens.
            buy_tickers = {s['ticker'] for s in buy_signals}
            to_close = open_tickers - buy_tickers

        if strategy.get('mode') == 'PAPER_UAT':
            pass  # order deltas already fired to the UAT session above;
                  # no DB ledger path (NEXT_OPEN/SIGNAL_CLOSE) applies.
        elif convention == 'SIGNAL_CLOSE':
            # Immediate fill at the signal-date close (the latest bar's
            # close), honestly stamped: entry/exit_date = the bar date of the
            # close used, basis SIGNAL_CLOSE. For strategies that declare
            # close-of-signal-date execution.
            # Same-day round-trip guard: a close on the entry bar would be a
            # $0-PnL same-price artifact from a double run.
            to_close = {t for t in to_close if open_by_ticker[t]['entry_date'] != today}
            for t in sorted(to_close):
                pos = open_by_ticker[t]
                bar = prices.get(t)
                cprice = bar['close'] if bar else pos['entry_price']
                cdate = bar['date'] if bar else None
                close_count += close_positions(
                    cur, cdate or today, [pos['id']], cprice,
                    source_date=cdate, basis='SIGNAL_CLOSE')

            # Open positions for targets not currently held
            held_tickers = open_tickers - to_close
            to_open = [t for t in targets if t['ticker'] not in held_tickers]

            open_values = []
            open_seen = set()
            for t in to_open:
                if t['ticker'] in open_seen:
                    continue
                open_seen.add(t['ticker'])
                bar = prices.get(t['ticker'])
                open_values.append((
                    sid, t['ticker'], bar['date'], t['price'], t['shares'],
                    round(t['weight'] * 100, 4), capital,
                    bar['date'], 'SIGNAL_CLOSE'
                ))
            open_count = open_new_positions(cur, open_values)
        else:
            # NEXT_OPEN (default, t_3454cc76): book DEFERRED orders. The
            # signal was computed from the latest bar's close (signal_date =
            # that bar's date); the order fills at the OPEN of the first bar
            # after it, settled by a later run's settle step. No same-day
            # guard needed: the fill is always a later bar than the signal.
            def _signal_bar(t):
                bar = prices.get(t)
                return bar['date'] if bar else today

            for t in sorted(to_close):
                pos = open_by_ticker[t]
                if pos['id'] in pend_close_posids:
                    continue  # resting exit already booked for this position
                booked_close += queue_pending_orders(cur, [(
                    sid, t, 'CLOSE', _signal_bar(t), pos['id'],
                    None, None, None, None
                )])
                print(f"  {sid}: BOOKED pending CLOSE {t} "
                      f"(signal {_signal_bar(t)}, fills at next open)")

            # Book entries for targets not currently held and not already
            # resting as a pending order.
            held_tickers = open_tickers - to_close
            open_seen = set()
            rows = []
            for t in targets:
                tk = t['ticker']
                if tk in held_tickers or tk in pend_open_tickers or tk in open_seen:
                    continue
                open_seen.add(tk)
                rows.append((
                    sid, tk, 'OPEN', _signal_bar(tk), None, t['shares'],
                    round(t['weight'] * 100, 4), capital, t['score']
                ))
                print(f"  {sid}: BOOKED pending OPEN {tk} x{t['shares']} "
                      f"(signal {_signal_bar(tk)}, fills at next open)")
            booked_open = queue_pending_orders(cur, rows)

    # Publish signals for every universe ticker (BUY or HOLD)
    signal_values = []
    for ticker in universe:
        action = action_map.get(ticker, 'HOLD')
        score = score_map.get(ticker, 0)
        price = close_map.get(ticker)
        signal_values.append((
            sid, ticker, action,
            round(float(score) / 100.0, 4),  # signal_strength
            round(float(score) / 100.0, 4),  # confidence_score
            price
        ))

    # Publish CASH explicitly if present in the scoring engine (not in universe).
    if 'CASH' in score_map and 'CASH' not in universe:
        signal_values.append((
            sid, 'CASH', action_map.get('CASH', 'HOLD'),
            round(float(score_map['CASH']) / 100.0, 4),
            round(float(score_map['CASH']) / 100.0, 4),
            None
        ))

    upsert_signals(cur, signal_values)
    # Keep the canonical win_rate copy in sync with the registry (t_bc9e8d3c).
    cur.execute(SQL_REFRESH_SIGNAL_WIN_RATE, (sid,))

    if uat_error is not None:
        # Deferred PAPER_UAT hard fail: signals are published above (qr_etl
        # owns signal state), now abort the firing pass — run() catches this,
        # logs loudly, and exits non-zero. No DB-ledger fallback, ever.
        raise uat_error

    return {
        'strategy_id': sid,
        'closed': close_count,
        'opened': open_count,
        'booked_open': booked_open,
        'booked_close': booked_close,
        'signals_published': len(signal_values),
        'skipped': skipped,
        'rebalanced': execute_rebalance,
    }


def run(backfill=False, strategy_id=None, date_str=None, max_position_pct=0.20,
        force_rebalance=False, dry_run=False):
    today = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now(timezone.utc).date()
    conn = get_connection()
    cur = None
    try:
        conn.autocommit = False
        cur = conn.cursor()

        ensure_constraints(cur)
        ensure_skip_tables(cur)
        ensure_rebalance_state_table(cur)
        ensure_pending_tables(cur)

        if backfill:
            if strategy_id:
                cur.execute("SELECT COALESCE(disable_paper_rebuild, FALSE) FROM gold.strategy_registry WHERE strategy_id = %s", (strategy_id,))
                row = cur.fetchone()
                if row and row[0]:
                    print(f"Backfill requested for {strategy_id}, but disable_paper_rebuild is TRUE. Skipping.")
                    conn.commit()
                    return
                print(f"Backfill mode: clearing rows for {strategy_id}")
                cur.execute("DELETE FROM gold.paper_trades_synthetic WHERE strategy_id = %s", (strategy_id,))
                cur.execute("DELETE FROM consumption.strategies_signals_current WHERE strategy_id = %s", (strategy_id,))
                cur.execute("DELETE FROM gold.paper_trade_skip_log WHERE strategy_id = %s", (strategy_id,))
                cur.execute("DELETE FROM consumption.strategy_paper_skips_current WHERE strategy_id = %s", (strategy_id,))
                cur.execute("DELETE FROM gold.paper_pending_orders WHERE strategy_id = %s", (strategy_id,))
                cur.execute("DELETE FROM consumption.strategy_paper_pending_current WHERE strategy_id = %s", (strategy_id,))
            else:
                print("Backfill mode: clearing stale paper_trades_synthetic and strategies_signals_current")
                cur.execute(SQL_TRUNCATE_STALE)
                cur.execute("TRUNCATE TABLE gold.paper_trade_skip_log, consumption.strategy_paper_skips_current")
                cur.execute("TRUNCATE TABLE gold.paper_pending_orders, consumption.strategy_paper_pending_current")

        strategies = fetch_active_strategies(cur)
        if strategy_id:
            strategies = [s for s in strategies if s['strategy_id'] == strategy_id]
            if not strategies:
                print(f"Strategy {strategy_id} not found in active PAPER/SIMULATION/PAPER_UAT strategies. Nothing to do.")
                conn.commit()
                return 0

        strategy_ids = [s['strategy_id'] for s in strategies]

        if not strategies:
            print("No active PAPER/SIMULATION/PAPER_UAT strategies with universe. Nothing to do.")
            conn.commit()
            return 0

        uat_sids = [s['strategy_id'] for s in strategies if s.get('mode') == 'PAPER_UAT']
        if len(uat_sids) > 1:
            print(f"WARNING: {len(uat_sids)} PAPER_UAT strategies active {uat_sids} — UAT "
                  f"positions/open-orders are ACCOUNT-LEVEL aggregates; delta firing assumes "
                  f"one strategy per UAT book until the Phase 4 attribution mirror lands.")

        all_tickers = list({t for s in strategies for t in s['universe']})
        prices = fetch_prices(cur, all_tickers)
        lots = fetch_lot_sizes(cur, all_tickers)
        signals = fetch_scores(cur, strategy_ids)

        # Settle deferred NEXT_OPEN orders FIRST (t_3454cc76): fills booked
        # by earlier runs execute at the open of the first bar after their
        # signal bar, and the resulting positions must be visible to the
        # rebalance logic below.
        settle = settle_pending_orders(cur, today, strategy_ids)
        if settle['filled_open'] or settle['filled_close'] or settle['waiting']:
            print(f"Settle: filled {settle['filled_open']} opens / "
                  f"{settle['filled_close']} closes; {settle['waiting']} orders resting")

        open_positions = fetch_open_positions(cur, strategy_ids)
        cap_overrides = fetch_cap_overrides(cur, strategy_ids)
        paper_designs = fetch_paper_designs(cur, strategy_ids)
        fill_conventions = fetch_fill_conventions(cur, strategy_ids)
        pend_open_map, pend_close_posids = fetch_pending_maps(cur, strategy_ids)
        rebalance_state = fetch_rebalance_state(cur, strategy_ids)

        # Declared residual-cash policy (t_ee1ab601): surfaced every run so
        # operators never have to read compute_target to learn what happens
        # to undeployed capital. The same policy string is stored per
        # strategy in gold.strategy_configs (config_key='paper_design').
        print("Residual-cash policy (declared): freed slot capital is "
              "redistributed pro-rata by score to fillable BUYs; residual "
              "cash is then deployed round-robin in rank order as whole lots "
              "bounded by the concentration cap; any undeployable remainder "
              "parks in cash.")

        results = []
        gated_count = 0
        uat_failures = 0
        for strategy in strategies:
            sid = strategy['strategy_id']
            # Cap resolution (t_ee1ab601): the cap is never a silent global
            # default anymore — its source is resolved and logged per strategy.
            eff_pct, cap_source = resolve_cap_with_source(
                cap_overrides, paper_designs, sid, max_position_pct)
            if cap_source == 'override':
                print(f"  {sid}: per-strategy concentration cap override "
                      f"{eff_pct:.0%} (gold.strategy_configs max_position_pct; "
                      f"global default {max_position_pct:.0%})")
            elif cap_source == 'design':
                print(f"  {sid}: concentration cap {eff_pct:.0%} derived from "
                      f"declared design (gold.strategy_configs paper_design; "
                      f"global default {max_position_pct:.0%})")
            elif cap_source == 'declared_fallback':
                print(f"  {sid}: no design cap declared (paper_design present); "
                      f"using global default {eff_pct:.0%} — declared fallback")
            else:
                print(f"  {sid}: WARNING no paper_design row; concentration cap "
                      f"falls back to global default {eff_pct:.0%} (undeclared)")

            # Cadence gate (t_68b07c59): daily/event strategies always
            # execute; weekly/monthly strategies only mutate positions on
            # the first run of a new period (or under an explicit override).
            execute = True
            gate_reason = ''
            if is_gated_frequency(strategy.get('frequency')):
                freq = normalize_frequency(strategy['frequency'])
                execute, period_key, gate_reason = decide_rebalance(
                    freq, today, rebalance_state.get(sid),
                    backfill=backfill, force_rebalance=force_rebalance)
                if rebalance_state.get(sid) is None:
                    # First run under the gate: seed the current period so a
                    # pre-gate book is never surprise-rebalanced mid-period.
                    cur.execute(SQL_SEED_REBALANCE_STATE, (sid, freq, period_key))
                    print(f"  {sid}: cadence gate seeded ({freq}, period {period_key})")
                if execute:
                    cur.execute(SQL_TOUCH_REBALANCE_STATE, (sid, freq, period_key, today))
                    print(f"  {sid}: REBALANCE DATE ({freq}: {gate_reason})")
                else:
                    gated_count += 1

            try:
                res = rebalance_strategy(cur, today, strategy, prices, signals,
                                         open_positions, lots, backfill=backfill,
                                         max_position_pct=eff_pct,
                                         execute_rebalance=execute,
                                         gate_reason=gate_reason,
                                         convention=resolve_fill_convention(fill_conventions, sid),
                                         pend_open_tickers=pend_open_map.get(sid, frozenset()),
                                         pend_close_posids=pend_close_posids,
                                         dry_run=dry_run)
            except PaperUatFireError as e:
                # PAPER_UAT hard fail (t_b64f7302): the strategy does NOT fire
                # this run and NOTHING falls back to the DB paper ledger.
                # Signals for the run were still published (qr_etl owns signal
                # state; the broker owns order state — the raise is deferred
                # until after upsert_signals inside rebalance_strategy).
                # Loud surface: per-strategy log + summary + non-zero exit.
                uat_failures += 1
                print(f"  {sid}: PAPER_UAT FIRE FAILED — {e}")
                print(f"  {sid}: no orders fired, no DB-ledger fallback "
                      f"(signals still published). "
                      f"Check UAT session (POST /api/ib/tws/uat/connect) and re-run.")
                res = {'strategy_id': sid, 'closed': 0, 'opened': 0,
                       'booked_open': 0, 'booked_close': 0,
                       'signals_published': 0, 'skipped': [],
                       'rebalanced': False, 'uat_failed': True}
            results.append(res)
            refresh_pending_mirror(cur, sid)
            if sid in fill_conventions:
                print(f"  {sid}: fill convention override "
                      f"{fill_conventions[sid]} (gold.strategy_configs fill_convention)")

        if not strategy_id:
            # Full run: drop current-skip rows for strategies no longer in the
            # active rebuild set (retired / disabled) so the UI surface stays
            # in sync with the live registry.
            cur.execute(SQL_DELETE_STALE_CURRENT_SKIPS, (strategy_ids,))
            if cur.rowcount:
                print(f"  Removed {cur.rowcount} stale skip rows for strategies no longer active")
            # Same hygiene for deferred orders: cancel resting orders of
            # strategies no longer active and drop their mirror rows.
            cur.execute(SQL_CANCEL_PENDING_INACTIVE, (strategy_ids,))
            if cur.rowcount:
                print(f"  Cancelled {cur.rowcount} pending orders for strategies no longer active")
            cur.execute(SQL_DELETE_PENDING_MIRROR_STALE, (strategy_ids,))

        if dry_run:
            conn.rollback()
            print("DRY RUN: all changes rolled back (no commits).")
        else:
            conn.commit()

        print("Rebalancer results:")
        for r in results:
            skipped_desc = [f"{s['ticker']}[{s['skip_kind']}]" for s in r.get('skipped', [])]
            print(f"  {r['strategy_id']}: closed={r['closed']} opened={r['opened']} "
                  f"booked_open={r.get('booked_open', 0)} booked_close={r.get('booked_close', 0)} "
                  f"signals={r['signals_published']} skipped={len(skipped_desc)}"
                  f" rebalanced={'yes' if r.get('rebalanced', True) else 'NO (cadence gate)'}"
                  + (" UAT_FIRE_FAILED" if r.get('uat_failed') else "")
                  + (f" ({', '.join(skipped_desc)})" if skipped_desc else ""))
        print(f"Total active strategies processed: {len(results)} "
              f"({gated_count} position-gated by cadence, signals still published)")
        if uat_failures:
            print(f"PAPER_UAT: {uat_failures} strateg(y/ies) FAILED to fire "
                  f"(hard fail, no DB-ledger fallback) — exiting non-zero.")
        return uat_failures

    except Exception as e:
        conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generic paper position rebalancer")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Truncate stale paper/signal tables and rebuild current state from scratch"
    )
    parser.add_argument(
        "--strategy-id",
        type=str,
        default=None,
        help="Only rebalance this strategy_id (default: all active PAPER/SIMULATION strategies)"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Use this date (YYYY-MM-DD) as the rebalance date instead of today"
    )
    parser.add_argument(
        "--max-position-pct",
        type=float,
        default=0.20,
        help="Max single-position notional as a fraction of assigned capital "
             "(default: 0.20). Caps sizing and residual-cash round-robin "
             "deployment; breaches are logged as CONCENTRATION_CAP skips. "
             "Per-strategy precedence: explicit gold.strategy_configs "
             "override (config_key='max_position_pct') > design-derived cap "
             "(config_key='paper_design' design_max_position_pct) > this "
             "global default; the source used is logged per strategy "
             "(t_ee1ab601). "
             "Set 0 to disable."
    )
    parser.add_argument(
        "--force-rebalance",
        action="store_true",
        help="Bypass the cadence gate: execute position mutations for "
             "weekly/monthly strategies even outside a rebalance date, and "
             "advance their rebalance state to the current period."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline logic but roll back every DB change "
             "(no commits) and fire NO PAPER_UAT broker orders (would-be "
             "orders are printed). Use to preview gate decisions and trades."
    )
    args = parser.parse_args()
    uat_failures = run(backfill=args.backfill, strategy_id=args.strategy_id, date_str=args.date,
        max_position_pct=args.max_position_pct,
        force_rebalance=args.force_rebalance, dry_run=args.dry_run)
    sys.exit(1 if uat_failures else 0)
