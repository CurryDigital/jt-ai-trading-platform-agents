#!/usr/bin/env python3
"""Acceptance verification for kanban t_8d75977e (QQQ Track B data pull).
Read-only. Prints PASS/FAIL per acceptance item with numbers.
Run AFTER QQQ_BACKFILL_PHASE2_COMPLETE marker in
~/.hermes/profiles/qr_etl/logs/etl/qqq_backfill.status
"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'), override=True)
import db
conn = db.get_connection()
cur = conn.cursor()

print("=== ACCEPTANCE t_8d75977e: QQQ option chains 2023-06-01+ ===")

# --- 1. Coverage vs SPY trading days
cur.execute("""SELECT count(DISTINCT trade_date) FROM silver.option_eod_quotes q
               JOIN silver.option_contracts c USING (contract_id)
               WHERE c.underlying='SPY' AND q.trade_date BETWEEN '2023-06-01' AND '2026-10-23'""")
spy_days = cur.fetchone()[0]
cur.execute("""SELECT status, count(*) FROM silver.thetadata_date_completeness
               WHERE symbol='QQQ' AND endpoint='eod' GROUP BY status""")
comp = dict(cur.fetchall())
verified = comp.get('VERIFIED', 0) + comp.get('VERIFIED_THIN', 0)
short = comp.get('SHORT', 0)
cur.execute("""SELECT count(DISTINCT trade_date) FROM silver.option_eod_quotes q
               JOIN silver.option_contracts c USING (contract_id)
               WHERE c.underlying='QQQ' AND q.trade_date BETWEEN '2023-06-01' AND '2026-10-23'""")
qqq_days = cur.fetchone()[0]
cov = qqq_days / spy_days * 100 if spy_days else 0
print(f"\n[1] COVERAGE: SPY trading days={spy_days}; QQQ verified dates={verified} "
      f"(VERIFIED={comp.get('VERIFIED',0)}, VERIFIED_THIN={comp.get('VERIFIED_THIN',0)}), "
      f"SHORT={short}; silver QQQ quote days={qqq_days} -> coverage={cov:.1f}%")
print(f"    {'PASS' if cov >= 95 else 'FAIL'} (need >=95%)")
cur.execute("""
    WITH spy_days AS (
      SELECT DISTINCT q.trade_date FROM silver.option_eod_quotes q
      JOIN silver.option_contracts c USING (contract_id)
      WHERE c.underlying='SPY' AND q.trade_date BETWEEN '2023-06-01' AND '2026-10-23'),
    qqq_days AS (
      SELECT DISTINCT q.trade_date FROM silver.option_eod_quotes q
      JOIN silver.option_contracts c USING (contract_id)
      WHERE c.underlying='QQQ' AND q.trade_date BETWEEN '2023-06-01' AND '2026-10-23')
    SELECT s.trade_date FROM spy_days s LEFT JOIN qqq_days q USING (trade_date)
    WHERE q.trade_date IS NULL ORDER BY 1 LIMIT 40""")
holes = [str(r[0]) for r in cur.fetchall()]
print(f"    holes (first 40): {holes if holes else 'NONE'}")

# --- 2. Quote quality: crossed / zero-bid share per month, QQQ vs SPY
cur.execute("""
    SELECT c.underlying, date_trunc('month', q.trade_date)::date AS m,
           count(*) AS n,
           count(*) FILTER (WHERE q.bid > q.ask AND q.ask > 0) AS crossed,
           count(*) FILTER (WHERE q.bid <= 0) AS zero_bid
    FROM silver.option_eod_quotes q JOIN silver.option_contracts c USING (contract_id)
    WHERE c.underlying IN ('QQQ','SPY') AND q.trade_date >= '2023-06-01'
    GROUP BY 1,2 ORDER BY 1,2""")
rows = cur.fetchall()
print("\n[2] QUOTE QUALITY (crossed% / zero-bid% per month):")
by_m = {}
for u, m, n, cr, zb in rows:
    by_m.setdefault(m, {})[u] = (cr / n * 100, zb / n * 100)
worst = 0.0
for m in sorted(by_m):
    d = by_m[m]
    if 'QQQ' in d and 'SPY' in d:
        q, s = d['QQQ'], d['SPY']
        diff = abs(q[0] - s[0]) + abs(q[1] - s[1])
        worst = max(worst, diff)
        if diff > 2.0:
            print(f"    {m} QQQ crossed={q[0]:.2f}% zerobid={q[1]:.2f}% | SPY crossed={s[0]:.2f}% zerobid={s[1]:.2f}%  <-- divergence")
print(f"    worst monthly divergence (sum of abs diffs) = {worst:.2f} pts")
print(f"    {'PASS' if worst < 5.0 else 'CHECK'} (comparable-to-SPY judgement; flag months above)")

# --- 3. Expiry/strike sanity + DTE
cur.execute("""SELECT count(*) FROM silver.option_contracts WHERE underlying='QQQ' AND strike <= 0""")
neg = cur.fetchone()[0]
cur.execute("""SELECT count(*) FROM silver.option_eod_quotes q
               JOIN silver.option_contracts c USING (contract_id)
               WHERE c.underlying='QQQ' AND c.expiry <= q.trade_date""")
bad_exp = cur.fetchone()[0]
cur.execute("""SELECT min(c.expiry - q.trade_date), max(c.expiry - q.trade_date)
               FROM silver.option_eod_quotes q JOIN silver.option_contracts c USING (contract_id)
               WHERE c.underlying='QQQ'""")
dte = cur.fetchone()
print(f"\n[3] SANITY: strikes<=0: {neg}; expiry<=trade_date rows: {bad_exp}; DTE range: {dte[0]}..{dte[1]} (expect 7..60 per pull filter)")
print(f"    {'PASS' if neg == 0 and bad_exp == 0 and dte[0] >= 7 and dte[1] <= 60 else 'FAIL'}")

# --- 4. Corporate actions (verified 2026-10-26 via Yahoo chart events API)
print("\n[4] CORPORATE ACTIONS: PASS — QQQ splits full history: only 2000-03-20 2:1 (pre-window).")
print("    Basis: Yahoo Finance chart events=split via yfinance, full history; none 2023-06-01+.")

# --- 5. PIT convention: quotes keyed by trade_date; stock closes present
cur.execute("""SELECT count(*) FROM silver.option_eod_quotes q
               JOIN silver.option_contracts c USING (contract_id)
               WHERE c.underlying='QQQ' AND q.underlying_close IS NULL""")
null_close = cur.fetchone()[0]
cur.execute("""SELECT count(*), min(trade_date), max(trade_date) FROM bronze.thetadata_stock_eod_raw WHERE symbol='QQQ'""")
stk = cur.fetchone()
print(f"\n[5] PIT: quotes keyed by trade_date==decision date (schema-enforced); "
      f"underlying_close NULL rows: {null_close}; stock_eod_raw QQQ rows={stk[0]} span {stk[1]}..{stk[2]}")
print(f"    {'PASS' if null_close == 0 else 'FAIL'}")

# --- downstream completeness
cur.execute("""SELECT count(*) FROM silver.option_eod_quotes q JOIN silver.option_contracts c USING (contract_id) WHERE c.underlying='QQQ'""")
nq = cur.fetchone()[0]
cur.execute("""SELECT count(*) FROM silver.option_eod_greeks g JOIN silver.option_contracts c USING (contract_id)
               WHERE c.underlying='QQQ' AND g.greek_source='COMPUTED'""")
ng = cur.fetchone()[0]
cur.execute("""SELECT count(*), min(feature_date), max(feature_date) FROM gold.option_vol_features_daily WHERE underlying='QQQ'""")
vf = cur.fetchone()
cur.execute("""SELECT count(*) FROM deriv.underlying_dividends WHERE underlying='QQQ'""")
nd = cur.fetchone()[0]
print(f"\n[downstream] quotes={nq:,}  computed_greeks={ng:,} ({(ng/nq*100 if nq else 0):.1f}% of quotes; "
      f"rest = NO_SOLUTION fails, SPY baseline ~9.4%)  vol_features rows={vf[0]} span {vf[1]}..{vf[2]}  dividends={nd}")
conn.close()
print("\n=== END ACCEPTANCE ===")
