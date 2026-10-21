"""Regression tests for the delta-mode deployment clamp (kanban t_5f69e8c0).

rebuild_paper_positions.clamp_new_opens must size NEW entries against the
budget remaining after retained positions' cost basis, so the paper book's
open cost basis can never exceed the deployable budget (and therefore never
exceed assigned capital). Reproduces the us_stk_sue_mom_01_v2 over-deployment:
a near-full 8/5 book (399,538 of 400k) plus fresh BUY signals whose
compute_target slots assumed an empty book -> 464,530.80 in-market.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rebuild_paper_positions import clamp_new_opens, deployable_budget  # noqa: E402


def tgt(ticker, shares, price, score=50.0, weight=0.25):
    return {'ticker': ticker, 'shares': shares, 'price': price,
            'score': score, 'weight': weight}


class TestDeployableBudget(unittest.TestCase):
    def test_no_cash_signal_full_capital(self):
        signals = [{'ticker': 'A', 'action': 'BUY', 'score': 50},
                   {'ticker': 'B', 'action': 'BUY', 'score': 50}]
        self.assertAlmostEqual(deployable_budget(signals, 400_000), 400_000)

    def test_cash_residual_respected(self):
        signals = [{'ticker': 'A', 'action': 'BUY', 'score': 90},
                   {'ticker': 'CASH', 'action': 'HOLD', 'score': 10}]
        self.assertAlmostEqual(deployable_budget(signals, 400_000), 360_000)

    def test_all_hold_zero_budget(self):
        signals = [{'ticker': 'A', 'action': 'HOLD', 'score': 50}]
        self.assertEqual(deployable_budget(signals, 400_000), 0.0)


class TestClampNewOpens(unittest.TestCase):
    def test_full_book_gates_new_entries(self):
        # us_stk_sue_mom_01_v2 repro: retained 399,538 of 400k budget ->
        # AVGO (364.25/share) fits 1 share, CIEN gets nothing.
        targets = [tgt('AVGO', 106, 364.25), tgt('CIEN', 70, 376.89)]
        clamped, skips = clamp_new_opens(targets, set(), 399_538.0, 400_000.0, {})
        by_ticker = {t['ticker']: t['shares'] for t in clamped}
        self.assertEqual(by_ticker, {'AVGO': 1})
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]['ticker'], 'CIEN')
        self.assertEqual(skips[0]['skip_kind'], 'OVER_DEPLOYED')
        total_new = sum(t['shares'] * float(t['price']) for t in clamped)
        self.assertLessEqual(399_538.0 + total_new, 400_000.0)

    def test_empty_book_passes_targets_through(self):
        targets = [tgt('A', 100, 10.0), tgt('B', 200, 20.0)]
        clamped, skips = clamp_new_opens(targets, set(), 0.0, 100_000.0, {})
        self.assertEqual({t['ticker']: t['shares'] for t in clamped},
                         {'A': 100, 'B': 200})
        self.assertEqual(skips, [])

    def test_held_tickers_untouched(self):
        targets = [tgt('HELD', 500, 10.0), tgt('NEW', 100, 10.0)]
        clamped, skips = clamp_new_opens(targets, {'HELD'}, 5_000.0, 6_000.0, {})
        by_ticker = {t['ticker']: t['shares'] for t in clamped}
        self.assertEqual(by_ticker['HELD'], 500)  # not resized
        self.assertEqual(by_ticker['NEW'], 100)   # fits in remaining 1,000
        self.assertEqual(skips, [])

    def test_partial_right_size_floors_to_lots(self):
        # HK lot size 100: remaining 2,500 -> 2 lots (200 shares), not 250.
        lots = {'0700.HK': 100}
        targets = [tgt('0700.HK', 1000, 10.0)]
        clamped, skips = clamp_new_opens(targets, set(), 97_500.0, 100_000.0, lots)
        self.assertEqual(clamped[0]['shares'], 200)
        self.assertEqual(skips, [])

    def test_pending_open_consumes_budget(self):
        # Resting pending OPEN for PEND debits the budget so NEW is gated.
        targets = [tgt('PEND', 900, 10.0), tgt('NEW', 100, 10.0)]
        clamped, skips = clamp_new_opens(targets, set(), 0.0, 10_000.0, {},
                                         pend_open_tickers=frozenset({'PEND'}))
        by_ticker = {t['ticker']: t['shares'] for t in clamped}
        self.assertEqual(by_ticker, {'PEND': 900, 'NEW': 100})
        # 9,000 debited for PEND, 1,000 left -> NEW fits exactly.
        self.assertEqual(skips, [])

    def test_pending_open_then_over_deployed(self):
        targets = [tgt('PEND', 900, 10.0), tgt('NEW', 500, 10.0)]
        clamped, skips = clamp_new_opens(targets, set(), 0.0, 10_000.0, {},
                                         pend_open_tickers=frozenset({'PEND'}))
        by_ticker = {t['ticker']: t['shares'] for t in clamped}
        self.assertEqual(by_ticker, {'PEND': 900, 'NEW': 100})
        self.assertEqual(skips, [])  # NEW right-sized to remaining 1,000

    def test_cn_lowvol_repro(self):
        # cn_stk_lowvol_12 repro: retained 92,736 of 100k; new 000001.SZ
        # (CN lot 100 @ 11.54) gets 600 shares, 600519.SS (lot 100 @
        # 1,302.80 = 130k/lot) is OVER_DEPLOYED.
        lots = {'000001.SZ': 100, '600519.SS': 100}
        targets = [tgt('000001.SZ', 843, 11.54), tgt('600519.SS', 7, 1302.80)]
        clamped, skips = clamp_new_opens(targets, set(), 92_736.0, 100_000.0, lots)
        by_ticker = {t['ticker']: t['shares'] for t in clamped}
        self.assertEqual(by_ticker, {'000001.SZ': 600})
        self.assertEqual([s['ticker'] for s in skips], ['600519.SS'])
        total_new = sum(t['shares'] * float(t['price']) for t in clamped)
        self.assertLessEqual(92_736.0 + total_new, 100_000.0)


if __name__ == '__main__':
    unittest.main()
