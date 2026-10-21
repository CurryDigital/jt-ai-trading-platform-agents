#!/usr/bin/env python3
"""
One-off DATA_FIX: split-factor backfill for 7 unadjusted names
(kanban t_8866358c, qr_research SLEEVE_WFV2_FOLLOWUP_REPORT 5b, 2026-10-15).

Problem: gold.daily_ohlcv + silver.unified_prices hold RAW (pre-split scale)
prices for CVNA, KLAC, DD, CRWD, MNST, APH, CTVA. yfinance now serves these
fully back-adjusted (verified 2026-10-15: yf raw 'Close' is continuous across
the split dates; our DB rows match yf post-split scale FROM the boundary date
and are factor*x pre-boundary).

Split events (boundary = first post-split trading day IN OUR DATA, verified by
matching DB close == yf close; NOTE yf's splits-index dates are ~1-9 days
LATER than the price boundary for 5 names — the price series is authoritative):

  ticker  boundary     factor (new shares per 1 old)   source
  CVNA    2026-04-29   5.0        yf actions 2026-05-08 5.0
  KLAC    2026-06-03   10.0       yf actions 2026-06-12 10.0
  DD      2026-06-18   1/3        yf actions 2026-06-24 0.333333 (1:3 reverse)
  CRWD    2026-06-22   4.0        yf actions 2026-07-02 4.0
  MNST    2026-08-10   2.0        yf actions 2026-08-11 2.0
  APH     2026-09-03   2.0        yf actions 2026-09-03 2.0 (date matches)
  CTVA    2026-10-01   6.665      yf actions 2026-10-01 6.665 (date matches)

Adjustment rule for rows with date < boundary:
  open/high/low/close/adjusted_close  := value / factor
  volume                              := volume * factor (rounded for bigint)

Table specifics:
- gold.daily_ohlcv: full history raw for all 7 (verified). Blanket adjust.
- silver.unified_prices: MIXED for DD/CRWD — a post-split bronze refresh
  overwrote recent pre-split rows with already-adjusted values (first
  divergent row vs gold: DD 2026-06-15, CRWD 2026-06-15). Per-row detection
  against gold (gold adjusted AFTER silver in this script, so gold is still
  the raw reference): |s/g - 1| < 2%  -> raw -> adjust;
  |s*factor/g - 1| < 2% -> already adjusted -> skip; else -> anomaly, report.
- bronze.yf_prices: same per-row detection (DD/CRWD already adjusted; other 5
  raw). Fixed so the nightly silver merge (clean_unified_prices.py upsert over
  bronze history) cannot reintroduce the jump. Also stamps stock_splits on the
  boundary date as an event marker.

After adjustment, returns_1d (gold, silver) and returns_log (silver) are
recomputed per ticker over full history.

Backups created before any write:
  gold.daily_ohlcv__splitfix_bak_20261015
  silver.unified_prices__splitfix_bak_20261015
  bronze.yf_prices__splitfix_bak_20261015

Usage:
  python3 split_factor_backfill_2026_10_15.py            # dry-run report
  python3 split_factor_backfill_2026_10_15.py --apply    # write

Author: qr_etl  Date: 2026-10-15
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

APPLY = '--apply' in sys.argv

SPLITS_ALL = {
    'CVNA': ('2026-04-29', 5.0),
    'KLAC': ('2026-06-03', 10.0),
    'DD':   ('2026-06-18', 1.0/3.0),
    'CRWD': ('2026-06-22', 4.0),
    'MNST': ('2026-08-10', 2.0),
    'APH':  ('2026-09-03', 2.0),
    'CTVA': ('2026-10-01', 6.665),
    # 2026-10-15 follow-up: universe scan (step 3 of t_8866358c) found BKNG as
    # an 8th unadjusted split: gold -96.1% on 2026-03-02, yf actions 25.0
    # (recorded 2026-04-06, price boundary 2026-03-02), factor verified
    # 4239.35/25 = 169.57 == yf 2026-02-27 close 169.6.
    'BKNG': ('2026-03-02', 25.0),
    # Universe scan step-3 HK finds (yf split action date == DB jump date,
    # DB pre-boundary close == factor x yf close exactly, DB == yf post):
    #   2670.HK: 85.7/8.57 = 10.0 exact; 3636.HK: 15.8/6.32 = 2.5 exact.
    '2670.HK': ('2026-09-23', 10.0),
    '3636.HK': ('2026-10-15', 2.5),
}
ONLY = None
if '--only' in sys.argv:
    ONLY = sys.argv[sys.argv.index('--only') + 1].split(',')
SPLITS = {k: v for k, v in SPLITS_ALL.items() if ONLY is None or k in ONLY}
TICKERS = list(SPLITS)

BACKUPS = [
    ('gold',   'daily_ohlcv'),
    ('silver', 'unified_prices'),
    ('bronze', 'yf_prices'),
]

def make_backups(cur):
    for sch, tbl in BACKUPS:
        bak = f'{sch}.{tbl}__splitfix_bak_20261015'
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {bak} AS
                        SELECT * FROM {sch}.{tbl} WHERE 1=0""")
        cur.execute(f"""INSERT INTO {bak} SELECT s.* FROM {sch}.{tbl} s
                        WHERE s.ticker = ANY(%s)
                          AND NOT EXISTS (SELECT 1 FROM {bak} b WHERE b.ticker = s.ticker AND b.date = s.date)""", (TICKERS,))
        cur.execute(f"SELECT count(*) FROM {bak} WHERE ticker = ANY(%s)", (TICKERS,))
        print(f'  backup {bak}: {cur.fetchone()[0]} rows (incl. prior runs)')

