#!/usr/bin/env python3
"""Apply + populate gold.paper_trade_entry_price_audit for backfill-era (stamped 2026-08-05)
paper entries. Kanban t_baf767e2. Append-only; never touches paper_trades_synthetic.

Policy:
- vintage = declared entry_price_source_date, else best-match close date in +-45d window.
- convention window for stamped 2026-08-05 (Wed) entry: source in {08-03, 08-04, 08-05}.
- CORRECT: vintage stale (< 2026-08-03) AND |dev vs stamped close| > 0.5%
    -> corrected_entry_price = stamped-date silver.unified_prices close.
- FLAG: near-convention vintage with restatement drift (MATCH_NEITHER, vintage in window).
- OK: MATCH_SOURCE/MATCH_ENTRY within convention window.
"""
import csv, json, sys
import psycopg2

DSN = "postgresql://openclaw_user:NewStrongPasswordHere12@127.0.0.1:5433/aitrading?sslmode=require"
SNAPSHOT_ID = "entry_audit_20260805_20261028"
MIGRATION = "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/migrations/2026-10-28_paper_entry_price_audit_backfill.sql"
WS = "/home/ubuntu/.hermes/kanban/boards/trading/workspaces/t_baf767e2"
STALE_CUTOFF = "2026-08-03"  # vintage < this is stale (window = 08-03..08-05)
DEV_TOL_PCT = 0.5

conn = psycopg2.connect(DSN)
conn.autocommit = False
cur = conn.cursor()

# 1. migration
with open(MIGRATION) as f:
    cur.execute(f.read())
print("migration applied")

# 2. pull backfill-era rows
cur.execute("""
SELECT id, strategy_id, ticker, entry_date, entry_price, entry_price_source_date,
       entry_price_basis, status, n_shares, exit_date, exit_price, pnl
FROM gold.paper_trades_synthetic
WHERE entry_date = '2026-08-05'
ORDER BY strategy_id, ticker
""")
rows = cur.fetchall()
assert len(rows) == 55, f"expected 55 rows, got {len(rows)}"

def close_on(ticker, d):
    if d is None: return None
    cur.execute("SELECT close FROM silver.unified_prices WHERE ticker=%s AND date=%s", (ticker, d))
    r = cur.fetchone()
    return float(r[0]) if r else None

def best_vintage(ticker, ep):
    cur.execute("""
        SELECT date, close, ABS(close - %s)/%s AS rel
        FROM silver.unified_prices
        WHERE ticker=%s AND date BETWEEN '2026-06-20' AND '2026-09-20'
        ORDER BY rel LIMIT 1
    """, (ep, ep, ticker))
    r = cur.fetchone()
    return (r[0], float(r[1]), float(r[2])) if r else (None, None, None)

audits = []
for (tid, sid, tkr, edate, ep, sdate, basis, status, nsh, xdate, xprice, pnl) in rows:
    ep = float(ep); nsh = float(nsh)
    c_entry = close_on(tkr, edate)
    c_src = close_on(tkr, sdate)
    dev_e = (ep - c_entry) / c_entry * 100 if c_entry else None
    dev_s = (ep - c_src) / c_src * 100 if c_src else None
    tol = 0.2  # pct
    if dev_s is not None and abs(dev_s) <= tol:
        cls, vintage = 'MATCH_SOURCE', sdate
    elif dev_e is not None and abs(dev_e) <= tol:
        cls, vintage = 'MATCH_ENTRY', edate
    else:
        cls = 'MATCH_NEITHER'
        vdate, vclose, vrel = best_vintage(tkr, ep)
        vintage = vdate
    stale = vintage is not None and vintage.isoformat() < STALE_CUTOFF
    if stale and dev_e is not None and abs(dev_e) > DEV_TOL_PCT:
        action, reason, corr = 'CORRECT', 'STALE_VINTAGE', c_entry
    elif cls == 'MATCH_NEITHER':
        action, reason, corr = 'FLAG', 'NEAR_CONVENTION_RESTATEMENT_DRIFT' if not stale else 'STALE_VINTAGE_SUBTHRESHOLD', None
    else:
        action, reason, corr = 'OK', 'CONVENTION', None
    audits.append(dict(trade_id=tid, strategy_id=sid, ticker=tkr, stamped_entry_date=edate,
                       ledger_entry_price=ep, source_date=sdate, basis=basis,
                       stamped_close=c_entry, source_close=c_src,
                       dev_e=dev_e, dev_s=dev_s, vintage=vintage, cls=cls,
                       action=action, reason=reason, corrected=corr,
                       status=status, n_shares=nsh, exit_date=xdate, exit_price=float(xprice) if xprice else None,
                       pnl=float(pnl) if pnl is not None else None))

n_corr = sum(1 for a in audits if a['action'] == 'CORRECT')
n_flag = sum(1 for a in audits if a['action'] == 'FLAG')
n_ok = sum(1 for a in audits if a['action'] == 'OK')
print(f"audit: {len(audits)} rows -> CORRECT={n_corr} FLAG={n_flag} OK={n_ok}")

# 3. insert (idempotent per task_id: skip if already populated)
cur.execute("SELECT count(*) FROM gold.paper_trade_entry_price_audit WHERE task_id='t_baf767e2'")
if cur.fetchone()[0] > 0:
    print("ALREADY POPULATED for t_baf767e2 — skipping insert")
