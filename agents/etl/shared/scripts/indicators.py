#!/usr/bin/env python3
"""
indicators.py — pure-Python technical indicators (stdlib only).

Written because silver/compute_technical_indicators.py was producing NULL for
rsi_14, macd_signal, macd_histogram and atr_14, and computing ema_12/ema_26
as simple moving averages (AVG) rather than EMAs. Downstream that meant
gold.kpis_metrics.macd_histogram was NULL, so every MACD-based BUY criterion
(e.g. S9_MACD_Momentum_V2's `macd_histogram >= 0.1`) and cond_macd_bullish
silently never fired — the root cause of "buy signals missing".

These are the standard definitions the strategies + backtests assume:
  ema        : EMA with adjust=False (charting/TA convention, matches pandas
               ewm(span=n, adjust=False)).
  rsi        : Wilder's RSI (SMA seed of first n, then Wilder smoothing).
  atr        : Wilder's ATR on true range.
  macd       : EMA(12) - EMA(26), signal = EMA(9) of the line, hist = line-signal.

No pandas / numpy dependency so it runs on any venv and is unit-testable
offline. Each function returns a list the same length as the input, with
None where there is not yet enough history (never a fabricated value).
"""
from __future__ import annotations

import math
from typing import List, Optional

Num = Optional[float]


def ema(values: List[Num], span: int) -> List[Num]:
    """EMA with adjust=False. Seeds on the first non-None value."""
    alpha = 2.0 / (span + 1.0)
    out: List[Num] = []
    prev: Num = None
    for v in values:
        if v is None:
            out.append(prev)
            continue
        if prev is None:
            prev = v
        else:
            prev = alpha * v + (1.0 - alpha) * prev
        out.append(prev)
    return out


def sma(values: List[Num], window: int) -> List[Num]:
    """Simple moving average; None until `window` real points are available."""
    out: List[Num] = []
    buf: List[float] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        buf.append(v)
        if len(buf) > window:
            buf.pop(0)
        out.append(sum(buf) / len(buf) if len(buf) == window else None)
    return out


def rolling_std(values: List[Num], window: int) -> List[Num]:
    """Population std over the trailing window (matches SQL STDDEV_POP-ish);
    None until the window is full."""
    out: List[Num] = []
    buf: List[float] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        buf.append(v)
        if len(buf) > window:
            buf.pop(0)
        if len(buf) == window:
            m = sum(buf) / window
            out.append(math.sqrt(sum((x - m) ** 2 for x in buf) / window))
        else:
            out.append(None)
    return out


def rsi(closes: List[float], period: int = 14) -> List[Num]:
    """Wilder's RSI. None for the first `period` bars."""
    n = len(closes)
    out: List[Num] = [None] * n
    if n <= period:
        return out
    gains, losses = [], []
    for i in range(1, n):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
    # gains[k] corresponds to closes[k+1].
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period + 1, n):
        g = gains[i - 1]
        l = losses[i - 1]
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
        out[i] = _rsi(avg_gain, avg_loss)
    return out


def atr(highs: List[float], lows: List[float], closes: List[float],
        period: int = 14) -> List[Num]:
    """Wilder's ATR on true range. None until `period` bars of TR exist."""
    n = len(closes)
    out: List[Num] = [None] * n
    if n <= period:
        return out
    tr: List[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    prev = sum(tr[1:period + 1]) / period  # first ATR at index `period`
    out[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, macd_signal, macd_histogram) — all EMA-based."""
    line = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema(closes, fast), ema(closes, slow))
    ]
    sig = ema(line, signal)
    hist = [
        (l - g) if (l is not None and g is not None) else None
        for l, g in zip(line, sig)
    ]
    return line, sig, hist
