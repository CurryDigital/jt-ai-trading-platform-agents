#!/usr/bin/env python3
"""uat_registry_guard.py — end-of-day UAT account vs registry guard (gold mirror).

Kanban t_9bee1ba6. Moves the qr_research 4-hourly live-API guard into the daily
ETL pipeline (post-22:30 UTC equity topup, after the PAPER_UAT mirror sync) and
extends the checks. Successor of scripts/uat_registry_crosscheck.py
(t_a44c50e1, mirror-based) and the qr_research live-endpoint guard
(check_uat_vs_registry.py). Standing recurrence guard recommended by
t_7d69ab61 (recommendation 3).

Reads the GOLD MIRROR tables (never the live backend API), so the
{"data": null} disconnected-session crash class of the qr_research script does
not exist here: a disconnected session fails the mirror sync, the snapshot
goes stale, and check 0 turns that into a clean ERROR verdict (exit 2) —
a traceback is not an alert.

Signal separation (same contract as t_a44c50e1):
  run_health  — did the guard execute? exit 0 = ran, exit 2 = DEAD/ERROR.
  verdict     — OK | VIOLATION (exit 0, alert on stdout) | ERROR (exit 2).
  Empty stdout on OK => watchdog delivers nothing.

Checks (all read-only):
  0. MIRROR_FRESH       paper_uat_mirror_sync.max(synced_at) — per-run sync
                        heartbeat (fallback: paper_uat_positions.max(synced_at))
                        — within UAT_GUARD_MIRROR_MAX_AGE_H (default 3h) of
                        run ts.
                        Else verdict=ERROR — the guard refuses to judge a
                        stale snapshot (equivalent of data:null upstream).
  a. ORPHAN_POSITIONS   positions with qty<>0 while ZERO active PAPER_UAT
                        sleeves. UNIVERSE_VIOLATION: held ticker not in the
                        union of active PAPER_UAT universes.
  b. UNOWNED_SHORT      qty<0 position with no short-permitted active
                        PAPER_UAT sleeve covering the ticker. Short permission
                        = gold.strategy_configs config_key='allow_short'
                        config_value='true' for that strategy (none today =>
                        every short flags).
  c. UNTAGGED_FILL      fills in the lookback window (default 13h — today's US
                        session at the 22:35 UTC run) with NULL/empty
                        order_ref OR NULL/empty strategy_id. Exempt (documented
                        single-use, t_7d69ab61): order_ref
                        'RECON_FLATTEN_t_7d69ab61' / strategy_id 'OPS_RECON'.
                        FOREIGN_FILL: attributed strategy not an active
                        PAPER_UAT sleeve. UNTAGGED_ORDER: gold.ibkr_orders
                        rows on the check date with NULL/empty strategy_id.
  d. ORPHAN_OPEN_ORDER  open orders in the snapshot while ZERO active
                        PAPER_UAT sleeves, or whose symbol is in no active
                        PAPER_UAT universe (mirror open orders carry no
                        order_ref — ownership is sleeve existence + universe).
  + MULTI_PAPER_UAT     >1 active PAPER_UAT sleeve (account-level book).

Outputs: JSONL log + latest-verdict file under the log dir (default
~/.hermes/profiles/qr_etl/logs/), gold.agent_events row (best effort), and
stdout ONLY on VIOLATION/ERROR (watchdog pattern). The 23:45 UTC
uat_guard_watchdog cron turns non-OK verdicts — or a MISSING verdict — into
Telegram alerts; a guard that errors or does not run is therefore caught.

Replay: --replay-fixture injects run_ts/mirror_synced_at/positions/fills/
open_orders/ibkr_orders (registry is live unless the fixture provides it) so
historical incident states (e.g. 2026-09-28 EOD) can be re-checked
deterministically without touching live tables.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

PROFILE_LOGS = '/home/ubuntu/.hermes/profiles/qr_etl/logs'
DEFAULT_LOG_DIR = os.environ.get('UAT_GUARD_LOG_DIR', PROFILE_LOGS)
JSONL_NAME = 'uat_registry_guard.jsonl'
LATEST_NAME = 'uat_registry_guard_latest.json'

MIRROR_MAX_AGE_H = float(os.environ.get('UAT_GUARD_MIRROR_MAX_AGE_H', '3'))
FILL_LOOKBACK_H = float(os.environ.get('UAT_GUARD_FILL_LOOKBACK_H', '13'))

# Documented single-use exceptions (user-approved reconciliation covers):
# t_7d69ab61 flatten 2026-10-09; t_72843934 residual GLD flatten 2026-10-15.
EXEMPT_ORDER_REFS = {'RECON_FLATTEN_t_7d69ab61', 'RECON_FLATTEN_t_72843934'}
EXEMPT_STRATEGY_IDS = {'OPS_RECON'}
# Until t_02e14081 lands (backend fills echo orderRef), key the approved
# reconciliation cover by immutable broker ids too.
EXEMPT_PERM_IDS = {1861250084}  # t_72843934 GLD flatten, user-approved 2026-10-15

ACTIVE_UAT_SQL = """
    SELECT strategy_id, universe_tickers FROM gold.strategy_registry
    WHERE execution_mode = 'PAPER_UAT' AND status NOT IN ('retired', 'paused')
