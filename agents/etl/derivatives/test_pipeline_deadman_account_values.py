#!/usr/bin/env python3
"""
Acceptance test for the account-value deadman in pipeline_deadman.py
(kanban t_5cac69f2, currency audit 2026-10-09).

Replays synthetic states through check_account_values() (pure check logic,
no DB) and asserts:
  1. normal state                                -> no alerts
  2. 7.8x day-over-day NAV jump (HKD/USD sig)    -> ACCT NAV JUMP alert
  3. stale bronze + gold account summary         -> staleness alerts
  4. HKD value labeled USD (2026-10-02 incident) -> ACCT CURRENCY MISLABEL
  5. NULL currency on positions / summary        -> ACCT CURRENCY NULL alerts
  6. summary net_liq vs NAV diverging > tol      -> ACCT UNIT MISMATCH
  7. empty tables                                -> ACCT ... EMPTY alerts

Run: /usr/bin/python3 -m pytest test_pipeline_deadman_account_values.py -q
  or /usr/bin/python3 test_pipeline_deadman_account_values.py
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline_deadman as pd_


NOW = datetime(2026, 10, 13, 1, 0, tzinfo=timezone.utc)  # Tue 01:00 UTC
WEEKDAY = NOW.date().weekday()  # 1 -> staleness enforced
TODAY = NOW.date()


def base_state():
    """Normal, healthy state modeled on live 2026-10-09 data."""
    return {
        'bronze_summary': {
            'account': 'DUP825942', 'net_liquidation': 248012.53,
            'fetched_at': datetime(2026, 10, 13, 0, 0)},          # 1h old
        'gold_summary': {
            'account': 'DUP825942', 'net_liquidation': 247459.00,
            'fetched_at': datetime(2026, 10, 12, 8, 30)},         # 16.5h old
        'gold_summary_cols': {'account', 'net_liquidation', 'cash_hkd', 'cash_usd',
                              'available_funds', 'buying_power', 'position_count',
                              'fetched_at'},
        'gold_summary_ccy_col': None,   # pre-conversion-layer: no label column
        'gold_summary_ccy': None,
        'nav_live': [
            {'as_of_date': TODAY - timedelta(days=1), 'equity': 251212.30},
            {'as_of_date': TODAY - timedelta(days=2), 'equity': 251050.36},
        ],
        'positions_null_ccy': 0,
        'fx': {'date': TODAY - timedelta(days=1), 'close': 7.8473},
    }


def run(state):
    pd_.ALERTS.clear()
    pd_.check_account_values(state, NOW, WEEKDAY)
    return list(pd_.ALERTS)


def test_normal_state_silent():
    alerts = run(base_state())
    assert alerts == [], f"normal state must be silent, got: {alerts}"


def test_7_8x_nav_jump_alerts():
    st = base_state()
    st['nav_live'] = [
        {'as_of_date': TODAY - timedelta(days=1), 'equity': 248352.89 * 7.8},
        {'as_of_date': TODAY - timedelta(days=2), 'equity': 248352.89},
    ]
    alerts = run(st)
    assert any('ACCT NAV JUMP' in a and '+680.0%' in a for a in alerts), alerts


def test_stale_summaries_alert():
    st = base_state()
    st['bronze_summary']['fetched_at'] = datetime(2026, 10, 10, 0, 0)  # 73h
    st['gold_summary']['fetched_at'] = datetime(2026, 10, 9, 8, 30)     # 88.5h
    alerts = run(st)
    assert any('ACCT SUMMARY STALE: bronze' in a for a in alerts), alerts
    assert any('ACCT SUMMARY STALE: gold' in a for a in alerts), alerts


def test_hkd_labeled_usd_alerts():
    """The 2026-10-02 incident: 248,714 HKD NetLiq carried with a USD label."""
    st = base_state()
    st['gold_summary']['net_liquidation'] = 248714.0   # HKD figure...
    st['gold_summary_ccy_col'] = 'currency'            # ...labeled USD
    st['gold_summary_ccy'] = 'USD'
    st['bronze_summary']['net_liquidation'] = 248714.0
    # keep cross-source check quiet so the mislabel alert is attributable
    st['nav_live'] = [
        {'as_of_date': TODAY - timedelta(days=1), 'equity': 248714.0},
        {'as_of_date': TODAY - timedelta(days=2), 'equity': 248700.0},
    ]
    alerts = run(st)
    assert any('ACCT CURRENCY MISLABEL' in a for a in alerts), alerts


def test_null_currency_alerts():
    st = base_state()
    st['positions_null_ccy'] = 3
    st['gold_summary_ccy_col'] = 'currency'
    st['gold_summary_ccy'] = None
    alerts = run(st)
    assert any('ACCT CURRENCY NULL: 3 gold.ibkr_positions_live' in a for a in alerts), alerts
    assert any('ACCT CURRENCY NULL: gold.ibkr_account_summary' in a for a in alerts), alerts


def test_unit_mismatch_cross_source_alerts():
    st = base_state()
    st['gold_summary']['net_liquidation'] = 251212.30 * 7.8  # HKD figure vs HKD NAV
    alerts = run(st)
    assert any('ACCT UNIT MISMATCH' in a for a in alerts), alerts


def test_empty_tables_alert():
    st = base_state()
    st['bronze_summary'] = None
    st['gold_summary'] = None
    st['nav_live'] = []
    alerts = run(st)
    assert any('ACCT SUMMARY EMPTY: bronze' in a for a in alerts), alerts
    assert any('ACCT SUMMARY EMPTY: gold' in a for a in alerts), alerts
    assert any('ACCT NAV EMPTY' in a for a in alerts), alerts


def test_weekend_morning_exempt_from_staleness():
    """Sun/Mon 01:00 UTC: last scheduled write was Friday -> stale-age OK."""
    st = base_state()
    st['bronze_summary']['fetched_at'] = datetime(2026, 10, 10, 0, 0)   # Fri
    st['gold_summary']['fetched_at'] = datetime(2026, 10, 9, 8, 30)     # Fri
    sun = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)             # Sun
    pd_.ALERTS.clear()
    pd_.check_account_values(st, sun, sun.date().weekday())             # 6
    assert not any('STALE' in a for a in pd_.ALERTS), list(pd_.ALERTS)


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
