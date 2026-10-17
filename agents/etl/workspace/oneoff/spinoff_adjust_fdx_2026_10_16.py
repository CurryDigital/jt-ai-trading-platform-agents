#!/usr/bin/env python3
"""
One-off DATA_FIX (user directive 2026-10-16): FDX spin-off price adjustment.

Recommendation implemented: ADJUST (not bar-mask). A spin-off is a real
corporate action with a yfinance adjustment factor (1.241); masking only the
ex-date bar leaves 1w/1m/3m lookbacks spanning 2026-05-26 polluted by the
-18.23% mechanical drop. Parent share count is unchanged, so PRICES are
divided by the factor for dates < boundary and VOLUME IS LEFT UNCHANGED
(unlike a true split).

Snapshots first (FDX-only, all three layers):
  gold.daily_ohlcv__spinoff_bak_20261016
  silver.unified_prices__spinoff_bak_20261016
  bronze.yf_prices__spinoff_bak_20261016

Usage:
  python3 spinoff_adjust_fdx_2026_10_16.py           # dry-run
  python3 spinoff_adjust_fdx_2026_10_16.py --apply   # write
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

APPLY = '--apply' in sys.argv
T, BD, F = 'FDX', '2026-05-26', 1.241
BAKS = [('gold', 'daily_ohlcv', 'updated_at'),
        ('silver', 'unified_prices', 'updated_at'),
        ('bronze', 'yf_prices', 'ingested_at')]


def bak_name(sch, tbl):
    return f'{sch}.{tbl}__spinoff_bak_20261016'


def make_backups(cur):
    for sch, tbl, _ in BAKS:
        bak = bak_name(sch, tbl)
        cur.execute(f"SELECT to_regclass('{bak}')")
        if cur.fetchone()[0]:
            cur.execute(f"SELECT count(*) FROM {bak} WHERE ticker=%s", (T,))
            print(f'  backup {bak}: exists ({cur.fetchone()[0]} FDX rows) — not recreated')
            continue
        cur.execute(f"CREATE TABLE {bak} AS SELECT * FROM {sch}.{tbl} WHERE ticker=%s", (T,))
        cur.execute(f"SELECT count(*) FROM {bak}")
        print(f'  backup {bak}: {cur.fetchone()[0]} rows')


def report(cur):
    for sch, tbl, _ in BAKS:
        cur.execute(f"SELECT count(*), min(date), max(date) FROM {sch}.{tbl} WHERE ticker=%s AND date < %s", (T, BD))
        print(f'  {sch}.{tbl} pre-boundary rows:', cur.fetchone())
    cur.execute("""
        SELECT date, close FROM gold.daily_ohlcv
        WHERE ticker=%s AND date <= %s ORDER BY date DESC LIMIT 2""", (T, BD))
    rows = cur.fetchall()
    print('  gold last pre/boundary rows:', rows)
    if len(rows) == 2:
        boundary_close, pre_close = float(rows[0][1]), float(rows[1][1])
        print(f'  boundary return now: {(boundary_close/pre_close-1)*100:.2f}%  -> after adjust: {(boundary_close/(pre_close/F)-1)*100:.2f}%')


def apply_adjust(cur):
    for sch, tbl, ts_col in BAKS:
        cur.execute(f"""
            UPDATE {sch}.{tbl}
            SET open = open / %(f)s,
                high = high / %(f)s,
                low = low / %(f)s,
                close = close / %(f)s,
                adjusted_close = adjusted_close / %(f)s,
                {ts_col} = NOW()
            WHERE ticker=%(t)s AND date < %(bd)s""", {'f': F, 't': T, 'bd': BD})
        print(f'  {sch}.{tbl}: {cur.rowcount} pre-boundary rows price-adjusted (volume unchanged)')

    # returns recompute from adjusted closes (silver has returns_log too)
    cur.execute("""
        WITH w AS (
          SELECT ticker, date,
            ROUND((close - LAG(close) OVER (PARTITION BY ticker ORDER BY date))
                  / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0), 6) r,
            ROUND(LN(NULLIF(close,0) / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)), 6) rl
          FROM silver.unified_prices WHERE ticker=%(t)s)
        UPDATE silver.unified_prices s SET returns_1d=w.r, returns_log=w.rl, updated_at=NOW()
        FROM w WHERE s.ticker=w.ticker AND s.date=w.date
          AND (s.returns_1d IS DISTINCT FROM w.r OR s.returns_log IS DISTINCT FROM w.rl)""", {'t': T})
    print(f'  silver.unified_prices returns: {cur.rowcount} refreshed')
    cur.execute("""
        WITH w AS (
          SELECT ticker, date,
            ROUND((close - LAG(close) OVER (PARTITION BY ticker ORDER BY date))
                  / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0), 6) r
          FROM gold.daily_ohlcv WHERE ticker=%(t)s)
        UPDATE gold.daily_ohlcv g SET returns_1d=w.r, updated_at=NOW()
        FROM w WHERE g.ticker=w.ticker AND g.date=w.date
          AND (g.returns_1d IS DISTINCT FROM w.r)""", {'t': T})
    print(f'  gold.daily_ohlcv returns_1d: {cur.rowcount} refreshed')

    cur.execute("""
        INSERT INTO gold.price_adjustment_factors
        (ticker, boundary_date, factor, split_type, source, evidence, applied,
         applied_at, applied_by, bak_ref, kanban_task)
        VALUES (%s, %s, %s, 'spinoff', 'yfinance', %s, TRUE, NOW(),
                'spinoff_adjust_fdx_2026_10_16.py (qr_etl session)',
                'gold.daily_ohlcv__spinoff_bak_20261016, silver.unified_prices__spinoff_bak_20261016, bronze.yf_prices__spinoff_bak_20261016',
                't_8866358c')
        ON CONFLICT (ticker, boundary_date) DO UPDATE SET
          split_type='spinoff', applied=TRUE, applied_at=NOW(),
          applied_by=EXCLUDED.applied_by, bak_ref=EXCLUDED.bak_ref,
          evidence=EXCLUDED.evidence""",
        (T, BD, F,
         'FedEx Freight-class spin-off; yf factor 1.241 stamped 2026-06-01; true as-traded ex-date 2026-05-26. '
         'Adjusted 2026-10-16: parent-only price series back-adjusted (prices /1.241, volume unchanged) so '
         'momentum lookbacks no longer read the mechanical -18.23% ex-drop; boundary move becomes +1.47%.'))


def verify(cur):
    cur.execute("""
        WITH w AS (SELECT date, close, LAG(close) OVER (ORDER BY date) pc
                   FROM gold.daily_ohlcv WHERE ticker=%s)
        SELECT date, round(((close/pc-1)*100)::numeric, 2) FROM w
        WHERE date BETWEEN '2026-05-20' AND '2026-06-02' ORDER BY date""", (T,))
    print('  FDX boundary moves post-fix:', cur.fetchall())
    cur.execute("""
        SELECT count(*) FROM gold.daily_ohlcv g
        JOIN gold.daily_ohlcv__spinoff_bak_20261016 b
          ON b.ticker=g.ticker AND b.date=g.date
        WHERE g.ticker=%s AND g.date < %s AND g.volume IS DISTINCT FROM b.volume""", (T, BD))
    print('  volume rows changed (must be 0):', cur.fetchone()[0])


def main():
    conn = get_connection(); cur = conn.cursor()
    print(f'MODE: {"APPLY" if APPLY else "DRY-RUN"}  {T} factor {F} boundary {BD}')
    if APPLY:
        make_backups(cur)
    report(cur)
    if APPLY:
        apply_adjust(cur)
        conn.commit()
        print('COMMITTED')
        verify(cur)
    else:
        conn.rollback()
        print('DRY-RUN complete — no writes.')
    conn.close()


if __name__ == '__main__':
    main()