def fix_gold(cur):
    print('== gold.daily_ohlcv (blanket adjust, verified all-raw)')
    for t, (bd, f) in SPLITS.items():
        cur.execute("""
            UPDATE gold.daily_ohlcv
            SET open=open/%(f)s, high=high/%(f)s, low=low/%(f)s,
                close=close/%(f)s, adjusted_close=adjusted_close/%(f)s,
                volume=ROUND(volume*%(f)s), updated_at=NOW()
            WHERE ticker=%(t)s AND date < %(bd)s""", {'f': f, 't': t, 'bd': bd})
        print(f'  {t}: {cur.rowcount} rows adjusted (factor {f:.6f}, boundary {bd})')

def fix_table_vs_gold(cur, schema, table, vol_bigint):
    """Per-row adjust for silver/bronze using gold (still raw) as reference."""
    ts_col = 'updated_at' if schema != 'bronze' else 'ingested_at'
    print(f'== {schema}.{table} (per-row detection vs gold-raw)')
    for t, (bd, f) in SPLITS.items():
        # classify
        cur.execute(f"""
            SELECT count(*),
                   count(*) FILTER (WHERE abs(s.close/g.close - 1) < 0.02),
                   count(*) FILTER (WHERE abs(s.close*%(f)s/g.close - 1) < 0.02),
                   count(*) FILTER (WHERE abs(s.close/g.close - 1) >= 0.02
                                        AND abs(s.close*%(f)s/g.close - 1) >= 0.02)
            FROM {schema}.{table} s JOIN gold.daily_ohlcv g
              ON g.ticker=s.ticker AND g.date=s.date
            WHERE s.ticker=%(t)s AND s.date < %(bd)s""", {'f': f, 't': t, 'bd': bd})
        tot, raw, adj, anom = cur.fetchone()
        cur.execute(f"SELECT count(*) FROM {schema}.{table} s WHERE s.ticker=%(t)s AND s.date < %(bd)s "
                    f"AND NOT EXISTS (SELECT 1 FROM gold.daily_ohlcv g WHERE g.ticker=s.ticker AND g.date=s.date)",
                    {'t': t, 'bd': bd})
        no_gold = cur.fetchone()[0]
        print(f'  {t}: pre-boundary rows={tot} raw={raw} already-adj={adj} anomaly={anom} no-gold-ref={no_gold}')
        if anom or no_gold:
            cur.execute(f"""
                SELECT s.date, s.close, g.close FROM {schema}.{table} s
                LEFT JOIN gold.daily_ohlcv g ON g.ticker=s.ticker AND g.date=s.date
                WHERE s.ticker=%(t)s AND s.date < %(bd)s
                  AND (g.close IS NULL OR (abs(s.close/g.close - 1) >= 0.02 AND abs(s.close*%(f)s/g.close - 1) >= 0.02))
                ORDER BY s.date LIMIT 10""", {'f': f, 't': t, 'bd': bd})
            for r in cur.fetchall():
                print(f'    ANOMALY {t} {r}')
        if not APPLY:
            continue
        vexpr = 'ROUND(s.volume*%(f)s)' if vol_bigint else 's.volume*%(f)s'
        cur.execute(f"""
            UPDATE {schema}.{table} s
            SET open=s.open/%(f)s, high=s.high/%(f)s, low=s.low/%(f)s,
                close=s.close/%(f)s, adjusted_close=s.adjusted_close/%(f)s,
                volume={vexpr}, {ts_col}=NOW()
            FROM gold.daily_ohlcv g
            WHERE g.ticker=s.ticker AND g.date=s.date
              AND s.ticker=%(t)s AND s.date < %(bd)s
              AND abs(s.close/g.close - 1) < 0.02""", {'f': f, 't': t, 'bd': bd})
        print(f'    -> {cur.rowcount} rows adjusted')

