#!/usr/bin/env python3
"""Unit test: MANAGED RUNOFF mode for the paper rebalancer (kanban t_0daa8eaf).

A retired strategy with open paper legs (or resting orders) stays in the
rebuild set so legs are managed to their rule-consistent exit, but the
book is CLOSE-ONLY:

- A BUY target for a ticker NOT currently held is suppressed and surfaced
  as a RUNOFF_NO_ENTRY skip (no pending OPEN booked).
- A held leg whose signal leaves the BUY set still gets its pending CLOSE
  booked (rule-consistent exit; NEXT_OPEN convention).
- A non-runoff control book books the same new entry normally.

Run:  python test_rebuild_paper_positions_runoff.py
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
    """Captures mutating SQL so runoff behaviour can be asserted DB-free."""

    def __init__(self):
        self.mutating = []
        self.connection = _StubConn()
        self._last_head = ''

    def execute(self, sql, params=None):
        if isinstance(sql, bytes):
            sql = sql.decode('utf8', 'replace')
        head = ' '.join(str(sql).split())[:45].upper()
        self._last_head = head
        if head.startswith(('UPDATE GOLD.PAPER_TRADES',
                            'INSERT INTO GOLD.PAPER_TRADES_SYNTHETIC',
                            'INSERT INTO GOLD.PAPER_PENDING_ORDERS')):
            self.mutating.append(head)
        self.rowcount = 0
        self.description = []

    def mogrify(self, template, args=None):
        return b'()'

    def fetchall(self):
        return []

    def fetchone(self):
        if self._last_head.startswith('SELECT COALESCE(SUM'):
            return (0,)
        return None


def _strategy(runoff):
    return {
        'strategy_id': 'COMM_Copper_Trend_VolTarget',
        'name': 'Copper Trend VolTarget',
        'mode': 'PAPER',
        'capital': 100_000,
        'universe': ['HG=F', 'CASH'],
        'frequency': 'daily',
        'runoff': runoff,
    }


def _bars():
    return {'HG=F': {'date': date(2026, 10, 30), 'open': 6.60, 'close': 6.60}}


OPEN_LEG = {'id': 2586, 'direction': 'LONG', 'entry_date': date(2026, 8, 20),
            'entry_price': 6.511, 'n_shares': 8388, 'status': 'open'}


def test_runoff_held_buy_untouched():
    print("test_runoff_held_buy_untouched (mom>0: leg retained, no bookings)")
    cur = _StubCursor()
    signals = {'COMM_Copper_Trend_VolTarget': [
        {'ticker': 'HG=F', 'score': 53.6418, 'action': 'BUY'},
        {'ticker': 'CASH', 'score': 46.3582, 'action': 'HOLD'},
    ]}
    open_positions = {'COMM_Copper_Trend_VolTarget': {'HG=F': dict(OPEN_LEG)}}
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _strategy(runoff=True),
        prices=_bars(), signals=signals, open_positions=open_positions,
        lots={}, execute_rebalance=True, max_position_pct=1.0)
    check("held leg not closed", res['closed'] == 0, f"closed={res['closed']}")
    check("no opens booked", res['booked_open'] == 0 and res['opened'] == 0)
    check("no position-mutation SQL", cur.mutating == [],
          f"mutating: {cur.mutating}")
    check("no RUNOFF_NO_ENTRY skip for the held ticker",
          not any(s['skip_kind'] == 'RUNOFF_NO_ENTRY' for s in res['skipped']),
          f"skips: {[(s['ticker'], s['skip_kind']) for s in res['skipped']]}")
    check("signals still published", res['signals_published'] == 2)


def test_runoff_exit_on_signal_flip():
    print("test_runoff_exit_on_signal_flip (mom<=0: pending CLOSE booked, no opens)")
    cur = _StubCursor()
    signals = {'COMM_Copper_Trend_VolTarget': [
        {'ticker': 'HG=F', 'score': 0.0, 'action': 'HOLD'},   # momentum flip
        {'ticker': 'CASH', 'score': 100.0, 'action': 'HOLD'},
    ]}
    open_positions = {'COMM_Copper_Trend_VolTarget': {'HG=F': dict(OPEN_LEG)}}
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _strategy(runoff=True),
        prices=_bars(), signals=signals, open_positions=open_positions,
        lots={}, execute_rebalance=True, max_position_pct=1.0)
    close_sql = [m for m in cur.mutating if m.startswith('INSERT INTO GOLD.PAPER_PENDING_ORDERS')]
    check("pending CLOSE booked for the flipped leg", len(close_sql) == 1,
          f"mutating: {cur.mutating}")
    check("no immediate close (NEXT_OPEN defers)", res['closed'] == 0)
    check("no opens booked on exit day", res['booked_open'] == 0)


def test_runoff_no_new_entry():
    print("test_runoff_no_new_entry (transition window: BUY for non-held ticker suppressed)")
    cur = _StubCursor()
    signals = {'COMM_Copper_Trend_VolTarget': [
        {'ticker': 'HG=F', 'score': 53.6418, 'action': 'BUY'},
        {'ticker': 'CASH', 'score': 46.3582, 'action': 'HOLD'},
    ]}
    open_positions = {'COMM_Copper_Trend_VolTarget': {}}  # leg already flat
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _strategy(runoff=True),
        prices=_bars(), signals=signals, open_positions=open_positions,
        lots={}, execute_rebalance=True, max_position_pct=1.0)
    check("no opens booked for retired book", res['booked_open'] == 0
          and res['opened'] == 0, f"booked_open={res['booked_open']}")
    check("no position-mutation SQL", cur.mutating == [],
          f"mutating: {cur.mutating}")
    skips = [s for s in res['skipped'] if s['skip_kind'] == 'RUNOFF_NO_ENTRY']
    check("RUNOFF_NO_ENTRY skip surfaced for HG=F",
          any(s['ticker'] == 'HG=F' for s in skips),
          f"skips: {[(s['ticker'], s['skip_kind']) for s in res['skipped']]}")


def test_control_active_book_still_enters():
    print("test_control_active_book_still_enters (runoff=False books the same entry)")
    cur = _StubCursor()
    signals = {'COMM_Copper_Trend_VolTarget': [
        {'ticker': 'HG=F', 'score': 53.6418, 'action': 'BUY'},
        {'ticker': 'CASH', 'score': 46.3582, 'action': 'HOLD'},
    ]}
    open_positions = {'COMM_Copper_Trend_VolTarget': {}}
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _strategy(runoff=False),
        prices=_bars(), signals=signals, open_positions=open_positions,
        lots={}, execute_rebalance=True, max_position_pct=1.0)
    open_sql = [m for m in cur.mutating if m.startswith('INSERT INTO GOLD.PAPER_PENDING_ORDERS')]
    check("control books pending OPEN", len(open_sql) == 1,
          f"mutating: {cur.mutating}")
    check("no RUNOFF_NO_ENTRY skip on active book",
          not any(s['skip_kind'] == 'RUNOFF_NO_ENTRY' for s in res['skipped']))


if __name__ == '__main__':
    test_runoff_held_buy_untouched()
    test_runoff_exit_on_signal_flip()
    test_runoff_no_new_entry()
    test_control_active_book_still_enters()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
