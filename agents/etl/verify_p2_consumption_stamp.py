#!/usr/bin/env python3
"""Read-only verify: consumption.strategies_signals_current re-stamp + eval API recent_signals."""
import json, os, sys
import psycopg2

def read_env(pid):
    env = {}
    with open(f"/proc/{pid}/environ", "rb") as f:
        for kv in f.read().decode(errors="replace").split("\0"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                env[k] = v
    return env

env = read_env(3296465)
conn = psycopg2.connect(
    host=env["DB_HOST"], port=env["DB_PORT"], dbname=env["DB_NAME"],
    user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10)
cur = conn.cursor()
cur.execute("""
    SELECT strategy_id, ticker, signal, updated_at
    FROM consumption.strategies_signals_current
    WHERE strategy_id IN ('hk_ipo_postlisting_drift_p2','hk_ipo_day1_green_momentum_v1')
    ORDER BY 1,2
""")
rows = cur.fetchall()
print(f"DB rows: {len(rows)}")
ok_stamp = True
for r in rows:
    today = str(r[3]).startswith("2026-09-07")
    if not today:
        ok_stamp = False
    print(f"  {r[0]:35s} {r[1]:15s} {r[2]:6s} updated_at={r[3]} today={today}")
cur.close(); conn.close()

for sid, path in [("hk_ipo_postlisting_drift_p2", "/tmp/eval_p2.json"),
                  ("hk_ipo_day1_green_momentum_v1", "/tmp/eval_v1.json")]:
    with open(path) as f:
        data = json.load(f)
    sigs = data.get("recent_signals", [])
    found = [s for s in sigs if s.get("ticker") == "HK_IPO_EVENTS"]
    print(f"API {sid}: recent_signals={len(sigs)} HK_IPO_EVENTS rows={len(found)}")
    for s in found:
        print(f"  {json.dumps({k: s.get(k) for k in ('ticker','signal','updated_at','as_of') if k in s})}")
    if not found:
        print("  !! HK_IPO_EVENTS HOLD row MISSING from recent_signals")

print("VERDICT:", "GREEN" if ok_stamp and len(rows) == 4 else "YELLOW/RED")
