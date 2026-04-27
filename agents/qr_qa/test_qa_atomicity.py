"""
Regression test for the qa atomicity contract documented in qa_agent.py:
    ONE connection. ONE cursor block. TWO INSERTs. ONE commit().

This test MOCKS the database layer entirely — no psycopg2 needed at runtime.
It also avoids importing qa_agent's transitive deps (hub.sdk, RealDictCursor)
by importing the method via a lightweight wrapper.

Run: `python3 agents/qr_qa/test_qa_atomicity.py`
"""

from __future__ import annotations

import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ─── Mock the DB layer ────────────────────────────────────────────────────

class MockCursor:
    def __init__(self, conn):
        self.connection = conn   # this is the property the atomicity guard reads
        self.executions = []     # list of (sql, params)
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._closed = True
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql.strip().split()[0:3], params))


class MockConn:
    def __init__(self):
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.cursor_calls = 0
        self._cursor = None

    def cursor(self):
        # Return the SAME cursor each time so we can verify the atomicity guard.
        self.cursor_calls += 1
        if self._cursor is None:
            self._cursor = MockCursor(self)
        return self._cursor

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.close_count += 1


class MockHub:
    """Just enough to satisfy `self.hub._get_conn()` in qa_agent."""
    def __init__(self):
        self.last_conn = None

    def _get_conn(self):
        self.last_conn = MockConn()
        return self.last_conn


# ─── Stub the heavy modules qa_agent imports ──────────────────────────────

def _install_stubs():
    """Install stub modules so qa_agent can import without psycopg2 / hub.sdk."""
    if 'psycopg2' not in sys.modules:
        sys.modules['psycopg2'] = types.ModuleType('psycopg2')
    if 'psycopg2.extras' not in sys.modules:
        m = types.ModuleType('psycopg2.extras')
        m.RealDictCursor = object  # placeholder — qa_agent only references it in cursor_factory=
        sys.modules['psycopg2.extras'] = m

    if 'hub' not in sys.modules:
        hub_pkg = types.ModuleType('hub')
        hub_pkg.__path__ = []  # pretend it's a package
        sys.modules['hub'] = hub_pkg
    if 'hub.router' not in sys.modules:
        m = types.ModuleType('hub.router')
        class _StubHubRouter:
            pass
        m.HubRouter = _StubHubRouter
        m.Event = object
        m.get_hub = lambda: MockHub()
        sys.modules['hub.router'] = m
    if 'hub.sdk' not in sys.modules:
        m = types.ModuleType('hub.sdk')
        class _StubAgent:
            def __init__(self, *a, **kw):
                self.hub = MockHub()
            def emit_event(self, **kw):
                return 'mocked_event_id'
        class _RetryableError(Exception):
            pass
        m.Agent = _StubAgent
        m.Event = object
        m.RetryableError = _RetryableError
        sys.modules['hub.sdk'] = m


_install_stubs()
from agents.qr_qa.qa_agent import QAAgent  # noqa: E402


# ─── The test cases ───────────────────────────────────────────────────────

def _build_qa(hub: MockHub) -> QAAgent:
    a = object.__new__(QAAgent)  # bypass Agent.__init__
    a.hub = hub
    a.agent_name = 'qr_qa'
    a.domain = 'quant'
    a._log = lambda msg: None  # silence agent logs in test output
    return a


def test_atomicity_uses_single_conn_single_cursor_single_commit():
    hub = MockHub()
    agent = _build_qa(hub)

    metrics = {'sharpe_oos': 1.1, 'max_drawdown': -0.12, 'trade_count_oos': 50,
               'trade_count_is': 120, 'sharpe_ratio_is_oos': 0.9}
    new_id = agent._write_lineage_and_emit(
        event_id='source-evt-1',
        strategy_id='s-001',
        experiment_id='e-001',
        metrics=metrics,
        risk_score=0.0,
        param_set={'strategy_type': 'momentum'},
        gate_result={'passed': True, 'failed_gate': None, 'rejection_reason': None},
    )

    conn = hub.last_conn
    assert conn is not None, "agent should have requested a connection"
    assert conn.cursor_calls >= 1, "cursor must be opened"
    assert conn.commit_count == 1, f"exactly one commit expected, got {conn.commit_count}"
    assert conn.rollback_count == 0, "no rollback on the happy path"
    assert conn.close_count == 1, "connection must be closed in finally"

    cur = conn._cursor
    # Both INSERTs must have run on the same cursor.
    assert len(cur.executions) == 2, f"expected 2 INSERTs, got {len(cur.executions)}"
    sql_keywords = [tuple(ex[0]) for ex in cur.executions]
    assert sql_keywords[0] == ('INSERT', 'INTO', 'openclaw_researcher.strategy_lineage'.split('.')[0]) \
           or sql_keywords[0][0] == 'INSERT', "first statement must be an INSERT"
    assert sql_keywords[1][0] == 'INSERT', "second statement must be an INSERT"

    # The atomicity guard verified cursor.connection is conn — confirm the test
    # cursor really exposes that property.
    assert cur.connection is conn

    # Sanity: a fresh uuid was generated and returned.
    assert isinstance(new_id, str) and len(new_id) > 0


