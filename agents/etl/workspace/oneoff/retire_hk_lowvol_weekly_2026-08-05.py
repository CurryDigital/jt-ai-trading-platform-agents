#!/usr/bin/env python3
"""
retire_hk_lowvol_weekly_2026-08-05.py
=====================================
One-off retirement of HK_LowVol_Weekly per book-level honest review
2026-08-05 (kanban t_d223563a):

  0.97 OOS correlation with HK_LowVol_TrendFilter_Weekly -> redundant
  duplicate. Consolidated; TrendFilter variant stays live.

Actions (all idempotent):
  1. Close all open gold.paper_trades_synthetic positions at the latest
     silver.unified_prices close (standard retirement flatten).
  2. gold.strategy_registry: status='retired', retired_at, retirement_reason,
     in_market_capital=0.
  3. gold.strategy_paper_monitoring: is_active=false, deactivated_at.
     (build_rotation_signals.py gates on status='paper' and
     rebuild_paper_positions.py gates on retired_at IS NULL, so signal
     generation and the paper engine stop automatically.)

Run with ETL venv:  /home/ubuntu/.hermes/etl-venv/bin/python3 <this file>
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)

from db import get_connection  # noqa: E402

SID = 'HK_LowVol_Weekly'
REASON = ('Duplicate of HK_LowVol_TrendFilter_Weekly (0.97 OOS corr); '
          'consolidated per book review 2026-08-05')


def main():
    today = date.today()
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # ── 0. pre-state ────────────────────────────────────────────────────
    cur.execute("""
        SELECT id, ticker, entry_date, entry_price, n_shares
        FROM gold.paper_trades_synthetic
        WHERE strategy_id = %s AND status = 'open'
        ORDER BY ticker
    """, (SID,))
    open_rows = cur.fetchall()
    print(f"[pre] open positions for {SID}: {len(open_rows)}")
    for r in open_rows:
        print(f"      id={r[0]} {r[1]} entry={r[2]} px={r[3]} sh={r[4]}")

    # ── 1. flatten open positions at latest close ───────────────────────
    tickers = [r[1] for r in open_rows]
    closed = 0
    if tickers:
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, close
            FROM silver.unified_prices
            WHERE ticker = ANY(%s)
            ORDER BY ticker, date DESC
        """, (tickers,))
        px = dict(cur.fetchall())
        missing = [t for t in tickers if t not in px]
        if missing:
            raise RuntimeError(f"no price for {missing} — refusing to flatten blind")
        for rid, ticker, entry_date, entry_price, n_shares in open_rows:
            exit_price = float(px[ticker])
            cur.execute("""
                UPDATE gold.paper_trades_synthetic
                SET status = 'closed',
                    exit_date = %s,
                    exit_price = %s,
                    pnl = (%s - entry_price) * n_shares,
                    pnl_pct = CASE WHEN entry_price = 0 OR entry_price IS NULL THEN 0
                                   ELSE ((%s - entry_price) / entry_price) * 100 END,
                    updated_at = NOW()
                WHERE id = %s AND status = 'open'
            """, (today, exit_price, exit_price, exit_price, rid))
            closed += cur.rowcount
            print(f"      closed id={rid} {ticker} exit={today} px={exit_price}")
    print(f"[1] positions closed: {closed}")

    # ── 2. registry retirement ──────────────────────────────────────────
    cur.execute("""
        UPDATE gold.strategy_registry
        SET status = 'retired',
            retired_at = NOW(),
            retirement_reason = %s,
            in_market_capital = 0,
            updated_at = NOW()
        WHERE strategy_id = %s
    """, (REASON, SID))
    print(f"[2] strategy_registry rows updated: {cur.rowcount}")

    # ── 3. deactivate paper monitoring ──────────────────────────────────
    cur.execute("""
        UPDATE gold.strategy_paper_monitoring
        SET is_active = false,
            deactivated_at = NOW(),
            updated_at = NOW()
        WHERE strategy_id = %s AND is_active = true
    """, (SID,))
    print(f"[3] strategy_paper_monitoring deactivated: {cur.rowcount}")

    conn.commit()

    # ── verify ──────────────────────────────────────────────────────────
    cur.execute("""
        SELECT status, retired_at IS NOT NULL AS retired_at_set, retirement_reason
        FROM gold.strategy_registry WHERE strategy_id = %s
    """, (SID,))
    print(f"[verify] registry: {cur.fetchone()}")
    cur.execute("""
        SELECT count(*) FROM gold.paper_trades_synthetic
        WHERE strategy_id = %s AND status = 'open'
    """, (SID,))
    print(f"[verify] open positions remaining: {cur.fetchone()[0]}")
    cur.execute("""
        SELECT is_active FROM gold.strategy_paper_monitoring WHERE strategy_id = %s
    """, (SID,))
    print(f"[verify] monitoring is_active: {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    print("RETIREMENT COMPLETE")


if __name__ == '__main__':
    main()