else:
    for a in audits:
        cur.execute("""
            INSERT INTO gold.paper_trade_entry_price_audit
            (trade_id, strategy_id, ticker, stamped_entry_date, ledger_entry_price, source_date,
             entry_price_basis, stamped_close, source_close, dev_vs_stamped_pct, dev_vs_source_pct,
             vintage_date, classification, action, flag_reason, corrected_entry_price, status_at_audit)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (a['trade_id'], a['strategy_id'], a['ticker'], a['stamped_entry_date'], a['ledger_entry_price'],
              a['source_date'], a['basis'], a['stamped_close'], a['source_close'],
              round(a['dev_e'], 4) if a['dev_e'] is not None else None,
              round(a['dev_s'], 4) if a['dev_s'] is not None else None,
              a['vintage'], a['cls'], a['action'], a['reason'], a['corrected'], a['status']))
    print(f"inserted {len(audits)} audit rows")

# 4. guard-trigger verification (in-transaction, rolled back via savepoint)
cur.execute("SAVEPOINT g1")
try:
    cur.execute("UPDATE gold.paper_trade_entry_price_audit SET flag_reason='X' WHERE trade_id=2469")
    print("GUARD FAIL: UPDATE allowed"); sys.exit(1)
except psycopg2.errors.RaiseException as e:
    print(f"guard OK: UPDATE rejected ({e.diag.message_primary})")
    cur.execute("ROLLBACK TO SAVEPOINT g1")
cur.execute("SAVEPOINT g2")
try:
    cur.execute("DELETE FROM gold.paper_trade_entry_price_audit WHERE trade_id=2469")
    print("GUARD FAIL: DELETE allowed"); sys.exit(1)
except psycopg2.errors.RaiseException as e:
    print(f"guard OK: DELETE rejected ({e.diag.message_primary})")
    cur.execute("ROLLBACK TO SAVEPOINT g2")

# 5. snapshot log
cur.execute("SELECT count(*) FROM gold.etl_snapshot_log WHERE snapshot_id=%s", (SNAPSHOT_ID,))
if cur.fetchone()[0] == 0:
    cur.execute("""
        INSERT INTO gold.etl_snapshot_log (snapshot_id, scope, script, pre_rows, pre_max_date, post_rows, post_max_date, note)
        VALUES (%s, 'gold.paper_trade_entry_price_audit', 'audit/apply_paper_entry_price_audit_t_baf767e2.py',
                0, NULL, %s, NULL, %s)
    """, (SNAPSHOT_ID, len(audits),
          f"append-only audit+corrections for 55 backfill-era (2026-08-05) paper entries; CORRECT={n_corr} FLAG={n_flag} OK={n_ok}; entry_price untouched"))
    print("snapshot logged")

conn.commit()
print("COMMITTED")

# 6. P&L impact (report-only, post-commit)
cur2 = conn.cursor()
cur2.execute("SELECT strategy_id, assigned_capital FROM gold.strategy_registry")
cap = {r[0]: float(r[1]) for r in cur2.fetchall()}
def latest_close(t):
    cur2.execute("SELECT close FROM silver.unified_prices WHERE ticker=%s ORDER BY date DESC LIMIT 1", (t,))
    r = cur2.fetchone(); return float(r[0]) if r else None

impact = {}
for a in audits:
    if a['action'] != 'CORRECT':
        continue
    delta = (a['ledger_entry_price'] - a['corrected']) * a['n_shares']  # P&L change in local ccy
    imp = impact.setdefault(a['strategy_id'], {'delta': 0.0, 'rows': []})
    imp['delta'] += delta
    imp['rows'].append(a)

print("\n=== P&L IMPACT (delta = (ledger-corrected)*shares; negative = P&L decreases) ===")
for sid, imp in sorted(impact.items()):
    pct = imp['delta'] / cap.get(sid, 1) * 100
    mover = '>>> MOVES >1%' if abs(pct) > 1 else ''
    print(f"{sid:24s} delta={imp['delta']:>12.2f}  vs assigned {cap.get(sid)}: {pct:+.2f}% {mover}")
    for a in imp['rows']:
        kind = 'OPEN->unrealized' if a['status'] == 'open' else f"closed {a['exit_date']}"
        print(f"   {a['ticker']:10s} {a['n_shares']:>8.0f}sh entry {a['ledger_entry_price']:.4f} -> {a['corrected']:.4f}  ({a['dev_e']:+.2f}%) [{kind}]")

# unrealized before/after for open corrected rows
print("\n=== OPEN-POSITION UNREALIZED before/after (local ccy) ===")
for sid, imp in sorted(impact.items()):
    for a in imp['rows']:
        if a['status'] != 'open':
            continue
        lc = latest_close(a['ticker'])
        if lc is None: continue
        before = (lc - a['ledger_entry_price']) * a['n_shares']
        after = (lc - a['corrected']) * a['n_shares']
        print(f"   {sid:22s} {a['ticker']:8s} last={lc:.4f}  unreal {before:>10.2f} -> {after:>10.2f}")

# 7. hand-check 5 names
print("\n=== HAND-CHECK (silver.unified_prices closes) ===")
for t in ['2388.HK', '0939.HK', '0001.HK', '0005.HK', '1398.HK']:
    cur2.execute("""
        SELECT date, close FROM silver.unified_prices
        WHERE ticker=%s AND date IN ('2026-07-17','2026-08-04','2026-08-05') ORDER BY date
    """, (t,))
    print(f"  {t}: " + "  ".join(f"{r[0]}={float(r[1]):.4f}" for r in cur2.fetchall()))

# artifacts
with open(f"{WS}/paper_entry_audit_2026-08-05.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(audits[0].keys()))
    w.writeheader()
    for a in audits:
        w.writerow(a)
print(f"\nCSV written: {WS}/paper_entry_audit_2026-08-05.csv ({len(audits)} rows)")
conn.close()