"""
SHORT_PERM_SQL = """
    SELECT strategy_id FROM gold.strategy_configs
    WHERE config_key = 'allow_short' AND lower(config_value::text) IN ('true', '"true"')
"""


class GuardError(RuntimeError):
    """Guard could not produce a trustworthy verdict -> ERROR (exit 2)."""


def _dt(s):
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(s).replace('Z', '+00:00'))


def fetch_state(conn):
    cur = conn.cursor()
    # Freshness = latest SUCCESSFUL sync heartbeat. A sync whose positions
    # fetch failed (gateway down / data:null) writes status='failed'; a failed
    # attempt newer than the last success means account state is UNKNOWN (not
    # flat) — ERROR immediately instead of judging a stale snapshot for up to
    # MIRROR_MAX_AGE_H. A healthy flat account (0 rows, status ok) stays OK.
    ok_ts = any_ts = last_err = None
    try:
        cur.execute("""
            SELECT max(synced_at) FILTER (WHERE status = 'ok'),
                   max(synced_at),
                   (SELECT error FROM gold.paper_uat_mirror_sync
                    ORDER BY synced_at DESC LIMIT 1)
            FROM gold.paper_uat_mirror_sync""")
        ok_ts, any_ts, last_err = cur.fetchone()
    except Exception:
        conn.rollback()  # heartbeat table predates deploy; fall through
    if ok_ts is not None:
        if any_ts > ok_ts:
            raise GuardError(
                f'mirror sync last attempted {any_ts.isoformat()} FAILED '
                f'({(last_err or "unknown")[:200]}); last good sync '
                f'{ok_ts.isoformat()} — account state UNKNOWN, not flat')
        mirror_synced_at = ok_ts
    else:
        cur.execute("SELECT max(synced_at) FROM gold.paper_uat_positions")
        mirror_synced_at = cur.fetchone()[0]
    if mirror_synced_at is None:
        raise GuardError('paper_uat mirror never synced '
                         '(no heartbeat row, no position rows)')

    cur.execute("SELECT ticker, qty, market_value, currency FROM gold.paper_uat_positions WHERE qty <> 0")
    positions = [{'ticker': r[0], 'qty': float(r[1]),
                  'market_value': float(r[2]) if r[2] is not None else None,
                  'currency': r[3]}
                 for r in cur.fetchall()]

    cur.execute("""SELECT order_id, perm_id, symbol, action, qty, status
                   FROM gold.paper_uat_open_orders""")
    open_orders = [{'order_id': r[0], 'perm_id': r[1], 'symbol': r[2], 'action': r[3],
                    'qty': float(r[4]) if r[4] is not None else None,
                    'status': r[5]} for r in cur.fetchall()]

    cur.execute("""SELECT fill_time, symbol, side, qty, order_id, perm_id, order_ref, strategy_id
                   FROM gold.paper_uat_fills
                   WHERE fill_time >= NOW() - (%s || ' hours')::interval
                   ORDER BY fill_time""", (FILL_LOOKBACK_H,))
    fills = [{'fill_time': r[0].isoformat(), 'symbol': r[1], 'side': r[2],
              'qty': float(r[3]) if r[3] is not None else None,
              'order_id': r[4], 'perm_id': r[5], 'order_ref': r[6], 'strategy_id': r[7]}
             for r in cur.fetchall()]

    cur.execute("""SELECT id, ticker, action, quantity, strategy_id, status, submit_time, perm_id
                   FROM gold.ibkr_orders
                   WHERE submit_time::date = (NOW() AT TIME ZONE 'UTC')::date""")
    ibkr_orders = [{'id': r[0], 'ticker': r[1], 'action': r[2], 'quantity': r[3],
                    'strategy_id': r[4], 'status': r[5],
                    'submit_time': r[6].isoformat() if r[6] else None,
                    'perm_id': r[7]}
                   for r in cur.fetchall()]

    cur.execute(ACTIVE_UAT_SQL)
    uat_sleeves = [{'strategy_id': r[0], 'universe_tickers': list(r[1] or [])}
                   for r in cur.fetchall()]

    cur.execute(SHORT_PERM_SQL)
    short_permitted = [r[0] for r in cur.fetchall()]

    return {
        'mirror_synced_at': mirror_synced_at.isoformat(),
        'positions': positions,
        'open_orders': open_orders,
        'fills': fills,
        'ibkr_orders': ibkr_orders,
        'uat_sleeves': uat_sleeves,
        'short_permitted': short_permitted,
    }


def load_fixture(path):
    with open(path) as f:
        fx = json.load(f)
    state = {
        'mirror_synced_at': fx['mirror_synced_at'],
        'positions': fx.get('positions', []),
        'open_orders': fx.get('open_orders', []),
        'fills': fx.get('fills', []),
        'ibkr_orders': fx.get('ibkr_orders', []),
        'uat_sleeves': fx.get('uat_sleeves'),       # None => query live
        'short_permitted': fx.get('short_permitted'),  # None => query live
    }
    return state, fx.get('run_ts')


def evaluate(state, run_ts):
    """Pure check logic. Returns (problems, detail)."""
    problems = []
    detail = {}

    synced_at = _dt(state['mirror_synced_at'])
    age_h = (run_ts - synced_at).total_seconds() / 3600
    detail['mirror_synced_at'] = state['mirror_synced_at']
    detail['mirror_age_h'] = round(age_h, 2)
    if age_h > MIRROR_MAX_AGE_H or age_h < -1:
        raise GuardError(
            f'MIRROR_FRESH: paper_uat mirror synced {age_h:.1f}h from run ts '
            f'(max {MIRROR_MAX_AGE_H}h) — mirror not refreshed this evening; '
            'refusing to judge a stale snapshot (upstream session down?)')

    sleeves = state['uat_sleeves'] or []
    sleeve_ids = [s['strategy_id'] for s in sleeves]
    uat_universe = set()
    for s in sleeves:
        uat_universe.update(s.get('universe_tickers') or [])
    short_permitted = set(state['short_permitted'] or [])
    short_universe = {s['strategy_id'] for s in sleeves} & short_permitted
    short_tickers = set()
    for s in sleeves:
        if s['strategy_id'] in short_universe:
            short_tickers.update(s.get('universe_tickers') or [])
    detail['active_paper_uat'] = sleeve_ids
    detail['short_permitted_sleeves'] = sorted(short_universe)

    positions = state['positions']
    detail['positions'] = positions

    # a. orphan positions / universe membership
    if positions and not sleeves:
        problems.append(
            f"ORPHAN_POSITIONS: UAT account holds {len(positions)} positions "
            f"{[p['ticker'] for p in positions]} but NO active PAPER_UAT strategy in registry")
    elif positions:
        outside = [p['ticker'] for p in positions if p['ticker'] not in uat_universe]
        if outside:
            problems.append(
                f'UNIVERSE_VIOLATION: held tickers in no active PAPER_UAT universe: {outside}')

    # b. shorts without a short-permitted owner
    bad_shorts = [p for p in positions if p['qty'] < 0
                  and (not sleeves or p['ticker'] not in short_tickers)]
    if bad_shorts:
        problems.append(
            'UNOWNED_SHORT: short positions with no short-permitted PAPER_UAT owner: '
            + json.dumps([{ 'ticker': p['ticker'], 'qty': p['qty'],
                            'market_value': p['market_value'],
                            'currency': p.get('currency')} for p in bad_shorts]))

    # c. fill/order tagging in the lookback window
    window_start = run_ts - timedelta(hours=FILL_LOOKBACK_H)
    untagged, foreign = [], []
    for f in state['fills']:
        ft = _dt(f['fill_time'])
        if ft < window_start or ft > run_ts + timedelta(hours=1):
            continue
        ref = (f.get('order_ref') or '').strip()
        sid = (f.get('strategy_id') or '').strip()
        if ref in EXEMPT_ORDER_REFS or sid in EXEMPT_STRATEGY_IDS or f.get('perm_id') in EXEMPT_PERM_IDS:
            continue
        if not ref or not sid:
            untagged.append({'symbol': f['symbol'], 'side': f['side'],
                             'qty': f['qty'], 'order_id': f['order_id'],
                             'fill_time': f['fill_time'],
                             'order_ref': ref or None, 'strategy_id': sid or None})
        elif sid not in sleeve_ids:
            foreign.append({'strategy_id': sid, 'symbol': f['symbol'],
                            'fill_time': f['fill_time']})
    if untagged:
        problems.append(
            'UNTAGGED_FILL: fills with NULL/empty order_ref or strategy_id in '
            f'{FILL_LOOKBACK_H}h window: ' + json.dumps(untagged))
    if foreign:
        problems.append(
            'FOREIGN_FILL: fills attributed to non-active-PAPER_UAT strategies: '
            + json.dumps(foreign))

    bad_orders = [o for o in state['ibkr_orders']
                  if not (o.get('strategy_id') or '').strip()
                  and (o.get('strategy_id') or '') not in EXEMPT_STRATEGY_IDS
                  and o.get('perm_id') not in EXEMPT_PERM_IDS]
    if bad_orders:
        problems.append(
            'UNTAGGED_ORDER: gold.ibkr_orders rows today with NULL/empty strategy_id: '
            + json.dumps(bad_orders))
    detail['fills_window_h'] = FILL_LOOKBACK_H
    detail['untagged_fills'] = untagged
    detail['foreign_fills'] = foreign
    detail['untagged_ibkr_orders'] = bad_orders

    # d. open orders with no owning sleeve
    open_orders = state['open_orders']
    detail['open_orders'] = open_orders
    non_exempt_open = [o for o in open_orders if o.get('perm_id') not in EXEMPT_PERM_IDS]
    if non_exempt_open and not sleeves:
        problems.append(
            f'ORPHAN_OPEN_ORDER: {len(non_exempt_open)} working orders on the UAT book '
            'with NO active PAPER_UAT strategy: '
            + json.dumps([{ 'order_id': o['order_id'], 'symbol': o['symbol'],
                            'action': o['action'], 'qty': o['qty'],
                            'status': o['status']} for o in non_exempt_open]))
    elif non_exempt_open:
        outside = [o for o in non_exempt_open if o['symbol'] not in uat_universe]
        if outside:
            problems.append(
                'ORPHAN_OPEN_ORDER: working orders whose symbol is in no active '
                'PAPER_UAT universe: ' + json.dumps(outside))

    # multi-sleeve governance
    if len(sleeves) > 1:
        problems.append(
            f'MULTI_PAPER_UAT: {len(sleeves)} active PAPER_UAT strategies {sleeve_ids}; '
            'UAT book is account-level — at most one allowed')

    return problems, detail


def write_outputs(log_dir, rec):
    os.makedirs(log_dir, exist_ok=True)
    line = json.dumps(rec)
    with open(os.path.join(log_dir, JSONL_NAME), 'a') as f:
        f.write(line + '\n')
    with open(os.path.join(log_dir, LATEST_NAME), 'w') as f:
        f.write(line + '\n')
    return line


def emit_agent_event(line):
    try:
        from db import get_connection
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO gold.agent_events (agent_name, event_type, payload, created_at) "
                "VALUES ('qr_etl', 'UatRegistryGuardVerdict', %s, NOW())", (line,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f'WARN: agent_events insert failed: {e}', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description='UAT registry guard (gold mirror, EOD)')
    ap.add_argument('--replay-fixture', help='JSON fixture injecting state (offline replay)')
    ap.add_argument('--log-dir', default=DEFAULT_LOG_DIR,
                    help='where JSONL + latest verdict are written')
    ap.add_argument('--no-agent-event', action='store_true',
                    help='skip the gold.agent_events insert (tests)')
    args = ap.parse_args()

    run_ts = datetime.now(timezone.utc)
    try:
        if args.replay_fixture:
            state, fx_ts = load_fixture(args.replay_fixture)
            if fx_ts:
                run_ts = _dt(fx_ts)
            if state['uat_sleeves'] is None or state['short_permitted'] is None:
                from db import get_connection
                conn = get_connection()
                try:
                    live = fetch_state(conn)
                finally:
                    conn.close()
                if state['uat_sleeves'] is None:
                    state['uat_sleeves'] = live['uat_sleeves']
                if state['short_permitted'] is None:
                    state['short_permitted'] = live['short_permitted']
        else:
            from db import get_connection
            conn = get_connection()
            try:
                state = fetch_state(conn)
            finally:
                conn.close()
        problems, detail = evaluate(state, run_ts)
    except GuardError as e:
        rec = {'ts': run_ts.isoformat(), 'run_health': 'RAN', 'verdict': 'ERROR',
               'error': str(e)}
        line = write_outputs(args.log_dir, rec)
        if not args.no_agent_event:
            emit_agent_event(line)
        print('UAT-GUARD ERROR (guard ran but cannot produce a trustworthy verdict)')
        print(f'  - {e}')
        print(line)
        return 2
    except Exception as e:  # DEAD guard: loud AND distinct from VIOLATION
        rec = {'ts': run_ts.isoformat(), 'run_health': 'DEAD', 'verdict': 'ERROR',
               'error': f'{type(e).__name__}: {e}'}
        line = write_outputs(args.log_dir, rec)
        print(f'UAT-GUARD RUN-FAILURE guard did not execute: {line}')
        print(line, file=sys.stderr)
        return 2

    verdict = 'VIOLATION' if problems else 'OK'
    rec = {'ts': run_ts.isoformat(), 'run_health': 'RAN', 'verdict': verdict,
           'problems': problems, 'detail': detail}
    line = write_outputs(args.log_dir, rec)
    if not args.no_agent_event:
        emit_agent_event(line)
    if problems:
        print('UAT-GUARD VIOLATION (guard healthy, registry/account mismatch found)')
        for p in problems:
            print(f'  - {p}')
        print(f'detail: {json.dumps(detail)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
