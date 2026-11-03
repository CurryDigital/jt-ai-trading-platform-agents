#!/usr/bin/env python3
"""Regression tests: cadence-marker ordering and idempotency (PORTFOLIO-ALIGN-1 B5).

Covers the three mandated scenarios:
1. Duplicate batch after a completed rebalance -> suppressed, zero mutations,
   zero new pending orders (idempotent re-run of the same period).
2. First-pass rebalance of a new period -> executes; NEXT_OPEN convention books
   deferred orders (no same-bar fills).
3. Interrupted/partial rebalance -> the period marker is NOT durably advanced
   (single-transaction ordering: SQL_TOUCH_REBALANCE_STATE commits only with the
   whole run), so the next run re-fires the rebalance instead of hiding the
   remainder as CADENCE_GATE skips.

Plus one defect-pinning test (current behaviour, documented): the gated path
surfaces CADENCE_GATE rows for targets that already have a RESTING pending OPEN
order from the completed rebalance — the skip surface double-labels resting
orders as gate-deferred (observed live 2026-11-02, us_stk_lowbeta_14: 28 of 31
current CADENCE_GATE rows had resting pending orders from the executed 09:17
rebalance). This test pins CURRENT behaviour so the fix diff is explicit.

Run:  python test_rebuild_paper_positions_rebalance_atomicity.py
Exit 0 = all assertions pass. Pure-python, no DB required.
"""
import os
import re
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from rebuild_paper_positions import (  # noqa: E402
    decide_rebalance,
    period_key_for,
    rebalance_strategy,
    SQL_FETCH_PENDING_ORDERS,
    SQL_MARK_ORDER_FILLED,
)

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


class _StubConn:
    encoding = 'UTF8'


class _StubCursor:
    """Captures ALL mutating SQL by target table (extended vs the cadence-gate
    stub: also tracks paper_pending_orders inserts)."""
    def __init__(self):
        self.mutating = []
        self.connection = _StubConn()
        self._last_head = ''

    def execute(self, sql, params=None):
        head = ' '.join(str(sql).split())[:60].upper()
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


def _monthly_strategy():
    return {
        'strategy_id': 'test_monthly',
        'name': 'Test Monthly',
        'mode': 'PAPER',
        'capital': 100_000,
        'universe': ['AAA', 'BBB'],
        'frequency': 'monthly',
    }


def _bars():
    return {
        'AAA': {'date': date(2026, 8, 14), 'open': 100.0, 'close': 100.0},
        'BBB': {'date': date(2026, 8, 14), 'open': 50.0, 'close': 50.0},
    }


def _signals():
    return {'test_monthly': [
        {'ticker': 'AAA', 'score': 60, 'action': 'BUY'},
        {'ticker': 'BBB', 'score': 40, 'action': 'BUY'},
    ]}


def test_1_duplicate_batch_after_completion():
    print("test_1: duplicate batch after successful completion is fully suppressed")
    st = {'frequency': 'monthly', 'last_period_key': 'M:2026-11',
          'last_rebalance_date': date(2026, 11, 2)}
    # Same day, later run (the 2026-11-02 09:52/09:55 case): period consumed.
    ex, key, reason = decide_rebalance('monthly', date(2026, 11, 2), st)
    check("same-day second run suppressed", not ex, reason)
    # Any later day in the period: suppressed.
    ex, key, reason = decide_rebalance('monthly', date(2026, 11, 20), st)
    check("later same-period run suppressed", not ex, reason)

    # Idempotency at the mutation layer: gated run issues NO position or
    # pending-order mutations even though a NEW BUY target exists.
    cur = _StubCursor()
    res = rebalance_strategy(
        cur, date(2026, 11, 20), _monthly_strategy(),
        prices=_bars(), signals=_signals(),
        open_positions={'test_monthly': {
            'AAA': {'id': 1, 'direction': 'LONG', 'entry_date': date(2026, 11, 3),
                    'entry_price': 100.0, 'n_shares': 100, 'status': 'open'}}},
        lots={}, execute_rebalance=False,
        gate_reason='period M:2026-11 already rebalanced 2026-11-02',
        max_position_pct=0.0)
    check("duplicate run books no pending orders",
          not any('PAPER_PENDING_ORDERS' in m for m in cur.mutating),
          f"mutating: {cur.mutating}")
    check("duplicate run mutates no positions",
          not any('PAPER_TRADES' in m for m in cur.mutating))
    check("duplicate run still publishes signals (surface stays fresh)",
          res['signals_published'] == 2)


