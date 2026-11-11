#!/usr/bin/env python3
"""Unit test: signal-staleness guard for the paper rebalancer (kanban t_6d1ddfe8).

SUE incident 2026-10: us_stk_sue_mom_01_v2's October signal file
(signal_date=2026-09-30) was generated 2026-10-17, 16 days late. The engine
fired the 10-01 rebalance on STALE August targets (bought AVGO, not an
October target), then CADENCE_GATE-skipped all 20 true October targets
('period M:2026-10 already rebalanced'). The book diverged from the strategy
for a full month, silently.

The guard fails closed: at a scheduled (gated) rebalance on an ingested
strategy, if the signal file's evidence date (signal_date, else computed_at)
is older than the last trading day of the prior cadence period, the rebalance
is BLOCKED — zero trades, book held, rebalance state NOT touched (period
stays open, auto re-fires when a fresh file lands), and exactly ONE
operator-visible SIGNAL_STALE alert row (ticker='*') is surfaced.

Covers:
- infer_home_market(): suffix majority, US default.
- prior_period_last_trading_day(): monthly/weekly math, weekend + holiday
  walk-back.
- signal_freshness_verdict(): stale/fresh/None-evidence (fail closed).
- SUE incident replay: today=2026-10-01, evidence=2026-08-31 -> stale.
- rebalance_strategy(stale_block=True): zero trades, no mutating SQL, exactly
  one SIGNAL_STALE skip row (ticker='*'), no CADENCE_GATE rows.

Run:  python test_rebuild_paper_positions_signal_staleness.py
Exit 0 = all assertions pass. Pure-python, no DB required.
"""
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from rebuild_paper_positions import (  # noqa: E402
    infer_home_market,
    prior_period_last_trading_day,
    signal_freshness_verdict,
    rebalance_strategy,
)

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


def test_market_inference():
    print("test_market_inference")
    check("bare tickers -> US", infer_home_market(['AAPL', 'MSFT', 'AVGO']) == 'US')
    check(".HK majority -> HK",
          infer_home_market(['0700.HK', '2388.HK', 'AAPL']) == 'HK')
    check(".SI -> SG", infer_home_market(['D05.SI', 'O39.SI']) == 'SG')
    check(".SS/.SZ -> CN", infer_home_market(['600519.SS', '000001.SZ']) == 'CN')
    check("empty universe -> US default", infer_home_market([]) == 'US')
    check("None universe -> US default", infer_home_market(None) == 'US')
    check("lowercase suffix handled", infer_home_market(['0700.hk', '0005.hk']) == 'HK')


def test_prior_period_last_trading_day():
    print("test_prior_period_last_trading_day")
    # Monthly: 2026-10-01 -> last day of Sep = 2026-09-30 (Wed, trading day).
    check("monthly 10-01 -> 09-30",
          prior_period_last_trading_day('monthly', date(2026, 10, 1), set())
          == date(2026, 9, 30))
    # Monthly weekend walk-back: 2026-11-02 -> Oct 31 is Sat -> Fri 2026-10-30.
    check("monthly 11-02 -> 10-30 (Sat walk-back)",
          prior_period_last_trading_day('monthly', date(2026, 11, 2), set())
          == date(2026, 10, 30))
    # Monthly holiday walk-back: today 2026-09-01, Aug 31 2026 is a Monday —
    # pretend it's a holiday -> expected Fri 2026-08-28.
    check("monthly holiday walk-back",
          prior_period_last_trading_day('monthly', date(2026, 9, 1),
                                        {date(2026, 8, 31)})
          == date(2026, 8, 28))
    # Weekly: Mon 2026-08-17 -> Sunday 08-16 -> walk back to Fri 2026-08-14.
    check("weekly new ISO week -> prior Friday",
          prior_period_last_trading_day('weekly', date(2026, 8, 17), set())
          == date(2026, 8, 14))
    # Weekly mid-week run (missed Monday): Tue 2026-08-18 -> same Friday.
    check("weekly mid-week run same expectation",
          prior_period_last_trading_day('weekly', date(2026, 8, 18), set())
          == date(2026, 8, 14))
    # Labor Day 2026-09-07 (Mon) case: weekly run on Mon 09-07 with Fri 09-04
    # a holiday -> expected Thu 2026-09-03.
    check("weekly holiday walk-back (Labor Day week)",
          prior_period_last_trading_day('weekly', date(2026, 9, 7),
                                        {date(2026, 9, 4)})
          == date(2026, 9, 3))
    # Ungated -> None.
    check("daily -> None (ungated)",
          prior_period_last_trading_day('daily', date(2026, 10, 1), set()) is None)


