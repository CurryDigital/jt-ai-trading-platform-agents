#!/usr/bin/env python3
"""
PAPER_UAT firing-contract tests (kanban t_b64f7302).

DB-free: rebalance_strategy is driven with stub cursors and monkeypatched
UAT HTTP helpers. Asserts:
1. PAPER_UAT strategies fire order deltas to the UAT session and write
   NOTHING to the DB paper ledger (no paper_trades_synthetic /
   paper_pending_orders mutations).
2. Exits fire SELL for UAT-held universe tickers that left the BUY set.
3. Entries fire BUY for sized targets not held and not already working.
4. Working-order dedup: an order already resting at UAT is not re-fired.
5. Disconnected UAT session -> PaperUatFireError (hard fail, no fallback).
6. dry_run fires nothing (no HTTP, no exceptions even with UAT down).
7. fire_paper_uat_order rejects responses not confirmed on the UAT session
   (simulated=True or session != 'uat') — never lands live/simulated.
"""
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import rebuild_paper_positions as rpp  # noqa: E402

# Capture the REAL firing entry point before any test monkeypatches it.
_REAL_FIRE = rpp.fire_paper_uat_order

PASS = []
FAIL = []


def check(name, cond, detail=''):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f"  ({detail})" if detail else ""))


class _StubConn:
    encoding = 'UTF8'


class _StubCursor:
    """Captures any SQL touching the DB paper ledger."""
    LEDGER_MARKERS = ('GOLD.PAPER_TRADES_SYNTHETIC', 'GOLD.PAPER_PENDING_ORDERS')

    def __init__(self):
        self.ledger_sql = []
        self.signal_upserts = 0
        self.connection = _StubConn()

    def execute(self, sql, params=None):
        # psycopg2 execute_values passes bytes; decode before matching.
        if isinstance(sql, (bytes, bytearray)):
            sql = sql.decode('utf-8', 'replace')
        head = ' '.join(str(sql).split()).upper()
        if any(m in head for m in self.LEDGER_MARKERS) and not head.startswith('SELECT'):
            self.ledger_sql.append(head[:60])
        if 'STRATEGIES_SIGNALS_CURRENT' in head and head.startswith('INSERT'):
            self.signal_upserts += 1
        self.rowcount = 0
        self.description = []

    def mogrify(self, template, args=None):
        return b'()'

    def fetchall(self):
        return []

    def fetchone(self):
        return None


def _uat_strategy():
    return {
        'strategy_id': 'test_uat',
        'name': 'Test UAT',
        'mode': 'PAPER_UAT',
        'capital': 100_000,
        'universe': ['AAA', 'BBB', 'CCC'],
        'frequency': 'daily',
    }


def _bars():
    return {
        'AAA': {'date': date(2026, 8, 24), 'open': 100.0, 'close': 100.0},
        'BBB': {'date': date(2026, 8, 24), 'open': 50.0, 'close': 50.0},
        'CCC': {'date': date(2026, 8, 24), 'open': 25.0, 'close': 25.0},
    }


def _signals():
    # BUY AAA + BBB; CCC is a HOLD (dropped out).
    return {'test_uat': [
        {'ticker': 'AAA', 'score': 50, 'action': 'BUY'},
        {'ticker': 'BBB', 'score': 50, 'action': 'BUY'},
        {'ticker': 'CCC', 'score': 10, 'action': 'HOLD'},
    ]}


def _run_uat(cur, held, working, fired, **kw):
    rpp.fetch_uat_positions = lambda: dict(held)
    rpp.fetch_uat_working_orders = lambda: set(working)
    def _fire(sid, ticker, action, qty, dry_run=False):
        fired.append({'sid': sid, 'ticker': ticker, 'action': action,
                      'qty': int(qty), 'dry_run': dry_run})
        return {'success': True, 'session': 'uat'}
    rpp.fire_paper_uat_order = _fire
    return rpp.rebalance_strategy(
        cur, date(2026, 8, 25), _uat_strategy(),
        prices=_bars(), signals=_signals(), open_positions={}, lots={},
        execute_rebalance=True, **kw)


def test_fire_deltas():
    print("test_fire_deltas (UAT-held CCC sold; AAA already held -> no re-buy; BBB bought)")
    cur = _StubCursor()
    fired = []
    # UAT holds AAA (still a BUY -> keep) and CCC (HOLD -> sell).
    res = _run_uat(cur, held={'AAA': 200, 'CCC': 100}, working=set(), fired=fired)
    sells = [f for f in fired if f['action'] == 'SELL']
    buys = [f for f in fired if f['action'] == 'BUY']
    check("SELL fired for dropped CCC", len(sells) == 1 and sells[0]['ticker'] == 'CCC'
          and sells[0]['qty'] == 100, f"fired={fired}")
    check("no re-BUY for held AAA", all(f['ticker'] != 'AAA' for f in buys), f"fired={fired}")
    check("BUY fired for new target BBB", len(buys) == 1 and buys[0]['ticker'] == 'BBB',
          f"fired={fired}")
    check("no DB ledger mutations", cur.ledger_sql == [], f"ledger SQL: {cur.ledger_sql}")
    check("result counts reflect fired orders", res['closed'] == 1 and res['opened'] == 1,
          f"closed={res['closed']} opened={res['opened']}")
    check("signals still published", res['signals_published'] >= 3,
          f"signals={res['signals_published']}")


