#!/usr/bin/env python3
"""Silver/bronze orphan reconcile (user directive 2026-10-17, item 1).

silver.unified_prices is upsert-only: a row whose bronze source row was
deleted (or never existed in current bronze) persists forever. This tool
anti-joins silver rows against their source bronze table and quarantines
orphans into bronze.yf_suspect_bars. NO DELETES from silver.

SCOPE — live-feed sources only (these SHOULD have bronze coverage):
    yfinance, yahoo, Yahoo, yahoo_backfill, yahoo_backfill_v2,
    yahoo_sg_backfill      -> bronze.yf_prices (ticker, date)
    fx, fx_daily_refresh   -> bronze.fx_prices (pair, timestamp::date)
EXEMPT (historical base / unmapped — reported, never quarantined):
    NULL source, legacy_historical_stock_data, unknown, manual_update,
    ibkr_position (position marks; writer fixed 2026-10-17), crypto tickers.

CALENDAR FILTER (2026-10-17 dry-run finding): a bare anti-join flags ~219k
rows — historical backfill staging (yahoo_backfill_v2) whose bronze rows were
rotated after merge, and FX pairs ingested under non-yf bronze tables. Those
are staging churn, not phantoms. The phantom signature is an orphan row on a
NON-TRADING DAY, so the anti-join is restricted to:
    - weekend dates (dow 6/7), excluding crypto and FX Sunday bars
    - US-market holidays for US/INDEX tickers
Everything else is reported as exempt churn, never quarantined.

Usage:
  python3 reconcile_unified_prices_bronze.py --dry-run          # report only
  python3 reconcile_unified_prices_bronze.py --apply --snapshot-id <id>
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared", "scripts")))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db

YF_SOURCES = ("yfinance", "yahoo", "Yahoo", "yahoo_backfill",
              "yahoo_backfill_v2", "yahoo_sg_backfill")
FX_SOURCES = ("fx", "fx_daily_refresh")
REASON = "orphan_no_bronze_source_reconcile"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--snapshot-id")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True
    if args.apply and not args.snapshot_id:
        ap.error("--apply requires --snapshot-id")

    conn = db.get_connection()
    cur = conn.cursor()

    # ── yfinance-family orphans on NON-TRADING DAYS (phantom signature) ─────
    # Excludes: crypto (24/7), FX Sunday bars (legit week open). FX tickers
    # routed to the fx anti-join instead of yf_prices.
    print("== yfinance-family orphans on non-trading days ==")
    cur.execute("""
        SELECT s.ticker, s.date, s.open, s.high, s.low, s.close, s.volume,
               s.adjusted_close, s.source
        FROM silver.unified_prices s
        WHERE s.source IN %s
          AND COALESCE(s.asset_class,'') NOT IN ('CRYPTO','FX','CURRENCY')
          AND (
                extract(isodow from s.date) IN (6,7)
                OR (s.market IN ('US','INDEX') AND s.date IN
                    (SELECT holiday_date FROM gold.us_market_holidays))
              )
          AND NOT EXISTS (SELECT 1 FROM bronze.yf_prices b
                          WHERE b.ticker = s.ticker AND b.date = s.date)
          AND NOT EXISTS (SELECT 1 FROM bronze.yf_commodity_futures c
                          WHERE c.ticker = s.ticker AND c.date = s.date)
        ORDER BY s.date DESC, s.ticker""", (YF_SOURCES,))
    yf_orphans = cur.fetchall()
    print(f"  TOTAL: {len(yf_orphans)}")
    print("  sample:", [(r[0], str(r[1]), r[8]) for r in yf_orphans[:10]])

    # ── fx orphans on non-trading days (Saturday only; Sunday is legit) ─────
    print("== fx orphans on Saturdays (no bronze.fx_prices row) ==")
    cur.execute("""
        SELECT s.ticker, s.date, s.open, s.high, s.low, s.close, s.volume,
               s.adjusted_close, s.source
        FROM silver.unified_prices s
        WHERE s.source IN %s
          AND extract(isodow from s.date) = 6
          AND NOT EXISTS (SELECT 1 FROM bronze.fx_prices f
                          WHERE f.pair = s.ticker
                            AND f.timestamp::date = s.date)
        ORDER BY s.date DESC""", (FX_SOURCES,))
    fx_orphans = cur.fetchall()
    print(f"  TOTAL: {len(fx_orphans)}")
    print("  sample:", [(r[0], str(r[1]), r[8]) for r in fx_orphans[:10]])

    # ── exempt/churn population (report only) ────────────────────────────────
    cur.execute("""
        SELECT COALESCE(source,'NULL'), count(*) FROM silver.unified_prices
        WHERE source IS NULL OR source NOT IN %s
        GROUP BY 1 ORDER BY 2 DESC""", (YF_SOURCES + FX_SOURCES,))
    print("== exempt/unmapped sources (never quarantined) ==")
    for r in cur.fetchall():
        print(f"  {r[0]:32s} {r[1]}")
    cur.execute("""
        SELECT count(*) FROM silver.unified_prices s
        WHERE s.source IN %s
          AND COALESCE(s.asset_class,'') NOT IN ('CRYPTO','FX','CURRENCY')
          AND NOT (extract(isodow from s.date) IN (6,7)
                   OR (s.market IN ('US','INDEX') AND s.date IN
                       (SELECT holiday_date FROM gold.us_market_holidays)))
          AND NOT EXISTS (SELECT 1 FROM bronze.yf_prices b
                          WHERE b.ticker = s.ticker AND b.date = s.date)
          AND NOT EXISTS (SELECT 1 FROM bronze.yf_commodity_futures c
                          WHERE c.ticker = s.ticker AND c.date = s.date)""",
        (YF_SOURCES,))
    print(f"== trading-day orphans (staging churn, REPORT ONLY): "
          f"{cur.fetchone()[0]} ==")

    orphans = yf_orphans + fx_orphans
    print(f"ORPHAN TOTAL: {len(orphans)}")

    if args.dry_run:
        print("DRY RUN — no writes. Re-run with --apply --snapshot-id <id>.")
        conn.close()
        return

    n = 0
    for t, d, o, h, l, c, v, adj, src in orphans:
        cur.execute("""
            INSERT INTO bronze.yf_suspect_bars
                (ticker, date, open, high, low, close, volume,
                 adjusted_close, reason, detected_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (ticker, date) DO NOTHING""",
            (t, d, o, h, l, c, v, adj, f"{REASON} (src={src})"))
        n += cur.rowcount
    cur.execute("""
        INSERT INTO gold.etl_snapshot_log
            (snapshot_id, scope, script, pre_rows, post_rows, note)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (snapshot_id, scope) DO UPDATE SET
            post_rows = EXCLUDED.post_rows, note = EXCLUDED.note""",
        (args.snapshot_id, "silver orphan reconcile (no deletes)",
         "silver/reconcile_unified_prices_bronze.py",
         len(orphans), n,
         f"quarantined {n}/{len(orphans)} orphans to bronze.yf_suspect_bars; "
         "silver rows left in place"))
    conn.commit()
    print(f"APPLIED: quarantined {n} new rows (of {len(orphans)} orphans); "
          f"snapshot_id={args.snapshot_id}")
    conn.close()


if __name__ == "__main__":
    main()