def test_freshness_verdict():
    print("test_freshness_verdict")
    exp = date(2026, 9, 30)
    fresh, _ = signal_freshness_verdict(date(2026, 9, 30), exp)
    check("evidence == expected -> fresh", fresh)
    fresh, _ = signal_freshness_verdict(date(2026, 10, 5), exp)
    check("evidence > expected -> fresh", fresh)
    fresh, detail = signal_freshness_verdict(date(2026, 8, 31), exp)
    check("evidence < expected -> stale", not fresh, detail)
    fresh, detail = signal_freshness_verdict(None, exp)
    check("no evidence -> stale (fail closed)", not fresh, detail)
    fresh, _ = signal_freshness_verdict(None, None)
    check("ungated expected -> fresh", fresh)


def test_sue_incident_replay():
    print("test_sue_incident_replay (2026-10-01 rebalance, August file)")
    # At the 10-01 rebalance the freshest file evidence was the AUGUST file
    # (signal_date 2026-08-31; the October file only landed 10-17).
    expected = prior_period_last_trading_day('monthly', date(2026, 10, 1), set())
    check("expected prior-period close 2026-09-30", expected == date(2026, 9, 30))
    fresh, detail = signal_freshness_verdict(date(2026, 8, 31), expected)
    check("August evidence at 10-01 -> BLOCK", not fresh, detail)
    # The CURRENT SUE file (signal_date 2026-09-30) at the November rebalance
    # (2026-11-02): expected 2026-10-30 -> still stale -> BLOCK until research
    # ships the November file.
    exp_nov = prior_period_last_trading_day('monthly', date(2026, 11, 2), set())
    fresh, detail = signal_freshness_verdict(date(2026, 9, 30), exp_nov)
    check("current SUE file stale for November rebalance", not fresh, detail)
    # A fresh November file (signal_date 2026-10-30 or later) passes.
    fresh, _ = signal_freshness_verdict(date(2026, 10, 30), exp_nov)
    check("fresh November file passes", fresh)


class _StubConn:
    encoding = 'UTF8'


class _StubCursor:
    """Captures mutating SQL so the blocked path can be asserted DB-free."""
    def __init__(self):
        self.mutating = []
        self.connection = _StubConn()
        self._last_head = ''

    def execute(self, sql, params=None):
        head = ' '.join(str(sql).split())[:40].upper()
        self._last_head = head
        if head.startswith(('UPDATE GOLD.PAPER_TRADES', 'INSERT INTO GOLD.PAPER_TRADES_SYNTHETIC')):
            self.mutating.append(head)
        self.rowcount = 0
        self.description = []

    def mogrify(self, template, args=None):
        return b'()'

    def fetchall(self):
        return []

    def fetchone(self):
        # Deployment writer reads open cost basis (scalar) — answer 0.
        if self._last_head.startswith('SELECT COALESCE(SUM'):
            return (0,)
        return None


def _sue_like_strategy():
    return {
        'strategy_id': 'us_stk_sue_mom_01_v2',
        'name': 'SUE momentum',
        'mode': 'PAPER',
        'capital': 100_000,
        'universe': ['AAA', 'BBB'],
        'frequency': 'monthly',
        'signal_mechanism': 'ingested',
    }


