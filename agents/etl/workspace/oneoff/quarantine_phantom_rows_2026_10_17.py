#!/usr/bin/env python3
"""Phantom-row quarantine (user directive 2026-10-17, item 1).

NO DELETES. Snapshot first (gold.etl_snapshot_log id + row-level bak table),
then quarantine into bronze.yf_suspect_bars with a reason.

Sets:
  A. SPY junk rows deleted 2026-10-15 without quarantine — re-add from
     gold.daily_ohlcv_bak_t183d8bb1 (completes the quarantine).
  B. silver.unified_prices non-trading-day phantoms: 2026-02-28 non-crypto
     cluster + AAPL Saturday ibkr_position marks + JPY=X 2026-05-16.
  C. gold.daily_ohlcv NULL-close rows on NON-trading days (weekend, or the
     row's market closed: US holidays for US/INDEX; same-market-no-bars test
     for HK/CN/SG).
  D. gold.daily_ohlcv NULL-close rows on TRADING days: refill from
     bronze.yf_prices where a real close exists; else quarantine as hole.

Usage:
  python3 quarantine_phantom_rows_2026_10_17.py --snapshot-id <id> [--dry-run]
Idempotent: quarantine inserts are ON CONFLICT (ticker,date) DO NOTHING;
refills only touch rows still NULL.
"""
import argparse
import os
import sys

