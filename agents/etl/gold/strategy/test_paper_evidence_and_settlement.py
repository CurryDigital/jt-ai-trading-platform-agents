#!/usr/bin/env python3
"""DB-free regressions for Paper evidence separation and settlement invariants.

Covers the 2026-11-13 repair batch:
1. historical replay rows are explicitly separated from forward Paper rows;
2. a failed PAPER_UAT fire restores the cadence marker instead of consuming
   the period;
3. a pending CLOSE is marked filled only after exactly one position row was
   actually closed.

Run: python test_paper_evidence_and_settlement.py
Exit 0 = all assertions pass. No database required.
"""
import os
import sys
from datetime import date
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL = os.path.normpath(os.path.join(_HERE, '..', '..'))
sys.path.insert(0, _HERE)

import rebuild_paper_positions as rpp  # noqa: E402
import refresh_paper_trades_synthetic as replay  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


class SettlementCursor:
    def __init__(self, close_rowcount, mark_rowcount=1):
        self.close_rowcount = close_rowcount
        self.mark_rowcount = mark_rowcount
        self.rowcount = 0
        self.mark_calls = 0
        self.close_calls = 0
        self._orders = [(
            42, 'test_strategy', 'AAA', 'CLOSE', date(2026, 11, 10), 7,
            100, 1.0, 10000.0, 60.0,
        )]

    def execute(self, sql, params=None):
        normalized = ' '.join(str(sql).split()).upper()
        if normalized.startswith('UPDATE GOLD.PAPER_TRADES_SYNTHETIC'):
            self.close_calls += 1
            self.rowcount = self.close_rowcount
        elif normalized.startswith('UPDATE GOLD.PAPER_PENDING_ORDERS'):
            self.mark_calls += 1
            self.rowcount = self.mark_rowcount
        else:
            self.rowcount = 0

    def fetchall(self):
        orders, self._orders = self._orders, []
        return orders


class RebalanceStateCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((' '.join(str(sql).split()).upper(), params))


def test_close_settlement_requires_position_row():
    print("test_close_settlement_requires_position_row")
    cur = SettlementCursor(close_rowcount=0)
    with patch.object(rpp, 'fetch_fill_bar',
                      return_value=(date(2026, 11, 11), 101.0, 100.0, 'US')), \
         patch.object(rpp, 'bar_is_final', return_value=True), \
         patch.object(rpp, 'resolve_cost_bps', return_value=0.0):
        try:
            rpp.settle_pending_orders(cur, date(2026, 11, 12), ['test_strategy'])
        except RuntimeError as exc:
            check("zero-row close raises before marking the order filled",
                  'refusing to mark filled' in str(exc), str(exc))
        else:
            check("zero-row close raises before marking the order filled", False)
    check("failed close never marks the pending order filled", cur.mark_calls == 0)

    cur = SettlementCursor(close_rowcount=1, mark_rowcount=1)
    with patch.object(rpp, 'fetch_fill_bar',
                      return_value=(date(2026, 11, 11), 101.0, 100.0, 'US')), \
         patch.object(rpp, 'bar_is_final', return_value=True), \
         patch.object(rpp, 'resolve_cost_bps', return_value=0.0):
        result = rpp.settle_pending_orders(cur, date(2026, 11, 12), ['test_strategy'])
    check("one-row close marks exactly one order filled",
          result['filled_close'] == 1 and cur.close_calls == 1 and cur.mark_calls == 1,
          f"result={result} close_calls={cur.close_calls} mark_calls={cur.mark_calls}")


