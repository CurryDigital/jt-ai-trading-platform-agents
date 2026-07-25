#!/usr/bin/env python3
"""
price_indicators.py — EMA-based MACD, Wilder RSI and Wilder ATR for daily OHLC
series, computed through indicators.py (the one true source, unit-tested in
tests/test_indicators.py).

ROADMAP G3 / PIPELINE_DESIGN principle 3 (indicator correctness as a contract):
the FX (gold.fx_metrics) and index (gold.index_metrics) builders used to emit
NULL macd_signal / macd_histogram / atr_14 and compute macd_line as an SMA
*difference* (AVG(12) - AVG(26)) — the same class of bug that left
silver.technical_indicators' macd_histogram NULL and killed every MACD BUY.
Both now route through here, so silver, FX and index agree on the math.

Never fabricates: emits None wherever there is not enough history to seed the
indicator (EMA-26 / RSI-14 / ATR-14).
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from indicators import rsi, atr, macd  # noqa: E402

# Warmup: enough daily history to seed EMA-26 (MACD) and Wilder ATR/RSI. The
# builders read this many calendar days back from the gold table (which
# accumulates history across daily runs), then write only the recent tail.
WARMUP_CALENDAR_DAYS = 420
WRITE_TAIL_DAYS = 60


def _f(x):
    return float(x) if x is not None else None


def indicator_rows(rows, write_cutoff=None):
    """Compute the five indicator columns for every input row.

    rows: iterable of (ticker, date, high, low, close) ordered by ticker, date.
          high/low may be None — they fall back to close (matches the
          silver builder's behaviour).
    write_cutoff: optional date; rows strictly before it are used as warmup
          history but excluded from the returned payload (bounds the UPDATE).

    Returns list of tuples:
        (ticker, date, rsi_14, macd_line, macd_signal, macd_histogram, atr_14)
    with None where history is insufficient.
    """
    by_t = {}
    for r in rows:
        by_t.setdefault(r[0], []).append((r[1], _f(r[2]), _f(r[3]), _f(r[4])))

    out = []
    for ticker, tr in by_t.items():
        dates = [x[0] for x in tr]
        closes = [x[3] for x in tr]
        # If a close is missing the ticker can't be indicated cleanly — skip it.
        if any(c is None for c in closes):
            continue
        highs = [x[1] if x[1] is not None else closes[i] for i, x in enumerate(tr)]
        lows = [x[2] if x[2] is not None else closes[i] for i, x in enumerate(tr)]

        r14 = rsi(closes, 14)
        m_line, m_sig, m_hist = macd(closes)
        a14 = atr(highs, lows, closes, 14)

        for i, d in enumerate(dates):
            if write_cutoff is not None and d < write_cutoff:
                continue
            out.append((ticker, d, r14[i], m_line[i], m_sig[i], m_hist[i], a14[i]))
    return out
