#!/usr/bin/env python3
"""
Backfill / reconcile win_rate_oos for 8 active ETF strategies in gold.strategy_registry
and gold.strategy_backtest_runs.

Context: parent task t_0eb8992c. The registry already had win_rate_oos populated, but
this script verifies consistency and reconciles the latest backtest row per affected
strategy to match the registry values. For REIT, the latest run was a partial backfill
with divergent metrics; we align it to the registry/P10-restored values so the
/api/strategies/researcher endpoint returns self-consistent OOS metrics.
"""
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import psycopg2


ETF_IDS = [
    "ETF_Defensive_Equity_Income",
    "ETF_Dividend_Aristocrats_Treasury_Barbell",
    "ETF_Global_Risk_Parity_VolTarget",
    "ETF_HK_Balanced_Trend",
    "ETF_HY_Credit_Carry",
    "ETF_REIT_Dividend_Momentum",
    "ETF_Small_Cap_Momentum",
    "ETF_US_Sector_Relative_Momentum",
]


def get_db_url():
    """Prefer explicit OPENCLAW_* env vars; the env file has a known
    airtrading/aitrading typo, so we always target the real DB name aitrading."""
    host = os.environ.get("OPENCLAW_DB_HOST")
    port = os.environ.get("OPENCLAW_DB_PORT", "5432")
    user = os.environ.get("OPENCLAW_DB_USER")
    password = os.environ.get("OPENCLAW_DB_PASSWORD")
    # Known typo correction: env file says airtrading, real DB is aitrading
    dbname = "aitrading"
    if not (host and user and password):
        # last resort
        url = os.environ.get("OPENCLAW_DATABASE_URL", "")
        if url:
            p = urlparse(url)
            host = p.hostname
            port = p.port or 5432
            user = p.username
            password = p.password
            dbname = "aitrading"  # known typo correction
    if not (host and user and password):
        raise RuntimeError("Missing DB credentials")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


def reconcile():
    url = get_db_url()
    conn = psycopg2.connect(url)
    conn.autocommit = False
    cur = conn.cursor()

    # 1. Verify no active registry row has NULL win_rate_oos
    cur.execute(
        """
        SELECT COUNT(*) FROM gold.strategy_registry
        WHERE status NOT IN ('DEPRECATED','REJECTED','FAILED')
          AND strategy_id = ANY(%s)
          AND win_rate_oos IS NULL
        """,
        (ETF_IDS,),
    )
    null_count = cur.fetchone()[0]
    if null_count:
        raise RuntimeError(f"{null_count} affected ETF registry rows still have NULL win_rate_oos")

    # 2. For each strategy, ensure the latest backtest row (by created_at) matches registry
    mismatches = []
    for sid in ETF_IDS:
        cur.execute(
            """
            SELECT r.win_rate_oos, r.trade_count_oos, r.sharpe_oos, r.max_drawdown_oos
            FROM gold.strategy_registry r
            WHERE r.strategy_id = %s
            """,
            (sid,),
        )
        reg = cur.fetchone()
        if not reg:
            print(f"WARNING: {sid} not in registry", file=sys.stderr)
            continue
        reg_win, reg_tc, reg_sharpe, reg_mdd = reg

        cur.execute(
            """
            SELECT run_id, win_rate_oos, trade_count_oos, sharpe_oos, max_drawdown_oos, created_at
            FROM gold.strategy_backtest_runs
            WHERE strategy_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (sid,),
        )
        bt = cur.fetchone()
        if not bt:
            raise RuntimeError(f"{sid} has no backtest rows")
        run_id, bt_win, bt_tc, bt_sharpe, bt_mdd, created_at = bt

        def same(a, b):
            if a is None and b is None:
                return True
            if a is None or b is None:
                return False
            return abs(float(a) - float(b)) < 1e-4

        if not (same(reg_win, bt_win) and same(reg_tc, bt_tc) and same(reg_sharpe, bt_sharpe) and same(reg_mdd, bt_mdd)):
            mismatches.append((sid, run_id, reg, bt))
            cur.execute(
                """
                UPDATE gold.strategy_backtest_runs
                SET win_rate_oos = %s,
                    trade_count_oos = %s,
                    sharpe_oos = %s,
                    max_drawdown_oos = %s,
                    notes = COALESCE(notes, '') || E'\n[backfill] Aligned latest run to registry OOS metrics.'
                WHERE run_id = %s
                """,
                (reg_win, reg_tc, reg_sharpe, reg_mdd, run_id),
            )
            print(f"RECONCILED {sid} run {run_id} -> registry values win_rate={reg_win} tc={reg_tc} sharpe={reg_sharpe} mdd={reg_mdd}")
        else:
            print(f"OK {sid} run {run_id} matches registry")

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nReconciliation complete: {len(mismatches)} row(s) adjusted.")
    return len(mismatches)


if __name__ == "__main__":
    n = reconcile()
    sys.exit(0 if n >= 0 else 1)
