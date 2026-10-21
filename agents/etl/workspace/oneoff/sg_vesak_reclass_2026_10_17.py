#!/usr/bin/env python3
"""SGX Vesak-observed 2026-06-01 reclassification (user directive, item 1).

SGX was CLOSED Monday 2026-06-01 (Vesak Day observed; Vesak fell Sunday
2026-05-31 — confirmed vs Tradeweb/forexchurch calendars). All 60 gold SG
rows on that date are non-trading-day artifacts:
  - 58 all-NULL placeholder rows (quarantined phase 1 as trading-day holes —
    misclassified because F03.SI/T43.SI flat zero-volume marks made the
    same-market-open test read 'open')
  - 2 zero-volume flat placeholder rows (F03.SI, T43.SI)

Actions: quarantine the 2 flat rows, reclassify all 60 to reason
'null_or_flat_sg_holiday_2026_06_01_vesak_obs', DELETE all 60 from
gold.daily_ohlcv. Log to gold.etl_snapshot_log.
"""
import os, sys
ETL = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
sys.path.insert(0, os.path.join(ETL, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db

NEW_REASON = "sg_holiday_2026_06_01_vesak_obs_nontrading_day"
OLD_REASON = "null_close_trading_day_hole_no_bronze_2026_10_17"

conn = db.get_connection()
cur = conn.cursor()

cur.execute("SELECT count(*) FROM gold.daily_ohlcv WHERE market='SG' AND date='2026-06-01'")
pre = cur.fetchone()[0]
print(f"PRE: SG gold rows on 2026-06-01 = {pre}")

# 1. quarantine the 2 flat zero-volume rows (copy full bar first)
cur.execute("""
    INSERT INTO bronze.yf_suspect_bars
        (ticker, date, open, high, low, close, volume, adjusted_close, reason, detected_at)
    SELECT ticker, date, open, high, low, close, volume, adjusted_close, %s, NOW()
    FROM gold.daily_ohlcv
    WHERE market='SG' AND date='2026-06-01' AND close IS NOT NULL
    ON CONFLICT (ticker, date) DO UPDATE SET reason = EXCLUDED.reason""",
    (NEW_REASON,))
print(f"flat rows quarantined: {cur.rowcount}")

# 2. reclassify the phase-1 NULL rows to the holiday reason
cur.execute("""
    UPDATE bronze.yf_suspect_bars
    SET reason = %s
    WHERE reason = %s AND date = '2026-06-01'
      AND ticker IN (SELECT ticker FROM gold.daily_ohlcv
                     WHERE market='SG' AND date='2026-06-01')""",
    (NEW_REASON, OLD_REASON))
print(f"reclassified: {cur.rowcount}")

# 3. delete all SG rows on the closed day from live gold
cur.execute("DELETE FROM gold.daily_ohlcv WHERE market='SG' AND date='2026-06-01'")
n_del = cur.rowcount
print(f"deleted from gold: {n_del}")

cur.execute("SELECT count(*) FROM gold.daily_ohlcv WHERE market='SG' AND date='2026-06-01'")
post = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM gold.daily_ohlcv WHERE close IS NULL")
null_left = cur.fetchone()[0]
print(f"POST: SG 06-01 rows = {post}; gold NULL-close remaining = {null_left}")
assert n_del == pre and post == 0, (n_del, pre, post)

cur.execute("""
    INSERT INTO gold.etl_snapshot_log (snapshot_id, scope, script, pre_rows, post_rows, note)
    VALUES (%s,%s,%s,%s,%s,%s)""",
    ("sg_vesak_obs_20261017",
     "SGX 2026-06-01 Vesak-observed reclassification + delete",
     "workspace/oneoff/sg_vesak_reclass_2026_10_17.py",
     pre, post,
     f"60 SG rows on closed day (Vesak obs): 58 NULL reclassified from hole reason, "
     f"2 flat zero-volume quarantined; all deleted from live gold. "
     f"Preserved in bronze.yf_suspect_bars reason={NEW_REASON} + "
     "gold.daily_ohlcv__phantomq_bak_20261017. NULL-close remaining=131-58=73 "
     "(HOLX 28, CTRA 28, MATIC-USD 15, US 2 on 06-01)"))
conn.commit()
conn.close()
print("DONE")
