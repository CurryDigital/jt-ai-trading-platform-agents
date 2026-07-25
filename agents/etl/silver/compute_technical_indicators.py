#!/usr/bin/env python3
"""
Silver: Technical Indicators
Reads from: silver.unified_prices
Writes to:  silver.technical_indicators

Computes SMA 20/50/200, EMA 12/26, Wilder RSI-14, EMA-based MACD
(line/signal/histogram), Bollinger Bands, Wilder ATR-14, 20d volatility,
volume SMA/ratio, and price-vs-SMA distances.

2026-07-22 REWRITE — fixes four correctness bugs in the previous SQL version
that were the root cause of "buy signals missing":
  1. rsi_14, macd_signal, macd_histogram, atr_14 were hardcoded NULL. Because
     build_equity_kpis copies these into gold.kpis_metrics, macd_histogram was
     NULL everywhere, so every MACD criterion (S9's `macd_histogram >= 0.1`,
     cond_macd_bullish, s012_tech_momentum) silently never fired.
  2. ema_12/ema_26/macd_line used AVG() (SMA), not EMA — wrong MACD math that
     also disagreed with what the strategies' backtests assumed.
  3. The load window was only 30 days, so a "200-day SMA" averaged ~21 rows.
     sma_50/sma_200 (and cond_above_sma200, golden/death cross) were wrong.
  4. ON CONFLICT DO UPDATE didn't refresh macd_*, ema_*, rsi_14 or
     volume_ratio, so re-runs left them stale.

Now computed per-ticker in pure Python via shared/scripts/indicators.py
(stdlib only, unit-tested in tests/test_indicators.py). Loads a warmup window
long enough to seed EMA-26 / SMA-200, then writes only the recent tail to
bound the upsert. Never fabricates: emits NULL where history is insufficient.
"""
import os
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from indicators import ema, sma, rsi, atr, macd, rolling_std

# Warmup: enough history to seed SMA-200 + EMA-26. ~420 calendar days ≈ 290
# trading days. WRITE_TAIL_DAYS bounds the upsert to recent rows.
WARMUP_CALENDAR_DAYS = 420
WRITE_TAIL_DAYS = 45
MIN_ROWS = 20  # below this, indicators are all-NULL anyway — skip the ticker

INSERT_COLS = (
    "ticker, date, sma_20, sma_50, sma_200, ema_12, ema_26, rsi_14, "
    "macd_line, macd_signal, macd_histogram, bb_upper, bb_middle, bb_lower, "
    "bb_width, atr_14, volatility_20d, volume_sma_20, volume_ratio, "
    "price_vs_sma50_pct, price_vs_sma200_pct, calculated_at"
)

UPSERT_SQL = f"""
INSERT INTO silver.technical_indicators ({INSERT_COLS})
VALUES %s
ON CONFLICT (ticker, date) DO UPDATE SET
  sma_20 = EXCLUDED.sma_20, sma_50 = EXCLUDED.sma_50, sma_200 = EXCLUDED.sma_200,
  ema_12 = EXCLUDED.ema_12, ema_26 = EXCLUDED.ema_26, rsi_14 = EXCLUDED.rsi_14,
  macd_line = EXCLUDED.macd_line, macd_signal = EXCLUDED.macd_signal,
  macd_histogram = EXCLUDED.macd_histogram,
  bb_upper = EXCLUDED.bb_upper, bb_middle = EXCLUDED.bb_middle,
  bb_lower = EXCLUDED.bb_lower, bb_width = EXCLUDED.bb_width,
  atr_14 = EXCLUDED.atr_14, volatility_20d = EXCLUDED.volatility_20d,
  volume_sma_20 = EXCLUDED.volume_sma_20, volume_ratio = EXCLUDED.volume_ratio,
  price_vs_sma50_pct = EXCLUDED.price_vs_sma50_pct,
  price_vs_sma200_pct = EXCLUDED.price_vs_sma200_pct,
  calculated_at = EXCLUDED.calculated_at;
"""