def test_atomicity_rollback_on_inner_exception():
    """If the second INSERT fails, the whole transaction rolls back. No commit."""
    hub = MockHub()
    agent = _build_qa(hub)

    # Patch the cursor so the second execute() raises.
    original_get_conn = hub._get_conn

    class ExplosiveCursor(MockCursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if len(self.executions) == 2:
                raise RuntimeError("DB blew up mid-transaction")

    class ExplosiveConn(MockConn):
        def cursor(self):
            self.cursor_calls += 1
            if self._cursor is None:
                self._cursor = ExplosiveCursor(self)
            return self._cursor

    def explosive_get_conn():
        c = ExplosiveConn()
        hub.last_conn = c
        return c

    hub._get_conn = explosive_get_conn

    raised = False
    try:
        agent._write_lineage_and_emit(
            event_id='evt-2', strategy_id='s-002', experiment_id='e-002',
            metrics={'sharpe_oos': 1.0, 'max_drawdown': -0.10, 'trade_count_oos': 40,
                     'trade_count_is': 100, 'sharpe_ratio_is_oos': 0.9},
            risk_score=0.0, param_set={'strategy_type': 'momentum'},
            gate_result={'passed': True, 'failed_gate': None, 'rejection_reason': None},
        )
    except RuntimeError:
        raised = True

    hub._get_conn = original_get_conn

    assert raised, "expected RuntimeError to propagate"
    conn = hub.last_conn
    assert conn.commit_count == 0, "no commit should run if any INSERT raises"
    assert conn.rollback_count == 1, "rollback must run exactly once on failure"
    assert conn.close_count == 1, "connection must still be closed in finally"


def test_atomicity_guard_rejects_mismatched_cursor():
    """
    If a future refactor accidentally uses a cursor bound to a different
    connection, the assert in _write_lineage_and_emit fires before any
    INSERT runs.
    """
    hub = MockHub()
    agent = _build_qa(hub)

    class WrongConnCursor(MockCursor):
        def __init__(self, conn):
            super().__init__(conn)
            # Lie: claim to belong to a different connection.
            self.connection = MockConn()

    class CursorMismatchConn(MockConn):
        def cursor(self):
            self.cursor_calls += 1
            if self._cursor is None:
                self._cursor = WrongConnCursor(self)
            return self._cursor

    def bad_get_conn():
        c = CursorMismatchConn()
        hub.last_conn = c
        return c

    hub._get_conn = bad_get_conn

    raised = False
    try:
        agent._write_lineage_and_emit(
            event_id='evt-3', strategy_id='s-003', experiment_id='e-003',
            metrics={'sharpe_oos': 1.0, 'max_drawdown': -0.10, 'trade_count_oos': 40,
                     'trade_count_is': 100, 'sharpe_ratio_is_oos': 0.9},
            risk_score=0.0, param_set={'strategy_type': 'momentum'},
            gate_result={'passed': True, 'failed_gate': None, 'rejection_reason': None},
        )
    except AssertionError as e:
        raised = True
        assert 'atomicity' in str(e).lower() or 'connection' in str(e).lower()

    assert raised, "expected AssertionError when cursor.connection ≠ conn"
    conn = hub.last_conn
    assert conn.commit_count == 0, "no commit allowed when atomicity guard fires"
    # rollback runs because the assert is caught by the except-and-rollback path.
    assert conn.rollback_count == 1


def _main():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    _main()
