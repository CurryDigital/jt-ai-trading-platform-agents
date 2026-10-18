#!/usr/bin/env python3
"""Golden-file test — composite_30_91_182_365d rank vs rerun_results.json
(OVERLAY_RESTATE_DECISION_MEMO §6 test (iii)).

For each Friday decision bar in b_compare.rows (2026-07-31 → 2026-10-15),
compute the composite rank over the sleeve universe from silver.unified_prices
and assert the top-4 set EQUALS the golden composite_set exactly. W-FRI bars;
the 1-bar lag (positions earn from the next bar) is a position-timing rule,
not a set rule — the golden sets are the decision-bar holdings.

Also prints the rank-function sha256 (signal-definition hash candidate).
"""
import hashlib
import inspect
import json
import os
import sys

ETL = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
sys.path.insert(0, os.path.join(ETL, "shared", "scripts"))
sys.path.insert(0, "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/signals/pipeline")
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
import db
import pandas as pd
from build_rotation_signals import composite_30_91_182_365d_score

GOLDEN = "/home/ubuntu/.hermes/profiles/qr_research/workspace/kat_followups_v1/rerun_results.json"
UNIVERSE = ['SPY', 'XLF', 'XLK', 'XLE', 'XLI', 'XLP', 'XLU', 'XLB', 'SMH', 'IWM']
TOP_N = 4

# rank-function hash (signal-definition hash candidate for cutover)
src = inspect.getsource(composite_30_91_182_365d_score)
h = hashlib.sha256(src.encode()).hexdigest()
print(f"rank-function sha256: {h}")

rows = json.load(open(GOLDEN))['b_compare']['rows']
fridays = [r['friday'] for r in rows]
print(f"golden weeks: {len(fridays)} ({fridays[0]} → {fridays[-1]})")

conn = db.get_connection()
cur = conn.cursor()
cur.execute("""
    SELECT ticker, date, close FROM silver.unified_prices
    WHERE ticker = ANY(%s) AND close IS NOT NULL
      AND date >= '2025-01-01' AND date <= %s
    ORDER BY ticker, date""", (UNIVERSE, fridays[-1]))
data = cur.fetchall()
conn.close()
df = pd.DataFrame(data, columns=['ticker', 'date', 'close'])
df['date'] = pd.to_datetime(df['date'])
df['close'] = pd.to_numeric(df['close'], errors='coerce').astype(float)

fails = []
for row in rows:
    F = pd.Timestamp(row['friday'])
    scores = {}
    for t in UNIVERSE:
        px = (df[df['ticker'] == t].set_index('date')['close'].sort_index())
        px = px[px.index <= F]
        if len(px) == 0 or px.index[-1] != F:
            scores[t] = None  # no bar at the decision Friday
            continue
        scores[t] = composite_30_91_182_365d_score(px, F)
    ranked = sorted([(t, s) for t, s in scores.items() if s is not None and pd.notna(s)],
                    key=lambda x: x[1], reverse=True)
    got = [t for t, _ in ranked[:TOP_N]]
    want = row['composite_set']  # golden stores sets alphabetically sorted
    ok = sorted(got) == sorted(want)
    if not ok:
        fails.append((row['friday'], want, got))
    print(f"{row['friday']}: {'OK ' if ok else 'DIFF'} want={sorted(want)} got={sorted(got)}")

print("GOLDEN TEST:", "PASS" if not fails else f"FAIL ({len(fails)} weeks differ)")
sys.exit(0 if not fails else 1)
