#!/usr/bin/env python3
"""Remediate stale gold.strategy_backtest_trades rows for us_stk_sue_mom_01_v2.

Kanban t_e0a75a95 (QA t_8f492136 flag): the table held 907 trades
(682 IS + 225 OOS) from the OLD pre-re-base batch10 engine run, all stamped
with run_id bf42f373-35ce-53ba-8af2-aa53b35d9280. The fresh re-based run
(same run_id) produced 19 rebalance events (trade_count_oos=19) and is the
run that gold.strategy_backtest_monthly_returns / gold.strategy_registry
(returns_oos 0.2530) now reflect.

This script deletes the 907 stale rows and reloads the per-ticker trade log
reconstructed from the fresh run's canonical daily weights matrix
(tmp_sue/us_stk_sue_mom_01_v2_trade_log.csv — the same artifact already
registered in CURVE_SOURCES of refresh_strategy_monthly_returns_gold.py).

Reconstruction conventions (match the batch10 engine + old row shape):
  - A trade = one contiguous non-zero-weight spell for a ticker.
    Entry at close of the rebalance date where weight becomes non-zero
    (engine lag: signal at t earns over (t, t+1], so entry fill = close(t)).
  - Exit at close of the rebalance date where weight returns to zero;
    final book stays OPEN with exit fields NULL.
  - entry_price / exit_price = silver.unified_prices close (same source the
    engine uses); exit price as-of (ffill) if the ticker has no print that day.
  - pnl_pct = exit_price/entry_price - 1; holding_days = calendar days.
  - exit_reason = REBALANCE (closed) / OPEN (still held at OOS end).
  - period = 'OOS' (fresh re-base is OOS-only: 2025-01-01..2026-07-31).
    The old 682 IS rows have no fresh-run replacement and are dropped; the
    re-based engine's IS period was not re-run by qr_research.

Note: results.json trade_count_oos=19 counts REBALANCE EVENTS (engine:
`trades += 1` per non-zero-turnover rebalance), not per-ticker spells; the
per-ticker spell count is larger. Verified below against the matrix.

Usage:
  python3 remediate_sue_mom_v2_stale_trades_2026-09-22.py --dry-run
  python3 remediate_sue_mom_v2_stale_trades_2026-09-22.py --apply
"""
import argparse
import csv
import datetime as dt
import os
import sys

import psycopg2
import psycopg2.extras

SID = "us_stk_sue_mom_01_v2"
RUN_ID = "bf42f373-35ce-53ba-8af2-aa53b35d9280"
MATRIX_CSV = ("/home/ubuntu/.hermes/profiles/qr_research/workspace/"
              "monthly_returns_unblock_2026-09-22/tmp_sue/"
              "us_stk_sue_mom_01_v2_trade_log.csv")
RESULTS_JSON = ("/home/ubuntu/.hermes/profiles/qr_research/workspace/"
                "monthly_returns_unblock_2026-09-22/tmp_sue/"
                "us_stk_sue_mom_01_v2_results.json")
EPS = 1e-9


def get_dsn():
    dsn = os.environ.get("OPENCLAW_DATABASE_URL")
    if not dsn:
        raise RuntimeError("OPENCLAW_DATABASE_URL not set in environment")
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return dsn


def load_matrix(path):
    """Return (dates, {ticker: [w per date]}), weights as floats."""
    with open(path, newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr)
        tickers = header[3:]  # date, portfolio_value, period_return, <weights...>
        dates, cols = [], {t: [] for t in tickers}
        for row in rdr:
            dates.append(dt.date.fromisoformat(row[0]))
            for t, v in zip(tickers, row[3:]):
                cols[t].append(float(v) if v else 0.0)
    return dates, cols


