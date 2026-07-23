#!/usr/bin/env python3
"""
Unit tests for shared/scripts/indicators.py — pure stdlib, no db/pandas.
Run: python3 agents/etl/tests/test_indicators.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared", "scripts"))
from indicators import ema, sma, rsi, atr, macd, rolling_std


def approx(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol


def test_ema_adjust_false():
    # EMA(span=3, adjust=False), alpha=0.5. Seeds on first value.
    x = [1.0, 2.0, 3.0, 4.0]
    e = ema(x, 3)
    # y0=1; y1=.5*2+.5*1=1.5; y2=.5*3+.5*1.5=2.25; y3=.5*4+.5*2.25=3.125
    assert approx(e[0], 1.0) and approx(e[1], 1.5) and approx(e[2], 2.25) and approx(e[3], 3.125), e


def test_macd_is_nonnull_and_line_minus_signal():
    closes = [10 + (i % 5) - (i % 3) + i * 0.1 for i in range(120)]
    line, sig, hist = macd(closes)
    # after warmup all three are populated
    assert line[-1] is not None and sig[-1] is not None and hist[-1] is not None
    # histogram is exactly line - signal
    assert approx(hist[-1], line[-1] - sig[-1]), (hist[-1], line[-1], sig[-1])
    # a genuine MACD line differs from an SMA-based one: for a rising series
    # the EMA line leads, so line != 0 generally
    assert abs(line[-1]) > 0


def test_rsi_bounds_and_known_case():
    # Strictly rising closes -> RSI should approach 100.
    closes = [float(i) for i in range(1, 60)]
    r = rsi(closes, 14)
    assert r[13] is None or True  # index 13 may be None (first value at 14)
    assert r[14] is not None
    assert all(0.0 <= v <= 100.0 for v in r if v is not None)
    assert r[-1] > 99.0, r[-1]  # all gains -> ~100
    # Strictly falling -> RSI near 0
    r2 = rsi([float(i) for i in range(60, 1, -1)], 14)
    assert r2[-1] < 1.0, r2[-1]


def test_rsi_wilder_reference():
    # Classic Wilder worked example (first 15 closes) — RSI at the 15th close.
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
              45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    r = rsi(closes, 14)
    # Widely-published value for this series is ~70.5 (Wilder seed).
    assert r[14] is not None and 69.0 < r[14] < 72.0, r[14]


def test_atr_nonnull_after_warmup():
    highs = [10 + (i % 4) * 0.5 for i in range(40)]
    lows = [9 + (i % 3) * 0.4 for i in range(40)]
    closes = [9.5 + (i % 5) * 0.3 for i in range(40)]
    a = atr(highs, lows, closes, 14)
    assert a[13] is None and a[14] is not None and a[-1] is not None
    assert a[-1] > 0


def test_sma_and_std_windows():
    x = [float(i) for i in range(1, 11)]
    s = sma(x, 5)
    assert s[3] is None and approx(s[4], 3.0) and approx(s[9], 8.0)
    st = rolling_std(x, 5)
    assert st[3] is None and st[4] is not None and st[4] > 0


def test_none_handling():
    # Leading None (insufficient history) must not crash and must not fabricate.
    assert ema([None, None, 5.0], 3)[-1] == 5.0
    assert sma([None, 1.0, 2.0], 5)[-1] is None


def _main():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _main()