FETCH_SQL = """
SELECT ticker, date, high, low, close, volume
FROM silver.unified_prices
WHERE close > 0 AND close IS NOT NULL
  AND date >= (SELECT MAX(date) - INTERVAL '%s days' FROM silver.unified_prices)
ORDER BY ticker, date
"""

import math


def _f(x):
    return float(x) if x is not None else None


def compute_for_ticker(rows):
    """rows: list of (date, high, low, close, volume) ordered by date.
    Returns list of value-tuples ready for INSERT (one per row)."""
    dates = [r[0] for r in rows]
    highs = [_f(r[1]) if r[1] is not None else _f(r[3]) for r in rows]  # fall back to close
    lows = [_f(r[2]) if r[2] is not None else _f(r[3]) for r in rows]
    closes = [_f(r[3]) for r in rows]
    vols = [_f(r[4]) if r[4] is not None else None for r in rows]

    sma20, sma50, sma200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    e12, e26 = ema(closes, 12), ema(closes, 26)
    rsi14 = rsi(closes, 14)
    mline, msig, mhist = macd(closes)
    std20 = rolling_std(closes, 20)
    log_ret = [None]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        log_ret.append(math.log(closes[i] / prev) if prev and prev > 0 and closes[i] > 0 else None)
    ret_std20 = rolling_std(log_ret, 20)
    atr14 = atr(highs, lows, closes, 14)
    vol_sma20 = sma(vols, 20)

    out = []
    for i in range(len(rows)):
        mid = sma20[i]
        upper = (mid + 2 * std20[i]) if (mid is not None and std20[i] is not None) else None
        lower = (mid - 2 * std20[i]) if (mid is not None and std20[i] is not None) else None
        width = ((4 * std20[i]) / mid) if (mid and std20[i] is not None) else None
        vol_ratio = (vols[i] / vol_sma20[i]) if (vols[i] is not None and vol_sma20[i]) else None
        pv50 = ((closes[i] / sma50[i] - 1) * 100) if (sma50[i]) else None
        pv200 = ((closes[i] / sma200[i] - 1) * 100) if (sma200[i]) else None
        volat = (ret_std20[i] * math.sqrt(252)) if ret_std20[i] is not None else None
        out.append((
            None, dates[i], sma20[i], sma50[i], sma200[i], e12[i], e26[i], rsi14[i],
            mline[i], msig[i], mhist[i], upper, mid, lower, width, atr14[i],
            volat, vol_sma20[i], vol_ratio, pv50, pv200,
        ))
    return out


def run():
    from psycopg2.extras import execute_values
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(FETCH_SQL % WARMUP_CALENDAR_DAYS)
    rows = cur.fetchall()

    # group by ticker preserving date order
    by_ticker = {}
    for r in rows:
        by_ticker.setdefault(r[0], []).append(r[1:])  # (date, high, low, close, volume)

    # only write rows in the recent tail
    cur.execute("SELECT MAX(date) FROM silver.unified_prices")
    max_date = cur.fetchone()[0]
    from datetime import timedelta
    write_cutoff = (max_date - timedelta(days=WRITE_TAIL_DAYS)) if max_date else None

    payload = []
    n_tickers = 0
    for ticker, trows in by_ticker.items():
        if len(trows) < MIN_ROWS:
            continue
        n_tickers += 1
        for vals in compute_for_ticker(trows):
            d = vals[1]
            if write_cutoff and d < write_cutoff:
                continue
            # vals = (None, date, ...19 metrics); replace leading None with ticker.
            # calculated_at is supplied as the NOW() literal in the template.
            payload.append((ticker,) + vals[1:])

    if not payload:
        print("⚠️  no technical-indicator rows to write")
        conn.close()
        return

    execute_values(
        cur, UPSERT_SQL, payload,
        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
        page_size=1000,
    )
    conn.commit()
    print(f"✅ silver.technical_indicators updated: {len(payload)} rows across {n_tickers} tickers")
    conn.close()


if __name__ == "__main__":
    run()
