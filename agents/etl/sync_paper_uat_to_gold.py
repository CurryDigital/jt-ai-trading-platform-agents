#!/usr/bin/env python3
"""
sync_paper_uat_to_gold.py
=========================
Mirror the IBKR PAPER_UAT broker session into gold (kanban t_db5ffc20,
Phase 4 of PAPER_UAT; decision: agents/etl/docs/PAPER_UAT_MIRROR_DECISION.md).

Source of truth = the dedicated UAT paper session (account DUP825942,
127.0.0.1:14002 client 2), reached ONLY through the backend UAT endpoints:

    GET /api/ib/tws/uat/positions
    GET /api/ib/tws/uat/open-orders
    GET /api/ib/tws/uat/fills

Targets (separate mirror tables — never gold.paper_trades*):
    gold.paper_uat_fills        append-only, upsert on (account, exec_id)
    gold.paper_uat_positions    point-in-time snapshot, refreshed whole
    gold.paper_uat_open_orders  point-in-time snapshot, refreshed whole
    gold.manual_orders          paper_uat blotter: one row per UAT fill
                                (book='paper_uat', order_id='uat-<exec_id>')

Blotter reconciliation (kanban t_51368ec4): the backend close-position
endpoint books gold.manual_orders ONLY when the order reaches synchronous
Filled inside the request's wait window. Orders that are PreSubmitted/queued
and fill later (next open, no waiter) never get booked by the backend — this
reconciler closes that gap by booking every UAT execution returned by
ib.fills(). Idempotent: deterministic order_id 'uat-<exec_id>' +
ON CONFLICT DO NOTHING, plus a note-scan so fills the backend already booked
synchronously (note contains 'ib_order <id>') are not double-booked.
Requires migration 2026-08-25_manual_orders_paper_uat_book.sql (widened
book/side CHECKs); without it every paper_uat blotter insert is rejected.

Attribution: fills carry order_ref = 'strat:<strategy_id>' (rebalancer firing
contract); strategy_id = substring(order_ref from '^strat:(.+)$'). Unmatched
refs are stored with strategy_id NULL and reported as UNATTRIBUTED.

HARD-FAIL contract: when the UAT session is disconnected (connected=false /
data=null on ANY endpoint) or the backend is unreachable, this script exits 1
and writes NOTHING (snapshots are never truncated against unknown state). It
NEVER reads the primary/live session as a substitute. run_stage.py records the
non-zero exit in the pipeline state — the failure is visible in the manifest.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SG_TZ = timezone(timedelta(hours=8))  # gold.manual_orders.created_at convention

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection

PAPER_UAT_API_BASE = os.environ.get('PAPER_UAT_API_BASE', 'http://127.0.0.1:8000')
PAPER_UAT_HTTP_TIMEOUT = float(os.environ.get('PAPER_UAT_HTTP_TIMEOUT', '15'))

STRAT_REF_RE = re.compile(r'^strat:(.+)$')
# OPS_RECON covers placed via the guarded backend route carry
# order_ref='RECON_FLATTEN_<task_id>' (kanban t_a374fbeb). They are
# user-approved account-management orders; attribute them to the OPS_RECON
# pseudo-strategy instead of leaving strategy_id NULL (UNATTRIBUTED).
OPS_RECON_REF_RE = re.compile(r'^RECON_FLATTEN_[A-Za-z0-9_\-]+$')


class PaperUatSyncError(RuntimeError):
    """Hard failure of the PAPER_UAT mirror sync. No partial writes, no
    fallback to the primary/live session — the run simply fails visibly."""


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
        raise PaperUatSyncError(f"{method} {path} -> HTTP {e.code}: {body}")
    except PaperUatSyncError:
        raise
    except Exception as e:
        raise PaperUatSyncError(f"{method} {path} failed: {e}")


def _fetch_uat(path):
    """Fetch one UAT endpoint; hard-fail unless connected with data present.
    An empty list is a valid connected response (genuinely flat / no fills)."""
    r = _uat_http('GET', path)
    if not r.get('connected') or r.get('data') is None:
        raise PaperUatSyncError(
            f"UAT session not connected ({path}): "
            f"{r.get('message') or r.get('error') or 'connected=false'}")
    return r


def attribute_strategy(order_ref):
    """'strat:<strategy_id>' -> strategy_id; 'RECON_FLATTEN_<task_id>' ->
    'OPS_RECON'; anything else -> None (never fabricate attribution)."""
    if not order_ref:
        return None
    m = STRAT_REF_RE.match(str(order_ref))
    if m:
        return m.group(1)
    if OPS_RECON_REF_RE.match(str(order_ref)):
        return 'OPS_RECON'
    return None


def sync_fills(conn, fills, as_of, dry_run=False):
    """Append-only upsert of UAT executions. Returns (rows, unattributed)."""
    rows = []
    for f in fills:
        ref = f.get('order_ref')
        side = (f.get('side') or '').upper()
        # defensive: backend already maps BOT/SLD, never let a raw IBKR side
        # violate the gold.paper_uat_fills side CHECK
        side = {'BOT': 'BUY', 'SLD': 'SELL'}.get(side, side)
        rows.append((
            f.get('account') or 'UNKNOWN',
            str(f.get('exec_id')),
            f.get('order_id'),
            f.get('perm_id'),
            ref,
            attribute_strategy(ref),
            f.get('symbol'),
            f.get('local_symbol'),
            side,
            f.get('qty'),
            f.get('price'),
            f.get('currency'),
            f.get('time'),
            as_of,
        ))
    unattributed = sum(1 for r in rows if r[5] is None)

    if dry_run:
        print(f"[DRY-RUN] Would upsert {len(rows)} fills "
              f"({unattributed} unattributed)")
        for r in rows:
            print(f"  {r[8]} {r[6]} x{r[9]} @ {r[10]} "
                  f"ref={r[4]!r} -> strategy_id={r[5]!r}")
        return len(rows), unattributed

    cur = conn.cursor()
    for r in rows:
        cur.execute("""
            INSERT INTO gold.paper_uat_fills
                (account, exec_id, order_id, perm_id, order_ref, strategy_id,
                 symbol, local_symbol, side, qty, price, currency,
                 fill_time, as_of)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account, exec_id) DO NOTHING;
        """, r)
    conn.commit()
    print(f"Synced {len(rows)} fills ({unattributed} unattributed)")
    return len(rows), unattributed


IB_ORDER_NOTE_RE = re.compile(r'ib_order (\d+)')


def blotter_order_id(exec_id):
    """Deterministic manual_orders.order_id for a reconciled UAT fill.
    Column is varchar(32): 'uat-' + exec_id (<= 28 chars observed)."""
    return ('uat-' + str(exec_id))[:32]


def _fill_time_sg(time_str):
    """ISO fill time -> naive +08:00 timestamp, matching the
    gold.manual_orders.created_at convention (UTC+8 wall clock)."""
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(str(time_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(SG_TZ).replace(tzinfo=None)
    except ValueError:
        return None


def sync_manual_orders(conn, fills, dry_run=False):
    """Reconcile UAT executions into the paper_uat blotter
    (gold.manual_orders, book='paper_uat').

    The backend close-position endpoint only books on synchronous Filled;
    fills that complete asynchronously (queued at close, filled at next open)
    are booked HERE. Idempotent: deterministic order_id + ON CONFLICT, and a
    note-scan skips fills the backend already booked synchronously.

    Returns (booked, skipped_existing, skipped_invalid).
    """
    cur = conn.cursor()
    booked_notes = []
    if not dry_run:
        cur.execute(
            "SELECT ticker, note FROM gold.manual_orders "
            "WHERE book = 'paper_uat' AND note IS NOT NULL;")
        booked_notes = cur.fetchall()
    # (ticker, ib order_id) pairs the backend already booked synchronously
    already = set()
    for ticker, note in booked_notes:
        m = IB_ORDER_NOTE_RE.search(note or '')
        if m:
            already.add((ticker, int(m.group(1))))

    booked = skipped_existing = skipped_invalid = 0
    for f in fills:
        exec_id = f.get('exec_id')
        side = (f.get('side') or '').upper()
        side = {'BOT': 'BUY', 'SLD': 'SELL'}.get(side, side)
        symbol = f.get('symbol')
        qty = f.get('qty')
        if not exec_id or not symbol or side not in ('BUY', 'SELL') \
                or not qty or float(qty) <= 0:
            skipped_invalid += 1
            print(f"  SKIP invalid fill row: {f}")
            continue
        if (symbol, f.get('order_id')) in already:
            skipped_existing += 1
            continue
        currency = f.get('currency')
        market = 'HK' if currency == 'HKD' else 'US'
        order_id = blotter_order_id(exec_id)
        # Include the UTC fill time in the note: created_at follows the
        # gold.manual_orders +08:00 wall-clock convention and has been misread
        # as UTC/after-close before (kanban t_117677e7). The note is the
        # human-facing provenance string, so it must carry unambiguous time.
        fill_utc = str(f.get('time') or '')[:19].replace('T', ' ')
        note = (f"IBKR UAT fill · exec {exec_id} · "
                f"ib_order {f.get('order_id')} · acct "
                f"{f.get('account') or 'UNKNOWN'}"
                f"{f' · {fill_utc}Z' if fill_utc else ''}")[:200]
        created_at = _fill_time_sg(f.get('time'))
        params = (order_id, 'paper_uat', symbol, market, 'STOCK', side,
                  float(qty), f.get('price'), note, created_at)
        if dry_run:
            print(f"[DRY-RUN] Would book blotter {order_id}: {side} "
                  f"{symbol} x{qty} @ {f.get('price')} ({market})")
        else:
            cur.execute("""
                INSERT INTO gold.manual_orders
                    (order_id, book, ticker, market, asset_class, side, qty,
                     entry_price, limit_price, status, note, created_by,
                     created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, 'filled', %s,
                        'etl_reconciler', COALESCE(%s, CURRENT_TIMESTAMP AT TIME ZONE 'UTC' + INTERVAL '8 hours'))
                ON CONFLICT (order_id) DO NOTHING;
            """, params)
            if getattr(cur, 'rowcount', 1):
                booked += 1
            else:
                skipped_existing += 1  # conflict: this exec_id already booked
    if not dry_run:
        conn.commit()
    print(f"Blotter: {booked} booked, {skipped_existing} already booked by "
          f"backend, {skipped_invalid} invalid skipped")
    return booked, skipped_existing, skipped_invalid


def sync_positions(conn, positions, as_of, dry_run=False):
    """Point-in-time snapshot, refreshed whole."""
    if dry_run:
        print(f"[DRY-RUN] Would refresh {len(positions)} UAT positions")
        for p in positions:
            print(f"  {p.get('ticker')}: qty={p.get('qty')} "
                  f"avg={p.get('avg_cost')} px={p.get('market_price')}")
        return len(positions)

    cur = conn.cursor()
    cur.execute("TRUNCATE gold.paper_uat_positions;")
    for p in positions:
        cur.execute("""
            INSERT INTO gold.paper_uat_positions
                (account, ticker, symbol, sec_type, exchange, currency, qty,
                 avg_cost, market_price, market_value, unrealized_pnl,
                 realized_pnl, as_of)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, (
            p.get('account') or 'UNKNOWN',
            p.get('ticker') or p.get('symbol'),
            p.get('symbol'),
            p.get('sec_type'),
            p.get('exchange'),
            p.get('currency'),
            p.get('qty'),
            p.get('avg_cost'),
            p.get('market_price'),
            p.get('market_value'),
            p.get('unrealized_pnl'),
            p.get('realized_pnl'),
            as_of,
        ))
    conn.commit()
    print(f"Synced {len(positions)} positions")
    return len(positions)