def test_cadence_restore_helper():
    print("test_cadence_restore_helper")
    cur = RebalanceStateCursor()
    prior = {
        'frequency': 'monthly',
        'last_period_key': 'M:2026-10',
        'last_rebalance_date': date(2026, 10, 1),
        'seeded': False,
    }
    rpp.restore_rebalance_state(cur, 'test_strategy', prior)
    check("existing cadence state is restored by upsert",
          len(cur.calls) == 1
          and cur.calls[0][0].startswith('INSERT INTO GOLD.STRATEGY_REBALANCE_STATE')
          and cur.calls[0][1][:4] == (
              'test_strategy', 'monthly', 'M:2026-10', date(2026, 10, 1)),
          f"calls={cur.calls}")

    cur = RebalanceStateCursor()
    rpp.restore_rebalance_state(cur, 'test_strategy', None)
    check("newly seeded state is deleted when the first fire fails",
          len(cur.calls) == 1
          and cur.calls[0][0].startswith('DELETE FROM GOLD.STRATEGY_REBALANCE_STATE'),
          f"calls={cur.calls}")

    src = open(os.path.join(_HERE, 'rebuild_paper_positions.py')).read()
    catch_at = src.index('except PaperUatFireError as e:')
    restore_at = src.index('restore_rebalance_state(cur, sid, prior_rebalance_state)', catch_at)
    summary_at = src.index("uat_failures += 1", catch_at)
    check("PAPER_UAT catch restores cadence before recording the failure",
          catch_at < restore_at < summary_at)


def test_evidence_class_writer_contracts():
    print("test_evidence_class_writer_contracts")
    migration_path = os.path.join(
        _ETL, 'migrations', '2026-11-13_paper_evidence_class.sql')
    migration = open(migration_path).read()
    for token in (
        "ADD COLUMN IF NOT EXISTS evidence_class TEXT",
        "'forward_paper', 'historical_replay', 'legacy_unclassified'",
        "r.feeder = 'refresh_paper_trades_synthetic'",
        "pts.evidence_class = 'forward_paper'",
        "t.evidence_class = 'forward_paper'",
        "paper_trades_synthetic.evidence_class = 'forward_paper'",
    ):
        check(f"migration contains {token}", token in migration)

    check("forward engine stamps forward_paper on inserted positions",
          'evidence_class' in rpp.SQL_OPEN_POSITIONS
          and "'forward_paper'" in open(os.path.join(
              _HERE, 'rebuild_paper_positions.py')).read())
    check("replay feeder stamps historical_replay on closed candidates",
          'evidence_class' in replay.sql_upsert_closed('gold.paper_trades_synthetic')
          and "'historical_replay'" in replay.sql_upsert_closed('gold.paper_trades_synthetic'))
    check("replay feeder stamps historical_replay on open candidates",
          'evidence_class' in replay.sql_upsert_open('gold.paper_trades_synthetic')
          and "'historical_replay'" in replay.sql_upsert_open('gold.paper_trades_synthetic'))
    check("replay schema guard requires evidence_class",
          "'evidence_class'" in replay.SQL_SCHEMA_GUARD
          and '2026-11-13_paper_evidence_class.sql' in open(
              os.path.join(_HERE, 'refresh_paper_trades_synthetic.py')).read())

    consumers = (
        os.path.join(_ETL, 'consumption', 'portfolio', 'sync_paper_positions_current.py'),
        os.path.join(_ETL, 'consumption', 'portfolio', 'portfolio_performance_attribution.py'),
        os.path.join(_HERE, 'sync_registry_in_market_capital.py'),
    )
    for path in consumers:
        src = open(path).read()
        check(f"{os.path.basename(path)} consumes forward Paper only",
              "evidence_class = 'forward_paper'" in src
              or "p.evidence_class = 'forward_paper'" in src)

    history_backfill = open(os.path.join(
        _HERE, 'backfill_paper_trades_from_history.py')).read()
    simulation_ingest = open(os.path.join(
        _ETL, 'workspace', 'oneoff',
        'ingest_hk_quality_bluechips_simulation_t_4f4e43d1.py')).read()
    check("history repair writer is labelled historical replay",
          "'historical_replay'" in history_backfill)
    check("one-off simulation ingest is labelled historical replay",
          "'historical_replay'" in simulation_ingest)


if __name__ == '__main__':
    test_close_settlement_requires_position_row()
    test_cadence_restore_helper()
    test_evidence_class_writer_contracts()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
