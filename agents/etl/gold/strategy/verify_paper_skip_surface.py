#!/usr/bin/env python3
"""Verify the zero-size skip surface in rebuild_paper_positions.compute_target.

Offline tests, no DB required. Covers the three skip kinds introduced for the
explicit skip surface (kanban t_86e4d3e1, operator decision B):

  1. Futures BUY that cannot afford 1 unit  -> UNSUPPORTED_ASSET_CLASS skip.
  2. Futures BUY at sufficient capital      -> fills, no skip.
  3. Equity BUY below one share (US lot=1)  -> BELOW_ONE_LOT skip + freed
     capital redistributed to the remaining fillable signal.
  4. BUY with no latest price               -> NO_PRICE skip (was a silent
     drop before the skip surface).

Cases 2-4 pass max_position_pct=0 (cap disabled) so they isolate lot sizing;
the concentration cap is orthogonal and has its own CONCENTRATION_CAP skip
kind. Case 3 reflects the unified lot convention (DECISION 2026-08-17,
t_928a4e7d): US equities/ETFs size in whole shares, so BELOW_ONE_LOT fires
only when a slot cannot afford ONE share.

Usage:
    source /home/ubuntu/.hermes/etl-venv/bin/activate
    python verify_paper_skip_surface.py

Exit code 0 = all checks pass, 1 = any failure.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rebuild_paper_positions import compute_target

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    line = f"  [{status}] {name}"
    if not cond and detail:
        line += f"  -- {detail}"
    print(line)
    if not cond:
        failures.append(name)


# --- Case 1: futures zero-size at $10k (the t_86e4d3e1 scenario) -----------
signals = [
    {'ticker': 'GC=F', 'score': 0.33, 'action': 'BUY'},
    {'ticker': 'CASH', 'score': 0.67, 'action': 'HOLD'},
    {'ticker': 'SI=F', 'score': 0.00, 'action': 'SELL'},
]
prices = {'GC=F': 4111.50, 'SI=F': 59.27}

targets, skipped = compute_target(signals, 10000, prices, {})
check("futures zero-size: no target produced", len(targets) == 0, str(targets))
check("futures zero-size: exactly one skip", len(skipped) == 1, str(skipped))
if skipped:
    sk = skipped[0]
    check("futures skip_kind is UNSUPPORTED_ASSET_CLASS",
          sk['skip_kind'] == 'UNSUPPORTED_ASSET_CLASS', str(sk))
    check("futures skip fields (ticker/slot/lot_cost/price/lot)",
          sk['ticker'] == 'GC=F'
          and sk['slot_notional'] == 3300.0
          and sk['lot_cost'] == 4111.5
          and sk['price'] == 4111.50
          and sk['lot_size'] == 1
          and sk['signal_action'] == 'BUY'
          and sk['weight'] == 0.33,
          str(sk))
    check("futures reason names missing contract multiplier",
          'multiplier' in sk['reason'] and 'futures' in sk['reason'], sk['reason'])

# --- Case 2: futures fillable at $100k (cap disabled: isolates lot sizing) --
targets, skipped = compute_target(signals, 100000, prices, {}, max_position_pct=0)
check("futures fillable at $100k: GC=F target of 8 units",
      len(targets) == 1 and targets[0]['ticker'] == 'GC=F' and targets[0]['shares'] == 8,
      str(targets))
check("futures fillable at $100k: no skip", len(skipped) == 0, str(skipped))

# --- Case 3: US equity below ONE SHARE (lot=1, unified convention 2026-08-17),
# freed capital redistributed ---------------------------------------------
signals_eq = [
    {'ticker': 'SPY', 'score': 50, 'action': 'BUY'},
    {'ticker': 'QQQ', 'score': 50, 'action': 'BUY'},
]
# $1,000 capital, equal scores -> $500 slots. SPY at $600 cannot afford one
# share -> BELOW_ONE_LOT; freed $500 redistributes to QQQ ($50/share).
targets, skipped = compute_target(signals_eq, 1000, {'SPY': 600.0, 'QQQ': 50.0}, {},
                                  max_position_pct=0)
check("equity below-one-share: one skip with kind BELOW_ONE_LOT",
      len(skipped) == 1 and skipped[0]['skip_kind'] == 'BELOW_ONE_LOT'
      and skipped[0]['ticker'] == 'SPY'
      and skipped[0]['lot_size'] == 1 and skipped[0]['lot_cost'] == 600.0,
      str(skipped))
check("equity below-one-share: reason string preserved",
      skipped and skipped[0]['reason'] == 'below 1 lot at slot capital',
      skipped[0]['reason'] if skipped else 'no skip')
check("equity below-one-share: freed slot redistributed to QQQ (20 shares)",
      len(targets) == 1 and targets[0]['ticker'] == 'QQQ' and targets[0]['shares'] == 20,
      str(targets))

# --- Case 4: BUY with no price -> NO_PRICE skip (previously silent) ---------
targets, skipped = compute_target([{'ticker': 'XXXX', 'score': 100, 'action': 'BUY'}],
                                  10000, {}, {})
check("no-price: one skip with kind NO_PRICE",
      len(skipped) == 1 and skipped[0]['skip_kind'] == 'NO_PRICE'
      and skipped[0]['price'] is None and skipped[0]['lot_cost'] is None,
      str(skipped))
check("no-price: reason names silver.unified_prices",
      skipped and skipped[0]['reason'] == 'no latest price in silver.unified_prices',
      skipped[0]['reason'] if skipped else 'no skip')
check("no-price: no target produced", len(targets) == 0, str(targets))

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("All skip-surface checks passed.")