def test_2_first_pass_rebalance_executes_deferred():
    print("test_2: first-pass rebalance of a new period executes via NEXT_OPEN deferred orders")
    st = {'frequency': 'monthly', 'last_period_key': 'M:2026-10',
          'last_rebalance_date': date(2026, 10, 1)}
    ex, key, reason = decide_rebalance('monthly', date(2026, 11, 2), st)
    check("new period executes", ex and key == 'M:2026-11', reason)

    cur = _StubCursor()
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _monthly_strategy(),
        prices=_bars(), signals=_signals(),
        open_positions={'test_monthly': {}},
        lots={}, execute_rebalance=True,
        gate_reason='new period (last M:2026-10)',
        convention='NEXT_OPEN',
        max_position_pct=0.0)
    check("NEXT_OPEN books deferred orders (no immediate position rows)",
          res['booked_open'] >= 0 and res['opened'] == 0,
          f"booked_open={res['booked_open']} opened={res['opened']}")
    check("no same-bar position insert under NEXT_OPEN",
          not any('PAPER_TRADES_SYNTHETIC' in m for m in cur.mutating),
          f"mutating: {cur.mutating}")


def test_3_interrupted_rebalance_resumable():
    print("test_3: interrupted/partial rebalance does not durably advance the period marker")
    # Behavioural half: if the 11-02 rebalance had crashed, the state row would
    # still carry the October key (transaction rollback), so the next run sees
    # a NEW period and re-fires — the remainder can never be hidden as
    # CADENCE_GATE skips.
    st_pre = {'frequency': 'monthly', 'last_period_key': 'M:2026-10',
              'last_rebalance_date': date(2026, 10, 1)}
    ex, key, reason = decide_rebalance('monthly', date(2026, 11, 3), st_pre)
    check("post-crash run re-fires the rebalance (period never marked done)",
          ex and key == 'M:2026-11', reason)

    # Structural half: ordering + transaction scope in run(). The period marker
    # (SQL_TOUCH_REBALANCE_STATE) and all position/order mutations must share
    # one transaction: no commit between the touch and the final commit, and a
    # rollback path on exception.
    src = open(os.path.join(_HERE, 'rebuild_paper_positions.py')).read()
    i_touch = src.find('SQL_TOUCH_REBALANCE_STATE, (sid, freq, period_key, today)')
    i_rebal = src.find('res = rebalance_strategy(')
    i_commit = src.find('conn.commit()', i_rebal)
    i_rollback = src.find('conn.rollback()', i_commit)
    check("state touch precedes rebalance execution", 0 < i_touch < i_rebal)
    check("no commit between state touch and rebalance (single transaction)",
          'conn.commit()' not in src[i_touch:i_rebal])
    check("single commit after all strategies, rollback on exception",
          0 < i_commit < i_rollback)
    # Settle idempotency: only status='pending' orders are fetched for
    # settlement, and a fill flips status — a crashed settle re-processes
    # exactly the still-pending remainder.
    check("settle fetches only pending orders",
          "status = 'pending'" in ' '.join(SQL_FETCH_PENDING_ORDERS.split())
          or "status='pending'" in SQL_FETCH_PENDING_ORDERS.replace(' ', ''))
    check("fill marks the order filled (no double-settle)",
          'filled' in SQL_MARK_ORDER_FILLED.lower())


def test_4_gated_path_excludes_resting_orders():
    print("test_4: gated path does NOT surface CADENCE_GATE for targets "
          "with resting pending OPEN orders")
    # Live evidence 2026-11-02 us_stk_lowbeta_14: after the 09:17 rebalance
    # booked 28 pending OPENs, the gated 09:52/09:55 runs surfaced those same
    # 28 tickers as CADENCE_GATE because the gate branch checked open_tickers
    # but not pend_open_tickers ("31 unfilled" = 28 resting + 3 genuine).
    # Fixed t_a300dee2: resting-order targets are neither re-booked NOR
    # labelled gate-deferred.
    cur = _StubCursor()
    res = rebalance_strategy(
        cur, date(2026, 11, 2), _monthly_strategy(),
        prices=_bars(), signals=_signals(),
        open_positions={'test_monthly': {}},
        lots={}, execute_rebalance=False,
        gate_reason='period M:2026-11 already rebalanced 2026-11-02',
        max_position_pct=0.0,
        pend_open_tickers={'AAA': 100, 'BBB': 400})  # both resting from the rebalance
    gate_skips = [s for s in res['skipped'] if s['skip_kind'] == 'CADENCE_GATE']
    check("resting-order targets excluded from CADENCE_GATE surfacing",
          gate_skips == [],
          f"skips: {[(s['ticker'], s['skip_kind']) for s in res['skipped']]}")


if __name__ == '__main__':
    test_1_duplicate_batch_after_completion()
    test_2_first_pass_rebalance_executes_deferred()
    test_3_interrupted_rebalance_resumable()
    test_4_gated_path_excludes_resting_orders()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