def sync_open_orders(conn, orders, as_of, dry_run=False):
    """Point-in-time snapshot, refreshed whole."""
    if dry_run:
        print(f"[DRY-RUN] Would refresh {len(orders)} UAT open orders")
        for o in orders:
            print(f"  order {o.get('order_id')}: {o.get('action')} "
                  f"{o.get('symbol')} x{o.get('qty')} ({o.get('status')})")
        return len(orders)

    cur = conn.cursor()
    cur.execute("TRUNCATE gold.paper_uat_open_orders;")
    for o in orders:
        cur.execute("""
            INSERT INTO gold.paper_uat_open_orders
                (account, order_id, perm_id, symbol, local_symbol, action,
                 qty, order_type, status, filled, remaining, as_of)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, (
            o.get('account') or 'UNKNOWN',
            o.get('order_id'),
            o.get('perm_id'),
            o.get('symbol'),
            o.get('local_symbol'),
            (o.get('action') or '').upper(),
            o.get('qty'),
            o.get('order_type'),
            o.get('status'),
            o.get('filled'),
            o.get('remaining'),
            as_of,
        ))
    conn.commit()
    print(f"Synced {len(orders)} open orders")
    return len(orders)


def main():
    parser = argparse.ArgumentParser(description='Sync IBKR UAT session to gold mirror tables')
    parser.add_argument('--dry-run', action='store_true',
                        help='Fetch and print what would be synced; no writes')
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"PAPER_UAT Session -> Gold Mirror Sync")
    print(f"{'='*60}")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Backend: {PAPER_UAT_API_BASE}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print()

    try:
        # Fetch ALL endpoints first: hard-fail before touching any table, so a
        # disconnected session never truncates the snapshots.
        r_pos = _fetch_uat('/api/ib/tws/uat/positions')
        r_ord = _fetch_uat('/api/ib/tws/uat/open-orders')
        r_fill = _fetch_uat('/api/ib/tws/uat/fills')
        account = r_pos.get('account') or r_fill.get('account') or 'UNKNOWN'
        print(f"UAT session connected: account={account}")
    except PaperUatSyncError as e:
        print(f"HARD FAIL: {e}")
        print("PAPER_UAT mirror NOT refreshed; never falling back to the "
              "primary/live session. Connect with POST /api/ib/tws/uat/connect.")
        # Record the FAILED attempt so the registry guard can tell a down
        # gateway apart from a healthy flat account — the last success
        # heartbeat alone would otherwise look fresh for up to 3h. Audit row
        # only; snapshot tables are never touched on this path.
        try:
            fconn = get_connection()
            try:
                fcur = fconn.cursor()
                fcur.execute(
                    "INSERT INTO gold.paper_uat_mirror_sync "
                    "(status, gateway_connected, error) "
                    "VALUES ('failed', FALSE, %s)", (str(e)[:500],))
                fconn.commit()
                print("Heartbeat: failure recorded -> gold.paper_uat_mirror_sync")
            finally:
                fconn.close()
        except Exception as he:
            print(f"WARN: failure heartbeat insert failed: {he}")
        return 1

    conn = get_connection()
    try:
        n_fill, n_unattr = sync_fills(conn, r_fill['data'], r_fill.get('as_of'), args.dry_run)
        n_book, n_skip, n_bad = sync_manual_orders(conn, r_fill['data'], args.dry_run)
        n_pos = sync_positions(conn, r_pos['data'], r_pos.get('as_of'), args.dry_run)
        n_ord = sync_open_orders(conn, r_ord['data'], r_ord.get('as_of'), args.dry_run)

        # Sync heartbeat: positions/open_orders are truncate+rewrite snapshots,
        # so a FLAT account leaves zero rows and max(synced_at) goes NULL —
        # indistinguishable from "mirror never synced" downstream (the
        # 2026-10-15 post-GLD-flatten false-ERROR class). One row per run gives
        # the registry guard a freshness signal that survives flat snapshots.
        if not args.dry_run:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO gold.paper_uat_mirror_sync "
                "(account, n_positions, n_open_orders, n_fills_new, "
                " n_fills_unattributed, status, gateway_connected) "
                "VALUES (%s, %s, %s, %s, %s, 'ok', TRUE)",
                (account, n_pos, n_ord, n_fill, n_unattr))
            conn.commit()
            print("Heartbeat: 1 row -> gold.paper_uat_mirror_sync")

        print()
        print(f"{'='*60}")
        print(f"Summary: {n_fill} fills ({n_unattr} unattributed), "
              f"blotter {n_book} booked/{n_skip} existing/{n_bad} invalid, "
              f"{n_pos} positions, {n_ord} open orders")
        print(f"{'='*60}")
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