def _bars():
    return {
        'AAA': {'date': date(2026, 9, 30), 'open': 100.0, 'close': 100.0},
        'BBB': {'date': date(2026, 9, 30), 'open': 50.0, 'close': 50.0},
    }


def test_stale_block_zero_trades_alert_row():
    print("test_stale_block_zero_trades_alert_row "
          "(blocked rebalance: zero trades, one SIGNAL_STALE alert row)")
    cur = _StubCursor()
    signals = {'us_stk_sue_mom_01_v2': [
        {'ticker': 'AAA', 'score': 60, 'action': 'BUY'},
        {'ticker': 'BBB', 'score': 40, 'action': 'BUY'},
    ]}
    open_positions = {'us_stk_sue_mom_01_v2': {
        'AAA': {'id': 1, 'direction': 'LONG', 'entry_date': date(2026, 9, 1),
                'entry_price': 100.0, 'n_shares': 100, 'status': 'open'},
    }}
    res = rebalance_strategy(
        cur, date(2026, 10, 1), _sue_like_strategy(),
        prices=_bars(),
        signals=signals, open_positions=open_positions, lots={},
        execute_rebalance=False,
        stale_block=True,
        gate_reason=("SIGNAL_STALE: signal evidence 2026-08-31 older than "
                     "prior-period close 2026-09-30 (expected signal_date >= "
                     "2026-09-30; home calendar US)"),
        max_position_pct=0.0,
    )
    check("zero closes", res['closed'] == 0, f"closed={res['closed']}")
    check("zero opens", res['opened'] == 0, f"opened={res['opened']}")
    check("no position-mutation SQL issued",
          cur.mutating == [], f"mutating SQL: {cur.mutating}")
    check("not marked rebalanced", res.get('rebalanced') is False)
    kinds = [(s['ticker'], s['skip_kind']) for s in res['skipped']]
    check("exactly ONE skip row", len(res['skipped']) == 1, f"skips: {kinds}")
    stale = [s for s in res['skipped'] if s['skip_kind'] == 'SIGNAL_STALE']
    check("skip row is SIGNAL_STALE", len(stale) == 1, f"skips: {kinds}")
    check("alert row ticker is '*'",
          stale and stale[0]['ticker'] == '*')
    check("alert row carries the gate reason",
          stale and 'SIGNAL_STALE' in stale[0]['reason']
          and '2026-09-30' in stale[0]['reason'],
          stale[0]['reason'] if stale else '')
    check("alert row numeric fields NULL-able (no price/score)",
          stale and stale[0]['score'] is None and stale[0]['price'] is None)
    check("no CADENCE_GATE rows on stale block",
          not any(s['skip_kind'] == 'CADENCE_GATE' for s in res['skipped']))


def test_gated_not_stale_unchanged():
    print("test_gated_not_stale_unchanged (plain cadence gate unaffected)")
    cur = _StubCursor()
    signals = {'us_stk_sue_mom_01_v2': [
        {'ticker': 'AAA', 'score': 60, 'action': 'BUY'},
        {'ticker': 'BBB', 'score': 40, 'action': 'BUY'},
    ]}
    res = rebalance_strategy(
        cur, date(2026, 8, 17), _sue_like_strategy(),
        prices=_bars(),
        signals=signals, open_positions={}, lots={},
        execute_rebalance=False,
        stale_block=False,
        gate_reason='period M:2026-08 already rebalanced 2026-08-03',
        max_position_pct=0.0,
    )
    kinds = [s['skip_kind'] for s in res['skipped']]
    check("cadence gate still emits CADENCE_GATE rows",
          'CADENCE_GATE' in kinds and 'SIGNAL_STALE' not in kinds,
          f"kinds: {kinds}")


if __name__ == '__main__':
    test_market_inference()
    test_prior_period_last_trading_day()
    test_freshness_verdict()
    test_sue_incident_replay()
    test_stale_block_zero_trades_alert_row()
    test_gated_not_stale_unchanged()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
