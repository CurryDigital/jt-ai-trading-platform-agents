#!/usr/bin/env python3
"""Unit test: 20% single-position concentration cap in the paper rebalancer.

Covers kanban t_569c181f: compute_target() in rebuild_paper_positions.py must
cap any single ticker at max_position_pct (default 20%) of assigned capital
BEFORE the residual-cash round-robin, skip capped tickers in the round-robin
(trying the next ticker), and log CONCENTRATION_CAP skips.

Primary fixture: etf_comm_trend_basket_15 at $225k assigned capital. Expected:
DBC notional <= $45,000 (20% of $225k). Before the fix the rebalancer bought
1,800 DBC shares = $50,958 (22.65% of capital).

Run:  python test_rebuild_paper_positions_concentration_cap.py
Exit 0 = all assertions pass. Pure-python, no DB required.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from rebuild_paper_positions import compute_target  # noqa: E402


FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


def basket15_signals():
    """etf_comm_trend_basket_15 scores at 2026-08-05 (batch12 audit figures)."""
    return [
        {'ticker': 'DBC',  'score': 20.19, 'action': 'BUY'},
        {'ticker': 'GLD',  'score': 16.76, 'action': 'BUY'},
        {'ticker': 'SLV',  'score': 9.24,  'action': 'BUY'},
        {'ticker': 'USO',  'score': 8.05,  'action': 'BUY'},
        {'ticker': 'CASH', 'score': 45.76, 'action': 'HOLD'},
    ]


BASKET15_PRICES = {'DBC': 28.31, 'GLD': 374.16, 'SLV': 53.84, 'USO': 115.78}
BASKET15_CAPITAL = 225_000


def by_ticker(targets):
    return {t['ticker']: t for t in targets}


def test_incident_fixture_capped():
    """Core requirement: DBC notional <= $45,000 at $225k with default cap."""
    print("test_incident_fixture_capped (etf_comm_trend_basket_15 @ $225k, default 20% cap)")
    targets, skipped = compute_target(
        basket15_signals(), BASKET15_CAPITAL, BASKET15_PRICES, lots={})
    tgt = by_ticker(targets)

    dbc = tgt.get('DBC')
    check("DBC position exists", dbc is not None)
    if dbc:
        notional = dbc['shares'] * dbc['price']
        check("DBC notional <= $45,000 (20% of $225k)",
              notional <= 45_000 + 1e-6,
              f"DBC {dbc['shares']} sh @ {dbc['price']} = ${notional:,.2f} "
              f"({notional / BASKET15_CAPITAL:.2%} of capital)")
    for leg in ('GLD', 'SLV', 'USO'):
        check(f"{leg} position exists (4-leg basket preserved)", leg in tgt)

    cap_skips = [s for s in skipped if s['skip_kind'] == 'CONCENTRATION_CAP']
    check("CONCENTRATION_CAP skip logged for DBC",
          any(s['ticker'] == 'DBC' for s in cap_skips),
          f"cap skips: {[(s['ticker'], s['reason'][:60]) for s in cap_skips]}")
    check("no duplicate skip rows per ticker",
          len({s['ticker'] for s in skipped}) == len(skipped),
          f"skips: {[(s['ticker'], s['skip_kind']) for s in skipped]}")

    # Residual round-robin must try the NEXT ticker when DBC is capped:
    # SLV slot buys 300sh; uncapped residual deployment adds whole lots.
    slv = tgt.get('SLV')
    if slv:
        check("residual cash flowed past capped DBC to next ticker (SLV > 300sh)",
              slv['shares'] > 300, f"SLV {slv['shares']} sh")
    # No position may exceed the cap.
    for t in targets:
        n = t['shares'] * t['price']
        check(f"{t['ticker']} under cap", n <= 45_000 + 1e-6,
              f"${n:,.2f}")


def test_pre_fix_behavior_reproduced():
    """Sanity: with the cap disabled, the fixture reproduces incident-era DBC
    concentration above the 20% line (whole-share convention t_928a4e7d:
    DBC pro-rata lands at ~$45.5k = 20.2% — still over the $45k cap the fix
    enforces; the exact 100-share-lot figure $50,958 no longer applies)."""
    print("test_pre_fix_behavior_reproduced (cap disabled)")
    targets, skipped = compute_target(
        basket15_signals(), BASKET15_CAPITAL, BASKET15_PRICES, lots={},
        max_position_pct=0)
    dbc = by_ticker(targets)['DBC']
    notional = dbc['shares'] * dbc['price']
    check("cap disabled: DBC concentrates above the 20% cap line",
          notional > 45_000 and notional / BASKET15_CAPITAL > 0.20,
          f"DBC {dbc['shares']} sh = ${notional:,.2f} "
          f"({notional / BASKET15_CAPITAL:.2%} of capital)")
    check("no CONCENTRATION_CAP skips when disabled",
          not any(s['skip_kind'] == 'CONCENTRATION_CAP' for s in skipped))


def test_custom_cap():
    """Configurable: 10% cap binds DBC at <= $22,500."""
    print("test_custom_cap (10%)")
    targets, skipped = compute_target(
        basket15_signals(), BASKET15_CAPITAL, BASKET15_PRICES, lots={},
        max_position_pct=0.10)
    for t in targets:
        n = t['shares'] * t['price']
        check(f"{t['ticker']} under 10% cap", n <= 22_500 + 1e-6, f"${n:,.2f}")


def test_cap_below_one_lot():
    """Edge: cap smaller than one share -> zero-size position, explicit
    CONCENTRATION_CAP skip, no zero-share target row.

    Lot convention (t_928a4e7d): US equities size in whole shares (lot=1),
    so 'below one lot' now means below ONE SHARE. 0.04% of $100k = $40 is
    below 1 share of both GLD ($374.16) and SLV ($53.84)."""
    print("test_cap_below_one_lot")
    signals = [
        {'ticker': 'GLD', 'score': 50.0, 'action': 'BUY'},
        {'ticker': 'SLV', 'score': 50.0, 'action': 'BUY'},
    ]
    prices = {'GLD': 374.16, 'SLV': 53.84}
    targets, skipped = compute_target(
        signals, 100_000, prices, lots={}, max_position_pct=0.0004)
    tgt = by_ticker(targets)
    check("GLD capped to zero (no target row)", 'GLD' not in tgt)
    check("SLV capped to zero (no target row)", 'SLV' not in tgt)
    check("both logged as CONCENTRATION_CAP",
          {s['ticker'] for s in skipped if s['skip_kind'] == 'CONCENTRATION_CAP'}
          == {'GLD', 'SLV'},
          f"skips: {[(s['ticker'], s['skip_kind']) for s in skipped]}")
    check("no zero-share target rows", all(t['shares'] > 0 for t in targets))


def test_no_cap_breach_no_skip():
    """A book already under the cap gets no CONCENTRATION_CAP rows."""
    print("test_no_cap_breach_no_skip")
    signals = [
        {'ticker': 'AAA', 'score': 10.0, 'action': 'BUY'},
        {'ticker': 'BBB', 'score': 10.0, 'action': 'BUY'},
        {'ticker': 'CCC', 'score': 10.0, 'action': 'BUY'},
        {'ticker': 'DDD', 'score': 10.0, 'action': 'BUY'},
        {'ticker': 'EEE', 'score': 10.0, 'action': 'BUY'},
    ]
    prices = {t: 10.0 for t in ('AAA', 'BBB', 'CCC', 'DDD', 'EEE')}
    targets, skipped = compute_target(signals, 500_000, prices, lots={})
    check("no CONCENTRATION_CAP skips",
          not any(s['skip_kind'] == 'CONCENTRATION_CAP' for s in skipped))
    for t in targets:
        n = t['shares'] * t['price']
        check(f"{t['ticker']} under 20% cap", n <= 100_000 + 1e-6, f"${n:,.2f}")


def test_resolve_max_position_pct():
    """Per-strategy override (gold.strategy_configs) wins; absent -> default."""
    print("test_resolve_max_position_pct")
    from rebuild_paper_positions import resolve_max_position_pct
    overrides = {'etf_vix_scaled_11': 0.60, 'etf_tech_mom_13': 0.50}
    check("override present -> override value",
          resolve_max_position_pct(overrides, 'etf_vix_scaled_11', 0.20) == 0.60)
    check("override absent -> global default",
          resolve_max_position_pct(overrides, 'other_strat', 0.20) == 0.20)
    check("empty override map -> global default",
          resolve_max_position_pct({}, 'etf_vix_scaled_11', 0.20) == 0.20)
    check("None override map -> global default",
          resolve_max_position_pct(None, 'etf_vix_scaled_11', 0.20) == 0.20)


def test_vix_scaled_incident_fixture():
    """Kanban t_6d931cc0: etf_vix_scaled_11 SPY60/QQQ40 at $200k.

    Whole-share convention (t_928a4e7d): the default 20% cap ($40k) is no
    longer below one share, so the book partially deploys with both legs
    capped and logged. The audited 60% override fills both legs to the cap
    boundary (~$120k / ~$80k); the residual round-robin may still log a
    CONCENTRATION_CAP row when the next whole share would breach the cap."""
    print("test_vix_scaled_incident_fixture (SPY60/QQQ40 @ $200k)")
    signals = [
        {'ticker': 'SPY', 'score': 60.0, 'action': 'BUY'},
        {'ticker': 'QQQ', 'score': 40.0, 'action': 'BUY'},
    ]
    prices = {'SPY': 769.79, 'QQQ': 717.30}

    # Default cap: both legs bind at $40k and are logged; whole shares make
    # the cap feasible so the book is ~39% deployed, not flat.
    targets, skipped = compute_target(signals, 200_000, prices, lots={})
    tgt = by_ticker(targets)
    check("default 20% cap: both legs bind at the cap boundary",
          all(t in tgt for t in ('SPY', 'QQQ'))
          and all(40_000 - prices[t] < tgt[t]['shares'] * tgt[t]['price']
                  <= 40_000 + 1e-6 for t in ('SPY', 'QQQ')),
          f"targets: {targets}")
    check("default 20% cap: SPY+QQQ CONCENTRATION_CAP skips",
          {s['ticker'] for s in skipped if s['skip_kind'] == 'CONCENTRATION_CAP'}
          == {'SPY', 'QQQ'},
          f"skips: {[(s['ticker'], s['skip_kind']) for s in skipped]}")

    # Audited 60% override: SPY fills to ~$120k, QQQ to ~$80k (whole shares).
    targets, skipped = compute_target(signals, 200_000, prices, lots={},
                                      max_position_pct=0.60)
    tgt = by_ticker(targets)
    spy_notional = tgt.get('SPY', {}).get('shares', 0) * prices['SPY']
    qqq_notional = tgt.get('QQQ', {}).get('shares', 0) * prices['QQQ']
    check("override 60%: SPY fills to the cap boundary (~$120k)",
          120_000 - prices['SPY'] < spy_notional <= 120_000 + 1e-6,
          f"SPY {tgt.get('SPY')} = ${spy_notional:,.2f}")
    check("override 60%: QQQ fills to its weight boundary (~$80k, residual may top up below cap)",
          80_000 - prices['QQQ'] < qqq_notional <= 120_000 + 1e-6,
          f"QQQ {tgt.get('QQQ')} = ${qqq_notional:,.2f}")
    check("override 60%: >99% deployed",
          (spy_notional + qqq_notional) / 200_000 > 0.99,
          f"deployed ${spy_notional + qqq_notional:,.2f}")
    # Residual round-robin MAY log CONCENTRATION_CAP for a ticker whose next
    # whole share would breach the cap — the guardrail stays enforced.
    check("override 60%: skips limited to cap-boundary round-robin probes",
          all(s['skip_kind'] == 'CONCENTRATION_CAP' for s in skipped),
          f"skips: {[(s['ticker'], s['skip_kind']) for s in skipped]}")
    for t in targets:
        n = t['shares'] * t['price']
        check(f"override 60%: {t['ticker']} under cap", n <= 120_000 + 1e-6,
              f"${n:,.2f}")


def test_resolve_cap_with_source():
    """t_ee1ab601: precedence override > design-derived > declared fallback
    > undeclared default; the source is always returned for logging."""
    print("test_resolve_cap_with_source (t_ee1ab601 design-derived caps)")
    from rebuild_paper_positions import resolve_cap_with_source
    overrides = {'etf_vix_scaled_11': 0.60}
    designs = {
        'ETF_US_Sector_Relative_Momentum': {'cap': 0.34, 'slot_count': 3},
        'etf_comm_trend_basket_15': {'cap': 0.20, 'slot_count': 6},
        'cn_stk_lowvol_12': {'cap': None, 'slot_count': None},  # declared fallback
    }
    check("explicit override beats design cap",
          resolve_cap_with_source(overrides, designs, 'etf_vix_scaled_11', 0.20)
          == (0.60, 'override'))
    check("design-derived cap used when no override (US Sector 0.34)",
          resolve_cap_with_source(overrides, designs,
                                  'ETF_US_Sector_Relative_Momentum', 0.20)
          == (0.34, 'design'))
    check("design-derived cap used when no override (comm_trend 0.20)",
          resolve_cap_with_source(overrides, designs,
                                  'etf_comm_trend_basket_15', 0.20)
          == (0.20, 'design'))
    check("paper_design row with null cap -> declared fallback to default",
          resolve_cap_with_source(overrides, designs, 'cn_stk_lowvol_12', 0.20)
          == (0.20, 'declared_fallback'))
    check("no paper_design row -> undeclared default",
          resolve_cap_with_source(overrides, designs, 'mystery_strat', 0.20)
          == (0.20, 'undeclared_default'))
    check("no maps at all -> undeclared default",
          resolve_cap_with_source(None, None, 'mystery_strat', 0.20)
          == (0.20, 'undeclared_default'))


def test_us_sector_design_cap_fixture():
    """t_ee1ab601: US Sector top-3 equal weight (XLK/XLF/IWM @ $100k).

    Silent 20% default capped every leg at $20k (memo: XLF 500->300,
    IWM 100->0, ~52% unintended cash). With the design-derived 0.34 cap
    each leg fills its 1/3 slot and residual deployment is unblocked.
    """
    print("test_us_sector_design_cap_fixture (top-3 equal @ $100k)")
    signals = [
        {'ticker': 'XLK', 'score': 33.33, 'action': 'BUY'},
        {'ticker': 'XLF', 'score': 33.33, 'action': 'BUY'},
        {'ticker': 'IWM', 'score': 33.33, 'action': 'BUY'},
    ]
    prices = {'XLK': 250.0, 'XLF': 50.0, 'IWM': 240.0}

    # Silent default reproduces the memo finding: every leg capped to $20k.
    targets, skipped = compute_target(signals, 100_000, prices, lots={})
    deployed = sum(t['shares'] * t['price'] for t in targets)
    check("default 20% cap: ~60% deployed max (memo reproduction)",
          deployed <= 60_000 + 1e-6, f"deployed ${deployed:,.2f}")

    # Design-derived 0.34 cap: full 1/3 slots deploy, no CONCENTRATION_CAP.
    targets, skipped = compute_target(signals, 100_000, prices, lots={},
                                      max_position_pct=0.34)
    deployed = sum(t['shares'] * t['price'] for t in targets)
    check("design cap 0.34: >95% deployed (52% unintended cash eliminated)",
          deployed > 95_000, f"deployed ${deployed:,.2f}")
    check("design cap 0.34: no CONCENTRATION_CAP skips",
          not any(s['skip_kind'] == 'CONCENTRATION_CAP' for s in skipped),
          f"skips: {[(s['ticker'], s['skip_kind']) for s in skipped]}")
    for t in targets:
        n = t['shares'] * t['price']
        check(f"design cap 0.34: {t['ticker']} under cap", n <= 34_000 + 1e-6,
              f"${n:,.2f}")


if __name__ == '__main__':
    test_incident_fixture_capped()
    test_pre_fix_behavior_reproduced()
    test_custom_cap()
    test_cap_below_one_lot()
    test_no_cap_breach_no_skip()
    test_resolve_max_position_pct()
    test_vix_scaled_incident_fixture()
    test_resolve_cap_with_source()
    test_us_sector_design_cap_fixture()
    print()
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)} assertion(s) failed)")
        sys.exit(1)
    print("RESULT: PASS (all assertions)")