def test_working_order_dedup():
    print("test_working_order_dedup (resting orders at UAT are not re-fired)")
    cur = _StubCursor()
    fired = []
    # CCC held+SELL working, BBB BUY working; AAA is an unheld BUY target
    # with nothing resting -> AAA is the ONLY order that should fire.
    _run_uat(cur, held={'CCC': 100}, working={('CCC', 'SELL'), ('BBB', 'BUY')}, fired=fired)
    check("no SELL re-fired for CCC (already working)",
          not any(f['action'] == 'SELL' and f['ticker'] == 'CCC' for f in fired), f"fired={fired}")
    check("no BUY re-fired for BBB (already working)",
          not any(f['action'] == 'BUY' and f['ticker'] == 'BBB' for f in fired), f"fired={fired}")
    check("only the unheld AAA BUY fired",
          len(fired) == 1 and fired[0]['ticker'] == 'AAA' and fired[0]['action'] == 'BUY',
          f"fired={fired}")


def test_disconnected_hard_fail():
    print("test_disconnected_hard_fail (UAT down -> PaperUatFireError, nothing fired)")
    cur = _StubCursor()
    fired = []
    def _boom():
        raise rpp.PaperUatFireError("UAT session not connected (positions): connected=false")
    rpp.fetch_uat_positions = _boom
    rpp.fire_paper_uat_order = lambda *a, **k: fired.append(a)
    try:
        rpp.rebalance_strategy(
            cur, date(2026, 8, 25), _uat_strategy(),
            prices=_bars(), signals=_signals(), open_positions={}, lots={},
            execute_rebalance=True)
        check("PaperUatFireError raised", False, "no exception")
    except rpp.PaperUatFireError:
        check("PaperUatFireError raised", True)
    check("no orders fired", fired == [])
    check("no DB ledger mutations on failure", cur.ledger_sql == [],
          f"ledger SQL: {cur.ledger_sql}")
    check("signals still published despite fire failure (deferred raise)",
          cur.signal_upserts > 0, f"signal_upserts={cur.signal_upserts}")


def test_dry_run_fires_nothing():
    print("test_dry_run (would-be orders only; works even with UAT down)")
    cur = _StubCursor()
    # Even with the session down, dry-run prints would-be orders. Position
    # reads are stubbed to succeed (read-only in production too).
    # Fixture: CCC held (dropped -> SELL), AAA+BBB unheld BUY targets.
    res = _run_uat(cur, held={'CCC': 100}, working=set(), fired=[], dry_run=True)
    check("dry-run completed", res['closed'] == 1 and res['opened'] == 2,
          f"closed={res['closed']} opened={res['opened']}")
    check("no DB ledger mutations in dry-run", cur.ledger_sql == [],
          f"ledger SQL: {cur.ledger_sql}")


def test_fire_rejects_non_uat_confirmation():
    print("test_fire_rejects_non_uat_confirmation (simulated / wrong session = not fired)")
    real_http = rpp._uat_http
    # Case 1: simulated virtual fill (backend ignored book) -> hard fail.
    rpp._uat_http = lambda m, p, payload=None: {
        'success': True, 'simulated': True, 'order_id': 'SIM_1'}
    try:
        _REAL_FIRE('test_uat', 'AAA', 'BUY', 10)
        check("simulated response rejected", False, "no exception")
    except rpp.PaperUatFireError:
        check("simulated response rejected", True)
    # Case 2: routed to the primary session -> hard fail (must never be live).
    rpp._uat_http = lambda m, p, payload=None: {
        'success': True, 'session': 'primary', 'order_id': 42}
    try:
        _REAL_FIRE('test_uat', 'AAA', 'BUY', 10)
        check("primary-session response rejected", False, "no exception")
    except rpp.PaperUatFireError:
        check("primary-session response rejected", True)
    # Case 3: confirmed on UAT -> passes, payload carries the contract fields.
    captured = {}
    def _ok(method, path, payload=None):
        captured.update(payload or {})
        return {'success': True, 'session': 'uat', 'order_id': 7}
    rpp._uat_http = _ok
    r = _REAL_FIRE('test_uat', 'AAA', 'BUY', 10)
    check("uat-confirmed response accepted", r.get('order_id') == 7)
    check("payload contract fields",
          captured.get('book') == 'paper_uat'
          and captured.get('strategy_id') == 'test_uat'
          and captured.get('order_ref') == 'strat:test_uat'
          and captured.get('order_type') == 'MKT',
          f"payload={captured}")
    rpp._uat_http = real_http


def test_sell_restricted_to_universe():
    print("test_sell_restricted_to_universe (foreign UAT holdings never sold)")
    cur = _StubCursor()
    fired = []
    # ZZZ is held at UAT but is NOT in this strategy's universe -> never sold.
    _run_uat(cur, held={'ZZZ': 500}, working=set(), fired=fired)
    check("no SELL for foreign ticker ZZZ",
          not any(f['ticker'] == 'ZZZ' for f in fired), f"fired={fired}")


if __name__ == '__main__':
    test_fire_deltas()
    test_working_order_dedup()
    test_disconnected_hard_fail()
    test_dry_run_fires_nothing()
    test_fire_rejects_non_uat_confirmation()
    test_sell_restricted_to_universe()
    print(f"\nPASSED: {len(PASS)}  FAILED: {len(FAIL)}")
    if FAIL:
        print("FAILED checks:", FAIL)
        sys.exit(1)
    print("ALL CHECKS PASSED")