ETL = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
sys.path.insert(0, os.path.join(ETL, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db

BAK_TABLE = "gold.daily_ohlcv__phantomq_bak_20261017"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = db.get_connection()
    cur = conn.cursor()
    counts = {"A_spy": 0, "B_silver": 0, "C_nontrading": 0,
              "D_refilled": 0, "D_hole": 0}

    def quarantine(rows, reason, dry):
        """rows: list of (ticker, date, o, h, l, c, v, adj). Returns inserted."""
        n = 0
        for t, d, o, h, l, c, v, adj in rows:
            if dry:
                n += 1
                continue
            cur.execute("""
                INSERT INTO bronze.yf_suspect_bars
                    (ticker, date, open, high, low, close, volume,
                     adjusted_close, reason, detected_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (ticker, date) DO NOTHING""",
                (t, d, o, h, l, c, v, adj, reason))
            n += cur.rowcount
        return n

    # ── pre counts ──────────────────────────────────────────────────────────
    cur.execute("SELECT count(*) FROM bronze.yf_suspect_bars")
    pre_suspect = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM gold.daily_ohlcv WHERE close IS NULL")
    pre_null = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM silver.unified_prices
                   WHERE (date='2026-02-28' AND COALESCE(asset_class,'')<>'CRYPTO')
                      OR (ticker='AAPL' AND date IN ('2026-07-18','2026-07-25','2026-08-15'))
                      OR (ticker='JPY=X' AND date='2026-05-16')""")
    pre_silver_phantom = cur.fetchone()[0]
    print(f"PRE: suspect_bars={pre_suspect} gold_null_close={pre_null} "
          f"silver_phantoms={pre_silver_phantom}")

    # ── snapshot row-level bak of every gold row we may touch (refill set) ──
    if not args.dry_run:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {BAK_TABLE} AS
            SELECT * FROM gold.daily_ohlcv WHERE close IS NULL""")
        cur.execute(f"SELECT count(*) FROM {BAK_TABLE}")
        print(f"snapshot {BAK_TABLE}: {cur.fetchone()[0]} rows")

    # ── A. SPY junk quarantine (from the t_183d8bb1 bak table) ─────────────
    cur.execute("""
        SELECT ticker, date, open, high, low, close, volume, adjusted_close
        FROM gold.daily_ohlcv_bak_t183d8bb1
        WHERE ticker='SPY' AND (
            extract(isodow from date) IN (6,7)
            OR date IN (SELECT holiday_date FROM gold.us_market_holidays))
        ORDER BY date""")
    spy_rows = cur.fetchall()
    counts["A_spy"] = quarantine(
        spy_rows, "spy_null_placeholder_2026_05_06_deleted_2026_10_15", args.dry_run)
    print(f"A. SPY junk quarantined: {counts['A_spy']} (of {len(spy_rows)} found)")

    # ── B. silver phantoms ──────────────────────────────────────────────────
    cur.execute("""
        SELECT ticker, date, open, high, low, close, volume, adjusted_close
        FROM silver.unified_prices
        WHERE (date='2026-02-28' AND COALESCE(asset_class,'')<>'CRYPTO')
           OR (ticker='AAPL' AND date IN ('2026-07-18','2026-07-25','2026-08-15'))
           OR (ticker='JPY=X' AND date='2026-05-16')""")
    sil_rows = cur.fetchall()
    counts["B_silver"] = quarantine(
        sil_rows, "phantom_nontrading_day_silver_2026_10_17", args.dry_run)
    print(f"B. silver phantoms quarantined: {counts['B_silver']} (of {len(sil_rows)})")

    # ── C/D. gold NULL-close split ──────────────────────────────────────────
    cur.execute("""
        SELECT ticker, date, market, open, high, low, close, volume, adjusted_close
        FROM gold.daily_ohlcv WHERE close IS NULL""")
    null_rows = cur.fetchall()
    print(f"gold NULL-close rows to classify: {len(null_rows)}")

    # US holiday set + per-date same-market-open evidence (one pass)
    cur.execute("SELECT holiday_date FROM gold.us_market_holidays")
    us_holidays = {r[0] for r in cur.fetchall()}
    cur.execute("""
        SELECT date, market, count(*) FILTER (WHERE close IS NOT NULL) AS real_bars
        FROM gold.daily_ohlcv
        WHERE date BETWEEN '2026-05-01' AND '2026-06-30'
        GROUP BY 1,2""")
    market_open = {(d, m): rb > 0 for d, m, rb in cur.fetchall()}

    refill_rows, hole_rows, nontrading_rows = [], [], []
    for t, d, mkt, o, h, l, c, v, adj in null_rows:
        dow = d.isoweekday()
        if dow in (6, 7):
            nontrading_rows.append((t, d, o, h, l, c, v, adj))
            continue
        if mkt in ("US", "INDEX") and d in us_holidays:
            nontrading_rows.append((t, d, o, h, l, c, v, adj))
            continue
        # market-open evidence: any same-market real bar that day
        if not market_open.get((d, mkt), False):
            nontrading_rows.append((t, d, o, h, l, c, v, adj))
            continue
        # trading day for this market, close is NULL -> hole
        cur.execute("""SELECT open, high, low, close, volume, adjusted_close
                       FROM bronze.yf_prices
                       WHERE ticker=%s AND date=%s AND close IS NOT NULL""",
                    (t, d))
        b = cur.fetchone()
        if b:
            refill_rows.append((t, d) + b)
        else:
            hole_rows.append((t, d, o, h, l, c, v, adj))

    counts["C_nontrading"] = quarantine(
        nontrading_rows, "null_bar_nontrading_day_2026_05_06_era", args.dry_run)
    print(f"C. NULL-close on non-trading days quarantined: "
          f"{counts['C_nontrading']} (of {len(nontrading_rows)})")

    for t, d, bo, bh, bl, bc, bv, badj in refill_rows:
        if args.dry_run:
            counts["D_refilled"] += 1
            continue
        cur.execute("""
            UPDATE gold.daily_ohlcv
            SET open=%s, high=%s, low=%s, close=%s, volume=%s,
                adjusted_close=%s,
                primary_source='refill_bronze_yf_phantomq_20261017'
            WHERE ticker=%s AND date=%s AND close IS NULL""",
            (bo, bh, bl, bc, bv, badj, t, d))
        counts["D_refilled"] += cur.rowcount
    print(f"D. trading-day NULL-close refilled from bronze: {counts['D_refilled']} "
          f"(of {len(refill_rows)} candidates)")

    counts["D_hole"] = quarantine(
        hole_rows, "null_close_trading_day_hole_no_bronze_2026_10_17", args.dry_run)
    print(f"D. trading-day NULL-close holes quarantined (no bronze source): "
          f"{counts['D_hole']} (of {len(hole_rows)})")

    # ── post counts + snapshot log ──────────────────────────────────────────
    cur.execute("SELECT count(*) FROM bronze.yf_suspect_bars")
    post_suspect = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM gold.daily_ohlcv WHERE close IS NULL")
    post_null = cur.fetchone()[0]
    print(f"POST: suspect_bars={post_suspect} gold_null_close={post_null}")

    note = (f"phantom quarantine 2026-10-17: A_spy={counts['A_spy']} "
            f"B_silver={counts['B_silver']} C_nontrading={counts['C_nontrading']} "
            f"D_refilled={counts['D_refilled']} D_hole={counts['D_hole']}; "
            f"suspect {pre_suspect}->{post_suspect}; "
            f"gold_null {pre_null}->{post_null}; bak={BAK_TABLE}; NO DELETES")
    if args.dry_run:
        print("DRY RUN — no writes. Note would be:", note)
        conn.rollback()
    else:
        cur.execute("""
            INSERT INTO gold.etl_snapshot_log
                (snapshot_id, scope, script, pre_rows, pre_max_date,
                 post_rows, post_max_date, note)
            VALUES (%s, %s, %s, %s, NULL, %s, NULL, %s)
            ON CONFLICT (snapshot_id) DO UPDATE SET
                post_rows = EXCLUDED.post_rows, note = EXCLUDED.note""",
            (args.snapshot_id,
             "phantom quarantine (gold.daily_ohlcv NULLs, silver phantoms, SPY junk)",
             "workspace/oneoff/quarantine_phantom_rows_2026_10_17.py",
             pre_null, post_null, note))
        conn.commit()
        print("snapshot logged:", args.snapshot_id)
    conn.close()
    print("DONE")


if __name__ == "__main__":
    main()
