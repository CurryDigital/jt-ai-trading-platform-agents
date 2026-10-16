#!/usr/bin/env python3
"""
test_sync_paper_uat.py — unit tests for sync_paper_uat_to_gold.py (t_db5ffc20).

Covers:
  1. order_ref attribution ('strat:<sid>' -> sid; everything else -> None)
  2. happy-path sync: fills upsert (attributed + unattributed), snapshot
     truncate+reload of positions/open_orders, correct counts
  3. disconnected UAT session: hard-fail exit 1, DB never touched
  4. HTTP failure: hard-fail exit 1

Run: python3 test_sync_paper_uat.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sync_paper_uat_to_gold as m


# --- fakes ---------------------------------------------------------------

class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))

    def fetchall(self):
        return self.conn.notes_to_return


class FakeConn:
    def __init__(self, notes_to_return=()):
        self.statements = []
        self.commits = 0
        self.closed = False
        self.notes_to_return = list(notes_to_return)

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def connected(payload):
    return {'session': 'uat', 'connected': True, 'account': 'DUP825942',
            'data': payload, 'count': len(payload),
            'as_of': '2026-08-25T10:00:00+00:00'}


FILLS = [
    {'exec_id': 'e1', 'order_id': 101, 'order_ref': 'strat:ETF_US_Momentum',
     'symbol': 'AAPL', 'local_symbol': 'AAPL', 'side': 'BOT', 'qty': 10.0,
     'price': 300.5, 'time': '2026-08-25T09:31:00+00:00', 'account': 'DUP825942'},
    {'exec_id': 'e2', 'order_id': 102, 'order_ref': None,
     'symbol': 'MSFT', 'local_symbol': 'MSFT', 'side': 'SLD', 'qty': 5.0,
     'price': 410.0, 'time': '2026-08-25T09:32:00+00:00', 'account': 'DUP825942'},
]
POSITIONS = [
    {'ticker': 'AAPL', 'symbol': 'AAPL', 'sec_type': 'STK', 'exchange': 'NASDAQ',
     'currency': 'USD', 'qty': 10.0, 'avg_cost': 295.0, 'market_price': 300.5,
     'market_value': 3005.0, 'unrealized_pnl': 55.0, 'realized_pnl': 0.0,
     'account': 'DUP825942'},
]
OPEN_ORDERS = [
    {'order_id': 103, 'perm_id': 9001, 'symbol': 'TSLA', 'local_symbol': 'TSLA',
     'action': 'BUY', 'qty': 3.0, 'order_type': 'MKT', 'status': 'PreSubmitted',
     'filled': 0.0, 'remaining': 3.0},
]


def fake_uat_http(method, path, payload=None):
    if path.endswith('/positions'):
        return connected(POSITIONS)
    if path.endswith('/open-orders'):
        return connected(OPEN_ORDERS)
    if path.endswith('/fills'):
        return connected(FILLS)
    raise AssertionError(f'unexpected path {path}')


# --- tests ----------------------------------------------------------------

class TestAttribution(unittest.TestCase):
    def test_strat_ref(self):
        self.assertEqual(m.attribute_strategy('strat:ETF_US_Momentum'),
                         'ETF_US_Momentum')

    def test_unmatched_refs_are_null(self):
        for ref in (None, '', 'manual', 'strat:', 'STRAT:Foo', 'xstrat:Foo'):
            self.assertIsNone(m.attribute_strategy(ref), ref)

    def test_ops_recon_refs(self):
        """RECON_FLATTEN_* covers from the guarded backend route attribute to
        the OPS_RECON pseudo-strategy, never NULL (kanban t_a374fbeb)."""
        self.assertEqual(m.attribute_strategy('RECON_FLATTEN_t_72843934'),
                         'OPS_RECON')
        self.assertEqual(m.attribute_strategy('RECON_FLATTEN_t_7d69ab61'),
                         'OPS_RECON')
        # lookalikes that are NOT guarded-path covers stay unattributed
        for ref in ('RECON_FLATTEN', 'recon_flatten_t_x', 'RECON_FLATTEN_',
                    'xRECON_FLATTEN_t_x', 'RECON_FLATTEN t_x'):
            self.assertIsNone(m.attribute_strategy(ref), ref)


class TestHappyPath(unittest.TestCase):
    def test_sync_writes_all_three_tables(self):
        conn = FakeConn()
        with mock.patch.object(m, '_uat_http', side_effect=fake_uat_http), \
             mock.patch.object(m, 'get_connection', return_value=conn):
            argv = sys.argv
            sys.argv = ['sync_paper_uat_to_gold.py']
            try:
                rc = m.main()
            finally:
                sys.argv = argv
        self.assertEqual(rc, 0)
        sqls = [s for s, _ in conn.statements]

        # fills: 2 upserts, one attributed one not
        fill_inserts = [(s, p) for s, p in conn.statements
                        if 'gold.paper_uat_fills' in s]
        self.assertEqual(len(fill_inserts), 2)
        strat_ids = sorted(p[5] for _, p in fill_inserts
                           if p[5] is not None)
        self.assertEqual(strat_ids, ['ETF_US_Momentum'])
        self.assertTrue(any(p[5] is None for _, p in fill_inserts))
        sides = sorted(p[8] for _, p in fill_inserts)
        self.assertEqual(sides, ['BUY', 'SELL'])

        # snapshots: truncate + insert
        self.assertTrue(any('TRUNCATE gold.paper_uat_positions' in s for s in sqls))
        self.assertTrue(any('TRUNCATE gold.paper_uat_open_orders' in s for s in sqls))
        pos_inserts = [p for s, p in conn.statements
                       if 'gold.paper_uat_positions' in s and 'INSERT' in s]
        ord_inserts = [p for s, p in conn.statements
                       if 'gold.paper_uat_open_orders' in s and 'INSERT' in s]
        self.assertEqual(len(pos_inserts), 1)
        self.assertEqual(pos_inserts[0][1], 'AAPL')
        self.assertEqual(len(ord_inserts), 1)
        self.assertEqual(ord_inserts[0][5], 'BUY')
        self.assertGreater(conn.commits, 0)
        self.assertTrue(conn.closed)

    def test_blotter_books_every_fill(self):
        conn = FakeConn()
        with mock.patch.object(m, '_uat_http', side_effect=fake_uat_http), \
             mock.patch.object(m, 'get_connection', return_value=conn):
            argv = sys.argv
            sys.argv = ['sync_paper_uat_to_gold.py']
            try:
                rc = m.main()
            finally:
                sys.argv = argv
        self.assertEqual(rc, 0)
        blotter = [(s, p) for s, p in conn.statements
                   if 'gold.manual_orders' in s and 'INSERT' in s]
        self.assertEqual(len(blotter), 2)
        ids = sorted(p[0] for _, p in blotter)
        self.assertEqual(ids, ['uat-e1', 'uat-e2'])  # deterministic, idempotent
        for _, p in blotter:
            self.assertEqual(p[1], 'paper_uat')
            self.assertEqual(p[4], 'STOCK')
            self.assertEqual(p[3], 'US')  # no currency in fake fills -> US
            self.assertIn('exec', p[8])
        by_id = {p[0]: p for _, p in blotter}
        self.assertEqual(by_id['uat-e1'][5], 'BUY')   # BOT -> BUY
        self.assertEqual(by_id['uat-e2'][5], 'SELL')  # SLD -> SELL

    def test_blotter_skips_backend_booked_and_invalid(self):
        conn = FakeConn(notes_to_return=[
            ('AAPL', 'IBKR UAT close · ib_order 101 · acct DUP825942'),
        ])
        bad = dict(FILLS[1])
        bad['qty'] = 0
        fills = FILLS + [bad]
        booked, skipped_existing, skipped_invalid = \
            m.sync_manual_orders(conn, fills)
        self.assertEqual((booked, skipped_existing, skipped_invalid), (1, 1, 1))
        blotter = [p for s, p in conn.statements
                   if 'gold.manual_orders' in s and 'INSERT' in s]
        self.assertEqual(len(blotter), 1)
        self.assertEqual(blotter[0][0], 'uat-e2')

    def test_fill_time_sg_conversion(self):
        # 13:30:07 UTC -> 21:30:07 naive +08:00 (manual_orders convention)
        self.assertEqual(
            m._fill_time_sg('2026-08-25T13:30:07+00:00').isoformat(),
            '2026-08-25T21:30:07')
        self.assertIsNone(m._fill_time_sg(None))
        self.assertIsNone(m._fill_time_sg('not-a-date'))

    def test_dry_run_writes_nothing(self):
        conn = FakeConn()
        argv = sys.argv
        sys.argv = ['sync_paper_uat_to_gold.py', '--dry-run']
        try:
            with mock.patch.object(m, '_uat_http', side_effect=fake_uat_http), \
                 mock.patch.object(m, 'get_connection', return_value=conn):
                rc = m.main()
        finally:
            sys.argv = argv
        self.assertEqual(rc, 0)
        self.assertEqual(conn.statements, [])
        self.assertEqual(conn.commits, 0)


class TestHardFail(unittest.TestCase):
    def _run_with_http(self, http):
        conn = FakeConn()
        argv = sys.argv
        sys.argv = ['sync_paper_uat_to_gold.py']
        try:
            with mock.patch.object(m, '_uat_http', side_effect=http), \
                 mock.patch.object(m, 'get_connection', return_value=conn) as gc:
                rc = m.main()
        finally:
            sys.argv = argv
        return rc, gc, conn

    def _assert_failure_heartbeat_only(self, rc, gc, conn):
        self.assertEqual(rc, 1)
        gc.assert_called_once()  # failure heartbeat only; snapshots untouched
        sqls = [s for s, _ in conn.statements]
        self.assertTrue(
            any('gold.paper_uat_mirror_sync' in s and "VALUES ('failed'" in s
                for s in sqls), sqls)
        self.assertFalse(
            any('TRUNCATE' in s or 'gold.paper_uat_fills' in s or
                'gold.paper_uat_positions' in s or
                'gold.paper_uat_open_orders' in s for s in sqls), sqls)
        self.assertEqual(conn.commits, 1)
        self.assertTrue(conn.closed)

    def test_disconnected_exits_1_and_records_failure_heartbeat_only(self):
        def http(method, path, payload=None):
            return {'session': 'uat', 'connected': False, 'account': None,
                    'data': None, 'as_of': '2026-08-25T10:00:00+00:00',
                    'message': 'UAT paper session not connected'}
        rc, gc, conn = self._run_with_http(http)
        self._assert_failure_heartbeat_only(rc, gc, conn)

    def test_http_error_exits_1_and_records_failure_heartbeat_only(self):
        def http(method, path, payload=None):
            raise m.PaperUatSyncError('GET /api/ib/tws/uat/positions failed: boom')
        rc, gc, conn = self._run_with_http(http)
        self._assert_failure_heartbeat_only(rc, gc, conn)


if __name__ == '__main__':
    unittest.main(verbosity=2)
