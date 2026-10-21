#!/usr/bin/env python3
"""Ad-hoc verification for t_aa97c50d rewire of gold/fx/build_fx_metrics.py.

Runs the rewired builder repeatedly (idempotency) and asserts:
  1. Builder exits clean; upsert count matches silver alias rows in the 14d window.
  2. All 7 FX tickers in gold.fx_metrics have max(date) == silver max(date).
  3. Zero null closes; no indicator NULLs from 2026-06-24 onward
     (2026-06-24 is past NZDUSD's legitimate 14-obs warmup within the gap).
  4. Gold close_price matches silver close exactly for recent rows.
  5. Row count stable across a third run (idempotent upsert).
  6. NZDUSD full history present (2017-01-05, 2493 rows).
"""
import os, re, subprocess, sys

ETL = os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl')
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection  # noqa: E402

failures = []

def check(name, cond, detail=''):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        failures.append(name)

def run_builder():
    return subprocess.run([sys.executable, 'gold/fx/build_fx_metrics.py'],
                          cwd=ETL, capture_output=True, text=True, timeout=300)

r1 = run_builder()
check('builder run 1 exit 0', r1.returncode == 0,
      (r1.stderr.strip()[-200:] if r1.returncode else r1.stdout.strip().splitlines()[0]))
r2 = run_builder()
check('builder run 2 exit 0', r2.returncode == 0, r2.stderr.strip()[-200:] if r2.returncode else '')

conn = get_connection()
cur = conn.cursor()

cur.execute("""SELECT count(*) FROM silver.unified_prices
               WHERE ticker ~ '^[A-Z]{6}$' AND date >= CURRENT_DATE - 14
                 AND ticker || '=X' IN (SELECT ticker FROM gold.asset_registry
                                        WHERE is_active AND asset_class IN ('FX','CURRENCY'))""")
silver_n = cur.fetchone()[0]
m = re.search(r'updated: (\d+) rows upserted', r1.stdout)
upserted = int(m.group(1)) if m else -1
check('upsert count == silver alias rows in 14d window', upserted == silver_n,
      f'upserted={upserted} silver={silver_n}')

cur.execute("""SELECT g.ticker, max(g.date)::date,
                      (SELECT max(s.date) FROM silver.unified_prices s WHERE s.ticker = g.ticker)
               FROM gold.fx_metrics g GROUP BY g.ticker ORDER BY 1""")
rows = cur.fetchall()
check('7 tickers present', len(rows) == 7, f'got {len(rows)}')
stale = [(t, str(g), str(s)) for t, g, s in rows if g != s]
check('gold max(date) == silver max(date) all tickers', not stale, f'stale={stale}')

cur.execute("SELECT count(*) FROM gold.fx_metrics WHERE close_price IS NULL")
check('zero null closes', cur.fetchone()[0] == 0)

cur.execute("""SELECT ticker, count(*) FROM gold.fx_metrics
               WHERE date >= '2026-06-24'
                 AND (rsi_14 IS NULL OR atr_14 IS NULL OR macd_line IS NULL
                      OR macd_signal IS NULL OR macd_histogram IS NULL)
               GROUP BY ticker""")
bad = cur.fetchall()
check('no indicator NULLs from 2026-06-24 onward', not bad, f'violations={bad}')

cur.execute("""SELECT count(*) FROM gold.fx_metrics g
               JOIN silver.unified_prices s ON s.ticker = g.ticker AND s.date = g.date::date
               WHERE g.date >= CURRENT_DATE - 5 AND g.close_price <> s.close""")
check('gold close_price == silver close (last 5d)', cur.fetchone()[0] == 0)

cur.execute("SELECT count(*) FROM gold.fx_metrics")
n_before = cur.fetchone()[0]
r3 = run_builder()
check('builder run 3 exit 0', r3.returncode == 0, r3.stderr.strip()[-200:] if r3.returncode else '')
cur.execute("SELECT count(*) FROM gold.fx_metrics")
n_after = cur.fetchone()[0]
check('row count stable across reruns (idempotent)', n_before == n_after, f'{n_before} -> {n_after}')

cur.execute("SELECT min(date)::date, count(*) FROM gold.fx_metrics WHERE ticker='NZDUSD'")
mn, n = cur.fetchone()
check('NZDUSD full history (2017-01-05, 2493 rows)', str(mn) == '2017-01-05' and n == 2493,
      f'min={mn} n={n}')

conn.close()
print()
print('RESULT:', 'ALL PASS' if not failures else f'{len(failures)} FAILURES: {failures}')
sys.exit(1 if failures else 0)