def stamp_bronze_events(cur):
    """Stamp stock_splits on boundary date as event marker (idempotent)."""
    for t, (bd, f) in SPLITS.items():
        cur.execute("UPDATE bronze.yf_prices SET stock_splits=%(f)s WHERE ticker=%(t)s AND date=%(bd)s",
                    {'f': f, 't': t, 'bd': bd})
        print(f'  bronze event stamp {t} {bd}: {cur.rowcount} row')

def recompute_returns(cur):
    print('== recompute returns (full history, 7 tickers)')
    cur.execute("""
        WITH w AS (
          SELECT ticker, date,
                 ROUND((close - LAG(close) OVER (PARTITION BY ticker ORDER BY date))
                       / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0), 6) r
          FROM gold.daily_ohlcv WHERE ticker = ANY(%(ts)s))
        UPDATE gold.daily_ohlcv g SET returns_1d = w.r, updated_at = NOW()
        FROM w WHERE g.ticker=w.ticker AND g.date=w.date
          AND (g.returns_1d IS DISTINCT FROM w.r)""", {'ts': TICKERS})
    print(f'  gold.daily_ohlcv.returns_1d: {cur.rowcount} rows refreshed')
    cur.execute("""
        WITH w AS (
          SELECT ticker, date,
                 ROUND((close - LAG(close) OVER (PARTITION BY ticker ORDER BY date))
                       / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0), 6) r,
                 ROUND(LN(NULLIF(close,0) / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)), 6) rl
          FROM silver.unified_prices WHERE ticker = ANY(%(ts)s))
        UPDATE silver.unified_prices s SET returns_1d = w.r, returns_log = w.rl, updated_at = NOW()
        FROM w WHERE s.ticker=w.ticker AND s.date=w.date
          AND (s.returns_1d IS DISTINCT FROM w.r OR s.returns_log IS DISTINCT FROM w.rl)""", {'ts': TICKERS})
    print(f'  silver.unified_prices.returns: {cur.rowcount} rows refreshed')

def verify(cur):
    print('== post-fix verification')
    for t, (bd, f) in SPLITS.items():
        for sch, tbl in [('gold','daily_ohlcv'), ('silver','unified_prices')]:
            cur.execute(f"""
                WITH w AS (SELECT date, close,
                    LAG(close) OVER (ORDER BY date) pc
                    FROM {sch}.{tbl} WHERE ticker=%(t)s AND close IS NOT NULL)
                SELECT max(abs(close/pc-1)), max(abs(close/pc-1)) FILTER (WHERE date=%(bd)s)
                FROM w WHERE pc>0""", {'t': t, 'bd': bd})
            mx, atbd = cur.fetchone()
            print(f'  {sch}.{tbl} {t}: max|1d ret| full history = {float(mx)*100 if mx else None:.1f}%  |  move on boundary {bd} = {float(atbd)*100 if atbd else None:.2f}%')

def main():
    conn = get_connection()
    cur = conn.cursor()
    print(f'MODE: {"APPLY" if APPLY else "DRY-RUN"}')
    if APPLY:
        make_backups(cur)
    # silver + bronze FIRST (they need gold as the raw reference), then gold
    fix_table_vs_gold(cur, 'silver', 'unified_prices', vol_bigint=False)
    fix_table_vs_gold(cur, 'bronze', 'yf_prices', vol_bigint=True)
    if APPLY:
        stamp_bronze_events(cur)
        fix_gold(cur)
        recompute_returns(cur)
        conn.commit()
        print('COMMITTED')
        verify(cur)
    else:
        conn.rollback()
        print('DRY-RUN complete — no writes. Re-run with --apply to execute.')
    conn.close()

if __name__ == '__main__':
    main()
