#!/usr/bin/env python3
"""Ad-hoc verification for kanban t_0a520c52: capital raise $10k->$100k for
COMM_GoldSilver_Ratio_MeanRev_VolTarget + paper-book rebuild.

Asserts end-state invariants against the live RDS DB:
  1. registry assigned_capital == 100000
  2. exactly one open position: GC=F LONG 8 units, assigned_capital 100000
  3. notional ~= 0.33 x 100000 (tolerance: one unit price)
  4. signal rows unchanged: CASH HOLD / GC=F BUY / SI=F SELL

NOT a test suite -- ad-hoc verification only. Deleted after run.
(NOTE: intended for /tmp per verification convention; the write tool's
filesystem intermittently rejects /tmp and the kanban scratch path --
shadow-FS split-brain -- so it lives here, a path visible to both tools.)
"""
import sys

sys.path.insert(0, "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts")
from db import get_connection

SID = "COMM_GoldSilver_Ratio_MeanRev_VolTarget"
failures = []

def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        failures.append(name)

conn = get_connection()
cur = conn.cursor()

cur.execute("SELECT assigned_capital, execution_mode, retired_at FROM gold.strategy_registry WHERE strategy_id=%s", (SID,))
row = cur.fetchone()
check("registry row exists", row is not None)
check("assigned_capital == 100000", row is not None and float(row[0]) == 100000.0, f"got={row[0] if row else None}")
check("execution_mode == PAPER, not retired", row is not None and row[1] == "PAPER" and row[2] is None)

cur.execute("""
    SELECT ticker, direction, entry_price, n_shares, assigned_capital
    FROM gold.paper_trades_synthetic WHERE strategy_id=%s AND status='open'
""", (SID,))
pos = cur.fetchall()
check("exactly 1 open position", len(pos) == 1, f"got={len(pos)}")
if pos:
    t, d, px, n, cap = pos[0]
    check("position is GC=F LONG 8 units", t == "GC=F" and d == "LONG" and float(n) == 8.0,
          f"got={t} {d} {n}")
    check("position stamped with new capital", float(cap) == 100000.0, f"got={cap}")
    notional = float(px) * float(n)
    check("notional ~ 0.33 x 100000 within 1 unit", abs(notional - 33000.0) <= float(px),
          f"notional={notional}")

cur.execute("""
    SELECT ticker, signal FROM consumption.strategies_signals_current
    WHERE strategy_id=%s ORDER BY ticker
""", (SID,))
sig = dict(cur.fetchall())
check("signals unchanged (CASH HOLD / GC=F BUY / SI=F SELL)",
      sig.get("CASH") == "HOLD" and sig.get("GC=F") == "BUY" and sig.get("SI=F") == "SELL",
      f"got={sig}")

cur.close()
conn.close()

print()
if failures:
    print(f"AD-HOC VERIFICATION FAILED: {len(failures)} check(s): {failures}")
    sys.exit(1)
print("AD-HOC VERIFICATION PASSED: 8/8 checks (ad-hoc, not a suite run)")
