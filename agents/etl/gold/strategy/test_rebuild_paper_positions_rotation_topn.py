#!/usr/bin/env python3
"""Regression test: rank-bounded rotation screen (kanban t_fdc57b21).

Root cause reproduced: a fully-deployed BUY-only paper book whose held
tickers all keep a BUY row in gold.strategy_ticker_scores can never rotate.
to_close = open - BUY_set is empty, the delta clamp counts the whole book as
retained cost, and every new BUY hits the OVER_DEPLOYED wall
(us_stk_sue_mom_01_v2, 2026-11-02: 56 BUYs vs a 20-slot design, 20 open
legs retained at $397,434.20 of $400k, 35 OVER_DEPLOYED skips, 0 closes,
period M:2026-11 consumed with zero rotation).

Fix under test: strategy_configs rotation_top_n=N declares a fixed top-N
screen. With BUY count > N the engine books exits for held laggards ranked
outside the screen (releasing their cost basis) and enters the in-screen
new names; non-held out-of-screen BUYs surface as ROTATION_TRIM skips.

Run:  python test_rebuild_paper_positions_rotation_topn.py
Exit 0 = all assertions pass. Pure-python, no DB required (stub cursor).
"""
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from rebuild_paper_positions import rebalance_strategy  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


class _StubConn:
    encoding = 'UTF8'


class _StubCursor:
    """Captures mutating SQL with per-statement row counts (execute_values
    calls mogrify once per row before a single execute)."""

    def __init__(self):
        self.connection = _StubConn()
        self._last_head = ''
        self._pending_rows = 0
        self.inserts = []          # (head, n_rows)
        self.rowcount = 0

    def mogrify(self, template, args=None):
        self._pending_rows += 1
        return b'()'

    def execute(self, sql, params=None):
        if isinstance(sql, bytes):
            sql = sql.decode('utf8', 'replace')
        head = ' '.join(str(sql).split())[:45].upper()
        self._last_head = head
        if head.startswith('INSERT INTO'):
            self.inserts.append((head, self._pending_rows))
            self.rowcount = self._pending_rows
        else:
            self.rowcount = 0
        self._pending_rows = 0
        self.description = []

    def fetchall(self):
        return []

    def fetchone(self):
        if self._last_head.startswith('SELECT COALESCE(SUM'):
            return (0,)
        return None

    def booked(self, kind):
        """Rows booked into paper_pending_orders for order_kind=kind."""
        # queue_pending_orders batches CLOSEs and OPENs as separate
        # execute_values calls; we cannot see the kind column in the head,
        # so callers distinguish by call order (closes booked first).
        return [(h, n) for h, n in self.inserts
                if h.startswith('INSERT INTO GOLD.PAPER_PENDING_ORDERS')]


SID = 'test_rotation_screen'

# SUE-shaped fixture: 56 BUYs (score = rank), 20-slot screen.
# Held: 7 in-screen (B50..B56) + 13 laggards (B24..B36).
# New in-screen entries: B37..B49. Non-held trimmed: B01..B23.
N_BUYS = 56
SCREEN = 20
PRICE = 10.0
HELD_SHARES = 1990          # $19,900 per leg, 20 legs = $398,000 of $400k
HELD_IN_SCREEN = [f'B{i:02d}' for i in range(50, 57)]   # 7
HELD_LAGGARDS = [f'B{i:02d}' for i in range(24, 37)]    # 13


def _signals():
    return {SID: [{'ticker': f'B{i:02d}', 'score': float(i), 'action': 'BUY'}
                  for i in range(1, N_BUYS + 1)]}


def _opens():
    return {SID: {t: {'id': 9000 + i, 'direction': 'LONG',
                      'entry_date': date(2026, 10, 5),
                      'entry_price': PRICE, 'n_shares': HELD_SHARES,
                      'status': 'open'}
                  for i, t in enumerate(HELD_IN_SCREEN + HELD_LAGGARDS)}}


def _strategy(rotation_top_n=None):
    s = {'strategy_id': SID, 'name': 'Rotation Screen Test',
         'mode': 'PAPER', 'capital': 400_000,
         'universe': [f'B{i:02d}' for i in range(1, N_BUYS + 1)],
         'frequency': 'monthly'}
    if rotation_top_n:
        s['rotation_top_n'] = rotation_top_n
    return s


def _prices():
    return {f'B{i:02d}': {'date': date(2026, 10, 30), 'open': PRICE,
                          'close': PRICE}
            for i in range(1, N_BUYS + 1)}


def test_control_without_config_reproduces_wall():
    print("test_control_without_config_reproduces_wall "
          "(no rotation_top_n: 1 right-sized entry, 35 OVER_DEPLOYED, 0 closes)")
    cur = _StubCursor()
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _strategy(), prices=_prices(),
        signals=_signals(), open_positions=_opens(), lots={},
        execute_rebalance=True, max_position_pct=0.20)
    pend = cur.booked('?')
    check("no pending CLOSE booked (wall: nothing leaves the BUY set)",
          res['booked_close'] == 0, f"booked_close={res['booked_close']}")
    od = [s for s in res['skipped'] if s['skip_kind'] == 'OVER_DEPLOYED']
    check("35 OVER_DEPLOYED skips (production repro)", len(od) == 35,
          f"got {len(od)}")
    check("at most one right-sized entry gets through the wall",
          res['booked_open'] <= 1, f"booked_open={res['booked_open']}")
    check("no ROTATION_TRIM without config",
          not any(s['skip_kind'] == 'ROTATION_TRIM' for s in res['skipped']))