def build_spells(dates, cols):
    """Per ticker, contiguous non-zero-weight spells -> trade dicts (prices TBD)."""
    trades = []
    for t, ws in cols.items():
        start = None
        for i, w in enumerate(ws):
            if abs(w) > EPS and start is None:
                start = i
            elif abs(w) <= EPS and start is not None:
                # position closed at rebalance on date i-1? No: weight went to
                # zero AT the rebalance that produced day-i's book. Exit fill =
                # close of that rebalance date. Day i-1 is the last day held;
                # the rebalance happened at close of the previous rebalance
                # date <= i-1. In the matrix, weights only change on rebalance
                # dates, so date[i-1] IS the rebalance date where exit filled.
                trades.append({"ticker": t, "entry_date": dates[start],
                               "exit_date": dates[i - 1], "weight": ws[start]})
                start = None
        if start is not None:
            trades.append({"ticker": t, "entry_date": dates[start],
                           "exit_date": None, "weight": ws[start]})
    trades.sort(key=lambda r: (r["entry_date"], r["ticker"]))
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to DB")
    ap.add_argument("--dry-run", action="store_true", help="print only")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("specify --dry-run or --apply")

    import json
    with open(RESULTS_JSON) as f:
        res = json.load(f)
    print(f"fresh run: trade_count_oos(rebalance events)={res['trade_count_oos']} "
          f"returns_oos={res['returns_oos']} oos={res['oos_start']}..{res['oos_end']}")

    dates, cols = load_matrix(MATRIX_CSV)
    print(f"matrix: {len(dates)} days {dates[0]}..{dates[-1]}, {len(cols)} tickers")

    # verify rebalance-event count matches results.json (weights change days)
    change_days = 0
    prev = None
    for i in range(len(dates)):
        book = tuple(sorted(t for t in cols if abs(cols[t][i]) > EPS))
        if prev is not None and book != prev:
            change_days += 1
        prev = book
    print(f"book-change days in matrix: {change_days} (expect == trade_count_oos)")

    trades = build_spells(dates, cols)
    print(f"per-ticker spells: {len(trades)} "
          f"({sum(1 for x in trades if x['exit_date'] is None)} OPEN)")

    conn = psycopg2.connect(get_dsn())
    cur = conn.cursor()

    # prices for entry/exit fills (same source as engine)
    tickers = sorted({x["ticker"] for x in trades})
    cur.execute("""SELECT ticker, date, close FROM silver.unified_prices
                   WHERE ticker = ANY(%s) AND date >= %s AND date <= %s
                   ORDER BY ticker, date""",
                (tickers, dates[0], dates[-1]))
    px = {}
    for t, d, c in cur.fetchall():
        px.setdefault(t, {})[d] = float(c)

    def asof(t, d):
        series = px.get(t, {})
        best = None
        for pd_, c in series.items():
            if pd_ <= d and (best is None or pd_ > best[0]):
                best = (pd_, c)
        return best[1] if best else None

    rows, skipped = [], 0
    for x in trades:
        ep = asof(x["ticker"], x["entry_date"])
        if ep is None:
            skipped += 1
            continue
        if x["exit_date"] is None:
            rows.append((RUN_ID, SID, x["ticker"], "OOS", x["entry_date"], None,
                         ep, None, None, None, "OPEN", None))
        else:
            xp = asof(x["ticker"], x["exit_date"])
            if xp is None:
                skipped += 1
                continue
            pnl = xp / ep - 1.0
            hd = (x["exit_date"] - x["entry_date"]).days
            rows.append((RUN_ID, SID, x["ticker"], "OOS", x["entry_date"],
                         x["exit_date"], ep, xp, round(pnl, 4), hd,
                         "REBALANCE", None))
    print(f"rows built: {len(rows)} (skipped no-price: {skipped})")

    cur.execute("""SELECT period, count(*) FROM gold.strategy_backtest_trades
                   WHERE strategy_id=%s GROUP BY period""", (SID,))
    print("DB before:", cur.fetchall())

    if args.dry_run:
        for r in rows[:5]:
            print("  sample:", r)
        print("DRY RUN - no writes")
        conn.rollback()
        return

    cur.execute("DELETE FROM gold.strategy_backtest_trades WHERE strategy_id=%s", (SID,))
    deleted = cur.rowcount
    psycopg2.extras.execute_values(
        cur,
        """INSERT INTO gold.strategy_backtest_trades
           (run_id, strategy_id, ticker, period, entry_date, exit_date,
            entry_price, exit_price, pnl_pct, holding_days, exit_reason,
            signal_score)
           VALUES %s""",
        rows)
    conn.commit()
    print(f"deleted {deleted} stale rows, inserted {len(rows)} fresh rows")

    cur.execute("""SELECT period, exit_reason, count(*) FROM gold.strategy_backtest_trades
                   WHERE strategy_id=%s GROUP BY period, exit_reason ORDER BY 1,2""", (SID,))
    print("DB after:", cur.fetchall())
    cur.execute("""SELECT min(entry_date), max(entry_date), max(exit_date)
                   FROM gold.strategy_backtest_trades WHERE strategy_id=%s""", (SID,))
    print("date span:", cur.fetchone())
    conn.close()


if __name__ == "__main__":
    main()
