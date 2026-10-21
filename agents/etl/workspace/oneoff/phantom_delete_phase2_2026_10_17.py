#!/usr/bin/env python3
"""Phantom cleanup phase 2 (user directive 2026-10-17 follow-up item 1).

DELETE the quarantined non-trading-day rows from the live tables.
Rows are preserved in bronze.yf_suspect_bars (full OHLCV) and
gold.daily_ohlcv__phantomq_bak_20261017 (gold set, pre-refill state).

Scope (exactly the phase-1 quarantined sets, by reason):
  gold.daily_ohlcv   : reason 'null_bar_nontrading_day_2026_05_06_era' (197)
  silver.unified_prices: reason 'phantom_nontrading_day_silver_2026_10_17' (217)

NOT touched: the 131 trading-day NULL-close holes (kept, flagged) and the
31 refilled rows.
"""
import os, sys
ETL = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
sys.path.insert(0, os.path.join(ETL, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db

GOLD_REASON = "null_bar_nontrading_day_2026_05_06_era"
SILVER_REASON = "phantom_nontrading_day_silver_2026_10_17"

conn = db.get_connection()
cur = conn.cursor()

cur.execute("SELECT count(*) FROM gold.daily_ohlcv WHERE close IS NULL")
pre_null = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM gold.daily_ohlcv")
pre_gold = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM silver.unified_prices")
pre_silver = cur.fetchone()[0]
print(f"PRE: gold={pre_gold} (null-close {pre_null}) silver={pre_silver}")

cur.execute("""
    DELETE FROM gold.daily_ohlcv d
    USING bronze.yf_suspect_bars s
    WHERE s.ticker=d.ticker AND s.date=d.date AND s.reason=%s""",
    (GOLD_REASON,))
n_gold = cur.rowcount
cur.execute("""
    DELETE FROM silver.unified_prices u
    USING bronze.yf_suspect_bars s
    WHERE s.ticker=u.ticker AND s.date=u.date AND s.reason=%s""",
    (SILVER_REASON,))
n_silver = cur.rowcount

cur.execute("SELECT count(*) FROM gold.daily_ohlcv")
post_gold = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM silver.unified_prices")
post_silver = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM gold.daily_ohlcv WHERE close IS NULL")
post_null = cur.fetchone()[0]
print(f"POST: gold={post_gold} (deleted {n_gold}; null-close {post_null}) "
      f"silver={post_silver} (deleted {n_silver})")

assert n_gold == 197 and n_silver == 217, (n_gold, n_silver)
assert post_null == 131, post_null

cur.execute("""
    INSERT INTO gold.etl_snapshot_log
        (snapshot_id, scope, script, pre_rows, post_rows, note)
    VALUES (%s,%s,%s,%s,%s,%s)""",
    ("phantomq_delete_20261017",
     "phantom cleanup phase 2: delete quarantined non-trading-day rows",
     "workspace/oneoff/phantom_delete_phase2_2026_10_17.py",
     pre_gold + pre_silver, post_gold + post_silver,
     f"gold -{n_gold} (reason {GOLD_REASON}), silver -{n_silver} (reason "
     f"{SILVER_REASON}); rows preserved in bronze.yf_suspect_bars + "
     "gold.daily_ohlcv__phantomq_bak_20261017; 131 trading-day holes kept "
     "(reason null_close_trading_day_hole_no_bronze_2026_10_17)"))
conn.commit()
conn.close()
print("DONE")