def test_screened_book_rotates():
    print("test_screened_book_rotates "
          "(rotation_top_n=20: 13 laggard exits + 13 new entries, no wall)")
    cur = _StubCursor()
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _strategy(rotation_top_n=SCREEN),
        prices=_prices(), signals=_signals(), open_positions=_opens(),
        lots={}, execute_rebalance=True, max_position_pct=0.20)
    pend = cur.booked('?')
    # NEXT_OPEN books each CLOSE as its own queue_pending_orders call, then
    # all OPENs as one batch: 13 x 1-row CLOSE inserts + 1 x 13-row OPEN.
    check("13 pending CLOSEs booked (held laggards exit the screen)",
          sum(n for h, n in pend) == 26 and pend[:13] == [(
              'INSERT INTO GOLD.PAPER_PENDING_ORDERS (STRATE', 1)] * 13,
          f"pending inserts: {pend}")
    check("13 pending OPENs booked (new in-screen names)",
          len(pend) == 14 and pend[13][1] == 13,
          f"pending inserts: {pend}")
    check("booked_close count matches", res['booked_close'] == 13,
          f"booked_close={res['booked_close']}")
    check("booked_open count matches", res['booked_open'] == 13,
          f"booked_open={res['booked_open']}")
    od = [s for s in res['skipped'] if s['skip_kind'] == 'OVER_DEPLOYED']
    check("zero OVER_DEPLOYED skips (capital released by rotation exits)",
          len(od) == 0, f"got {[(s['ticker'], s['reason']) for s in od]}")
    trims = [s for s in res['skipped'] if s['skip_kind'] == 'ROTATION_TRIM']
    check("23 ROTATION_TRIM skips (non-held out-of-screen BUYs)",
          len(trims) == 23, f"got {len(trims)}")
    check("no ROTATION_TRIM for held laggards (they exit via close path)",
          not any(s['ticker'] in HELD_LAGGARDS for s in trims))
    check("signals still published for the full unscreened universe",
          res['signals_published'] == N_BUYS,
          f"published={res['signals_published']}")


def test_buys_within_screen_is_noop():
    print("test_buys_within_screen_is_noop (10 BUYs, screen 20: no trim)")
    cur = _StubCursor()
    signals = {SID: [{'ticker': f'B{i:02d}', 'score': float(i),
                      'action': 'BUY'} for i in range(1, 11)]}
    opens = {SID: {t: {'id': 1, 'direction': 'LONG',
                       'entry_date': date(2026, 10, 5),
                       'entry_price': PRICE, 'n_shares': 100,
                       'status': 'open'}
                   for t in ('B09', 'B10')}}
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _strategy(rotation_top_n=SCREEN),
        prices=_prices(), signals=signals, open_positions=opens,
        lots={}, execute_rebalance=True, max_position_pct=0.20)
    check("no closes booked", res['booked_close'] == 0,
          f"booked_close={res['booked_close']}")
    check("8 new entries booked", res['booked_open'] == 8,
          f"booked_open={res['booked_open']}")
    check("no ROTATION_TRIM skips",
          not any(s['skip_kind'] == 'ROTATION_TRIM' for s in res['skipped']))


def test_gated_day_emits_no_trim_rows():
    print("test_gated_day_emits_no_trim_rows "
          "(execute_rebalance=False: CADENCE_GATE for in-screen, no ROTATION_TRIM)")
    cur = _StubCursor()
    res = rebalance_strategy(
        cur, date(2026, 11, 3), _strategy(rotation_top_n=SCREEN),
        prices=_prices(), signals=_signals(), open_positions=_opens(),
        lots={}, execute_rebalance=False, gate_reason='monthly: not a rebalance date',
        max_position_pct=0.20)
    check("no position mutations on a gated day",
          not cur.inserts or all(
              'PENDING_ORDERS' not in h and 'TRADES_SYNTHETIC' not in h
              for h, _ in cur.inserts),
          f"inserts: {cur.inserts}")
    check("no ROTATION_TRIM rows on gated days (screen enforced at boundary)",
          not any(s['skip_kind'] == 'ROTATION_TRIM' for s in res['skipped']))
    cg = [s for s in res['skipped'] if s['skip_kind'] == 'CADENCE_GATE']
    check("13 CADENCE_GATE skips for the deferred in-screen entries",
          len(cg) == 13, f"got {len(cg)}")


if __name__ == '__main__':
    test_control_without_config_reproduces_wall()
    test_screened_book_rotates()
    test_buys_within_screen_is_noop()
    test_gated_day_emits_no_trim_rows()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
