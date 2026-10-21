#!/usr/bin/env python3
"""
One-off DATA_FIX (kanban t_8866358c follow-up, user-approved 2026-10-16):
688012.SS true split (factor 1.49, price boundary 2026-05-19; yf action stamped
2026-05-29 — the known yf-late-stamp pattern) + FDX returns_1d seam repair.

Evidence (verified 2026-10-15/16):
  688012.SS: DB discontinuity -26.7% on 2026-05-19 (438.75 -> 321.45);
  DB/yf raw ratio = 1.4900 pre-05-19 and 0.9988 post-05-19; yf split event 1.49.
  => true split (bonus issue); DB raw series unadjusted pre-boundary.
  FDX: spin-off (FedEx Freight class), true ex 2026-05-26 with as-traded
  -18.23% drop ALREADY in DB (394.20 -> 322.32); yf factor 1.241 stamped
  2026-06-01; DB continuous across 06-01. NOT a split -> NO price adjustment.
  Only defect: stored returns_1d on 2026-04-01 = +52.36% (phantom predecessor
  ~236.04; true cross-gap move vs 2026-02-25 close 386.56 = -7.05%). Repair =
  recompute returns from closes; prices untouched.

Rule: adjust prices only for true splits. Returns recompute is not a price
adjustment.

Backups before any write (rows for both tickers, all three layers):
  gold.daily_ohlcv__splitfix_bak_20261016
  silver.unified_prices__splitfix_bak_20261016
  bronze.yf_prices__splitfix_bak_20261016

Usage:
  python3 split_fix_688012_fdx_2026_10_16.py            # dry-run report
  python3 split_fix_688012_fdx_2026_10_16.py --apply    # write
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

APPLY = '--apply' in sys.argv
T, BD, F = '688012.SS', '2026-05-19', 1.49
FIX_TICKERS = [T, 'FDX']

def make_backups(cur):
    for sch, tbl in [('gold', 'daily_ohlcv'), ('silver', 'unified_prices'),
                     ('bronze', 'yf_prices')]:
        bak = f'{sch}.{tbl}__splitfix_bak_20261016'
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {bak} AS
                        SELECT * FROM {sch}.{tbl} WHERE ticker = ANY(%s)""",
                    (FIX_TICKERS,))
        cur.execute(f"SELECT count(*) FROM {bak}")
        print(f'  backup {bak}: {cur.fetchone()[0]} rows')

def fix_layer(cur, sch, tbl, gold_raw_ref):
    """Per-row adjust vs gold reference (same pattern as the 10-ticker fix)."""
    ts_col = 'updated_at' if sch != 'bronze' else 'ingested_at'
    vol_expr = 'ROUND(s.volume*%(f)s)' if tbl == 'yf_prices' else 's.volume*%(f)s'
    ref = 'gold.daily_ohlcv' if gold_raw_ref else 'gold.daily_ohlcv'
    cur.execute(f"""
        SELECT count(*),
               count(*) FILTER (WHERE abs(s.close/g.close - 1) < 0.02),
               count(*) FILTER (WHERE abs(s.close*%(f)s/g.close - 1) < 0.02),
               count(*) FILTER (WHERE abs(s.close/g.close - 1) >= 0.02
                                    AND abs(s.close*%(f)s/g.close - 1) >= 0.02)
        FROM {sch}.{tbl} s JOIN {ref} g ON g.ticker=s.ticker AND g.date=s.date
        WHERE s.ticker=%(t)s AND s.date < %(bd)s""", {'f': F, 't': T, 'bd': BD})
    tot, raw, adj, anom = cur.fetchone()
    print(f'  {sch}.{tbl} {T}: pre-boundary={tot} raw={raw} already-adj={adj} anomaly={anom}')
    if not APPLY:
        return
    cur.execute(f"""
        UPDATE {sch}.{tbl} s
        SET open=s.open/%(f)s, high=s.high/%(f)s, low=s.low/%(f)s,
            close=s.close/%(f)s, adjusted_close=s.adjusted_close/%(f)s,
            volume={vol_expr}, {ts_col}=NOW()
        FROM {ref} g
        WHERE g.ticker=s.ticker AND g.date=s.date
          AND s.ticker=%(t)s AND s.date < %(bd)s
          AND abs(s.close/g.close - 1) < 0.02""", {'f': F, 't': T, 'bd': BD})
    print(f'    -> {cur.rowcount} rows adjusted')

def recompute_returns(cur):
    for sch, tbl, extra in [('gold', 'daily_ohlcv', False),
                            ('silver', 'unified_prices', True)]:
        if extra:
            cur.execute("""
                WITH w AS (
                  SELECT ticker, date,
                    ROUND((close - LAG(close) OVER (PARTITION BY ticker ORDER BY date))
                          / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0), 6) r,
                    ROUND(LN(NULLIF(close,0) / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0)), 6) rl
                  FROM silver.unified_prices WHERE ticker = ANY(%(ts)s))
                UPDATE silver.unified_prices s SET returns_1d=w.r, returns_log=w.rl, updated_at=NOW()
                FROM w WHERE s.ticker=w.ticker AND s.date=w.date
                  AND (s.returns_1d IS DISTINCT FROM w.r OR s.returns_log IS DISTINCT FROM w.rl)""",
                {'ts': FIX_TICKERS})
            print(f'  silver.unified_prices returns: {cur.rowcount} refreshed')
        else:
            cur.execute("""
                WITH w AS (
                  SELECT ticker, date,
                    ROUND((close - LAG(close) OVER (PARTITION BY ticker ORDER BY date))
                          / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY date), 0), 6) r
                  FROM gold.daily_ohlcv WHERE ticker = ANY(%(ts)s))
                UPDATE gold.daily_ohlcv g SET returns_1d=w.r, updated_at=NOW()
                FROM w WHERE g.ticker=w.ticker AND g.date=w.date
                  AND (g.returns_1d IS DISTINCT FROM w.r)""",
                {'ts': FIX_TICKERS})
            print(f'  gold.daily_ohlcv returns_1d: {cur.rowcount} refreshed')

