#!/usr/bin/env python3
"""Exchange-calendar phantom removal (user directive item 1, re-run result).

Rows on days the exchange was CLOSED (per gold.exchange_holidays /
us_market_holidays), all zero-volume flat/placeholder bars:
  SG holidays: 2019-01-01 (92), 2019-02-05 CNY (92), 2019-12-25 (93),
    2026-05-01 (1), 2026-05-27 Hari Raya Haji (92), 2026-06-01 Vesak obs (2,
    silver only), 2026-08-10 National Day obs (2)
  HK: 8182.HK flat 0.113 placeholder on 10 HK holidays (2018-2019)
  ^VIX: 4 zero-volume rows on US holidays (silver only; VIX doesn't print
    on holidays)
JPY=X US-holiday rows are LEGIT (FX trades US holidays; market mislabeled
'US' — relabel flagged separately, data kept).
"""
import os, sys
ETL = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
sys.path.insert(0, os.path.join(ETL, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db

REASON = "exchange_holiday_phantom_2026_10_17"
conn = db.get_connection()
cur = conn.cursor()

SETS = {
    "SG": ("market='SG' AND extract(isodow from date) BETWEEN 1 AND 5 "
           "AND date IN (SELECT holiday_date FROM gold.exchange_holidays WHERE market='SG')"),
    "HK": ("market='HK' AND ticker='8182.HK' AND extract(isodow from date) BETWEEN 1 AND 5 "
           "AND date IN (SELECT holiday_date FROM gold.exchange_holidays WHERE market='HK')"),
    "VIX": ("ticker='^VIX' AND extract(isodow from date) BETWEEN 1 AND 5 "
            "AND date IN (SELECT holiday_date FROM gold.us_market_holidays)"),
}

tot_q, tot_d = 0, 0
for name, cond in SETS.items():
    for tbl, pk in (("silver.unified_prices", "(ticker, date)"),
                    ("gold.daily_ohlcv", "(ticker, date)")):
        # quarantine (copy full bar values first)
        cur.execute(f"""
            INSERT INTO bronze.yf_suspect_bars
                (ticker, date, open, high, low, close, volume, adjusted_close,
                 reason, detected_at)
            SELECT ticker, date, open, high, low, close, volume, adjusted_close,
                   %s, NOW()
            FROM {tbl} WHERE {cond}
            ON CONFLICT (ticker, date) DO NOTHING""", (REASON,))
        nq = cur.rowcount
        cur.execute(f"DELETE FROM {tbl} WHERE {cond}")
        nd = cur.rowcount
        print(f"{name} {tbl}: quarantined {nq}, deleted {nd}")
        tot_q += nq; tot_d += nd

cur.execute("SELECT count(*) FROM bronze.yf_suspect_bars")
sus = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM gold.daily_ohlcv")
g = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM silver.unified_prices")
s = cur.fetchone()[0]
print(f"TOTALS: quarantined {tot_q}, deleted {tot_d}; "
      f"suspect_bars={sus} gold={g} silver={s}")

cur.execute("""
    INSERT INTO gold.etl_snapshot_log (snapshot_id, scope, script, pre_rows, post_rows, note)
    VALUES (%s,%s,%s,%s,%s,%s)""",
    ("exchange_holiday_phantoms_20261017",
     "holiday phantom removal (SG clusters, HK 8182.HK, ^VIX) after calendar modeling",
     "workspace/oneoff/exchange_holiday_phantom_delete_2026_10_17.py",
     g + s + tot_d, g + s,
     f"reason={REASON}; quarantined {tot_q}, deleted {tot_d}; calendars from "
     "workspace/exchange_calendars (SG 89/HK 134/CN 165 loaded); JPY=X US-holiday "
     "rows legit (FX trades US holidays) — market label 'US' flagged for relabel"))
conn.commit()
conn.close()
print("DONE")
