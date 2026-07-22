"""Estimate profit_factor_oos for approved/backtesting strategies that still lack it.

Order of preference:
  1. Compute from gold.strategy_backtest_trades pnl_pct if available.
  2. Estimate from win_rate_oos, returns_oos, max_drawdown_oos, trade_count_oos using a
     simple return/drawdown heuristic when the strategy is approved or backtesting and
     no trade-level data exists.
  3. Leave NULL if no metrics are available.

Estimated rows are flagged in the notes column so downstream consumers can exclude them.
"""
import os
import math
from decimal import Decimal, InvalidOperation
import psycopg2
from psycopg2.extras import RealDictCursor

DB = dict(
    host=os.environ['PGHOST'],
    dbname=os.environ['PGDATABASE'],
    user=os.environ['PGUSER'],
    password=os.environ['PGPASSWORD'],
)

def pf_from_trades(pnls):
    pnls = [p for p in pnls if p is not None and not p.is_nan()]
    if not pnls:
        return None
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    return round(gross_profit / gross_loss, 6) if gross_loss else Decimal('999')

def estimate_pf(r):
    """Return a heuristic PF from summary metrics, or None if not estimable."""
    w = r['win_rate_oos']
    n = r['trade_count_oos']
    ret = r['returns_oos']
    dd = r['max_drawdown_oos']
    if w is None or n is None or n <= 0:
        return None
    # All wins and no losses: PF is undefined, use sentinel.
    if w == 1 or w == Decimal('1'):
        return Decimal('999')
    if ret is None or dd is None:
        return None
    abs_dd = abs(dd)
    if abs_dd == 0:
        # No observed drawdown; treat as all-win-like.
        return Decimal('999')
    # Heuristic: PF = 1 + (return / max_drawdown magnitude). This is a rough reward/risk proxy.
    return round(Decimal('1') + (ret / abs_dd), 6)

conn = psycopg2.connect(**DB)
conn.autocommit = False
cur = conn.cursor(cursor_factory=RealDictCursor)

print("Fetching approved/backtesting strategies with NULL profit_factor_oos...")
cur.execute("""
    SELECT s.strategy_id
    FROM gold.strategy_research s
    JOIN (
        SELECT DISTINCT ON (strategy_id) strategy_id, profit_factor_oos
        FROM gold.strategy_backtest_runs
        ORDER BY strategy_id, run_number DESC, created_at DESC
    ) b ON b.strategy_id = s.strategy_id
    WHERE s.status IN ('approved','backtesting')
      AND b.profit_factor_oos IS NULL
    ORDER BY s.strategy_id
""")
rows = cur.fetchall()
print(f"  {len(rows)} strategies need PF")

updated = 0
estimated = 0
for row in rows:
    sid = row['strategy_id']
    # Try trade-level PF first
    cur.execute("SELECT pnl_pct FROM gold.strategy_backtest_trades WHERE strategy_id=%s", (sid,))
    pnls = [r['pnl_pct'] for r in cur.fetchall()]
    pf = pf_from_trades(pnls)
    source = 'trades'
    if pf is None:
        # Fetch summary metrics from the latest run
        cur.execute("""
            SELECT win_rate_oos, trade_count_oos, returns_oos, max_drawdown_oos
            FROM gold.strategy_backtest_runs
            WHERE strategy_id=%s
            ORDER BY run_number DESC, created_at DESC
            LIMIT 1
        """, (sid,))
        mr = cur.fetchone()
        pf = estimate_pf(mr) if mr else None
        source = 'estimated_return_drawdown'
    if pf is None:
        print(f"  {sid}: no PF source")
        continue
    note = f"profit_factor_oos backfilled from {source} on {os.environ.get('NOW', 'run')}"
    cur.execute("""
        UPDATE gold.strategy_backtest_runs
        SET profit_factor_oos = %s,
            notes = COALESCE(notes, '') || E'\n' || %s
        WHERE strategy_id = %s
          AND profit_factor_oos IS NULL
    """, (pf, note, sid))
    updated += cur.rowcount
    estimated += (1 if source == 'estimated_return_drawdown' else 0)
    print(f"  {sid}: set PF={pf} from {source}")

conn.commit()
print(f"\nCommitted: {updated} rows updated ({estimated} estimated from metrics)")
conn.close()