def verify(cur):
    cur.execute("""WITH w AS (SELECT date, close, LAG(close) OVER (ORDER BY date) pc
                              FROM gold.daily_ohlcv WHERE ticker=%s)
                   SELECT date, round(((close/pc-1)*100)::numeric, 2) FROM w
                   WHERE date BETWEEN '2026-05-15' AND '2026-05-21' ORDER BY date""", (T,))
    print('  688012.SS boundary moves post-fix:', cur.fetchall())
    cur.execute("""SELECT returns_1d FROM gold.daily_ohlcv WHERE ticker='FDX' AND date='2026-04-01'""")
    print('  FDX 2026-04-01 returns_1d post-fix:', cur.fetchone())
    cur.execute("""SELECT max(abs(returns_1d)) FROM gold.daily_ohlcv
                   WHERE ticker=%s AND date <> ALL(ARRAY['2026-05-19']::date[])""", (T,))
    print('  688012.SS max |returns_1d| ex-boundary:', cur.fetchone())

def main():
    conn = get_connection(); cur = conn.cursor()
    print(f'MODE: {"APPLY" if APPLY else "DRY-RUN"}')
    if APPLY:
        make_backups(cur)
    # silver + bronze first (gold raw is the reference), then gold
    fix_layer(cur, 'silver', 'unified_prices', gold_raw_ref=True)
    fix_layer(cur, 'bronze', 'yf_prices', gold_raw_ref=True)
    if APPLY:
        cur.execute("UPDATE bronze.yf_prices SET stock_splits=%s WHERE ticker=%s AND date=%s",
                    (F, T, BD))
        print(f'  bronze event stamp {T} {BD}: {cur.rowcount} row')
        cur.execute("""UPDATE gold.daily_ohlcv
                       SET open=open/%(f)s, high=high/%(f)s, low=low/%(f)s,
                           close=close/%(f)s, adjusted_close=adjusted_close/%(f)s,
                           volume=ROUND(volume*%(f)s), updated_at=NOW()
                       WHERE ticker=%(t)s AND date < %(bd)s""", {'f': F, 't': T, 'bd': BD})
        print(f'  gold.daily_ohlcv {T}: {cur.rowcount} rows adjusted')
        recompute_returns(cur)
        # factor registry
        cur.execute("""
            INSERT INTO gold.price_adjustment_factors
            (ticker, boundary_date, factor, split_type, source, evidence, applied,
             applied_at, applied_by, bak_ref, kanban_task)
            VALUES (%s, %s, %s, 'split', 'yfinance', %s, TRUE, NOW(),
                    'split_fix_688012_fdx_2026_10_16.py (qr_etl session)',
                    'gold.daily_ohlcv__splitfix_bak_20261016, silver.unified_prices__splitfix_bak_20261016, bronze.yf_prices__splitfix_bak_20261016',
                    't_8866358c')
            ON CONFLICT (ticker, boundary_date) DO UPDATE SET
              applied=TRUE, applied_at=NOW(), applied_by=EXCLUDED.applied_by,
              evidence=EXCLUDED.evidence""",
            (T, BD, F,
             'yf split event 1.49 stamped 2026-05-29; true price boundary 2026-05-19 '
             '(DB -26.7% raw discontinuity; DB/yf ratio 1.4900 pre / 0.9988 post)'))
        cur.execute("""
            INSERT INTO gold.price_adjustment_factors
            (ticker, boundary_date, factor, split_type, source, evidence, applied,
             applied_at, applied_by, bak_ref, kanban_task)
            VALUES ('FDX', '2026-05-26', 1.241, 'spinoff', 'yfinance', %s, FALSE, NULL,
                    'qr_etl session 2026-10-16', NULL, 't_8866358c')
            ON CONFLICT (ticker, boundary_date) DO UPDATE SET
              split_type='spinoff', applied=FALSE, evidence=EXCLUDED.evidence""",
            ('FedEx Freight-class spin-off; as-traded ex-drop -18.23% on 2026-05-26 '
             'already in DB (continuous as-traded series); yf factor 1.241 stamped '
             '2026-06-01; user rule: adjust only true splits -> NOT adjusted. '
             'returns_1d seam artifact on 2026-04-01 repaired via recompute.',))
        conn.commit()
        print('COMMITTED')
        verify(cur)
    else:
        conn.rollback()
        print('DRY-RUN complete — no writes.')
    conn.close()

if __name__ == '__main__':
    main()
