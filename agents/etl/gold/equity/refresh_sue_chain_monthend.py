#!/usr/bin/env python3
"""Month-end SUE chain refresh (kanban t_4df7ec1d, 2026-11-02).

Problem: the bronze leg of the SUE chain (ingest_yfinance_aux.py earnings
scrape) runs WEEKLY (Sun 03:00 UTC), so eps_actual for earnings reported
Mon-Thu lands up to ~4 days late. The 2026-10-30 month-end signal for
us_stk_sue_mom_01_v2 consumed gold.sue_scores with max(calculated_at) =
2026-10-26 — earnings reported 10-27..10-30 were missing from the picks.

This driver runs the FULL chain on month-end days so gold.sue_scores is fresh
before the 23:55 UTC ingested-signal run (cron 5aff9601ff55, days 28-31) and
before any next-morning one-shot retry:

  1. bronze:  ingest_yfinance_aux.ingest_earnings_calendar(scoped tickers)
  2. silver:  silver/clean_unified_earnings.py   (subprocess, cwd=agents/etl)
  3. gold:    gold/equity/build_earnings_signals.py (subprocess; sets
              ETL_RUN_SNAPSHOT_ID=sue-monthend-YYYYMMDD for snapshot_guard)
  4. verify:  report gold.sue_scores vintage; exit non-zero if any step failed

Scrape scope: union of universe_tickers for strategies whose
gold.strategy_configs row config_key='requires_sue_scores' is truthy
(fallback: all active signal_mechanism='ingested' strategies).

Cadence (Hermes cron, profile qr_etl, no_agent):
  qr_etl.sue_monthend_refresh     30 21 27-31 * *   (before the 23:55 signal)
  qr_etl.sue_monthend_refresh_am   0  5 28-31,1 * * (before next-morning retry)
Idempotent upserts; harmless on non-month-end days.

Run under the ETL venv (needs yfinance + lxml for the earnings scrape):
  /home/ubuntu/.hermes/etl-venv/bin/python3 gold/equity/refresh_sue_chain_monthend.py
"""
import os
import subprocess
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ETL_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, os.path.join(ETL_ROOT, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402


def target_tickers() -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT t
            FROM gold.strategy_registry r
            JOIN gold.strategy_configs c
              ON c.strategy_id = r.strategy_id AND c.config_key = 'requires_sue_scores'
            CROSS JOIN LATERAL unnest(r.universe_tickers) AS t
            WHERE (c.config_value = 'true'::jsonb
                   OR (jsonb_typeof(c.config_value) = 'object'
                       AND (c.config_value->>'enabled')::boolean))
              AND r.status NOT IN ('retired', 'paused')
        """)
        tickers = [r[0] for r in cur.fetchall()]
        if not tickers:
            print("  (no requires_sue_scores config rows — falling back to all "
                  "active signal_mechanism='ingested' universes)")
            cur.execute("""
                SELECT DISTINCT t
                FROM gold.strategy_registry r
                CROSS JOIN LATERAL unnest(r.universe_tickers) AS t
                WHERE r.signal_mechanism = 'ingested'
                  AND r.status NOT IN ('retired', 'paused')
            """)
            tickers = [r[0] for r in cur.fetchall()]
        return sorted(set(tickers))
    finally:
        conn.close()


def run_step(name, argv, env):
    print(f"── {name}: {' '.join(argv)}")
    rc = subprocess.run(argv, cwd=ETL_ROOT, env=env).returncode
    if rc != 0:
        print(f"❌ {name} FAILED (exit {rc})")
    return rc


def main() -> int:
    tickers = target_tickers()
    if not tickers:
        print("❌ no target tickers resolved — refusing to run an unscoped scrape")
        return 1
    print(f"SUE month-end refresh: {len(tickers)} tickers in scope "
          f"(requires_sue_scores universes)")

    env = os.environ.copy()
    env.setdefault("ETL_RUN_SNAPSHOT_ID", f"sue-monthend-{date.today().isoformat()}")
    print(f"ETL_RUN_SNAPSHOT_ID={env['ETL_RUN_SNAPSHOT_ID']}")

    failures = []

    # 1. bronze earnings scrape (in-process: the module sets its own paths)
    try:
        sys.path.insert(0, os.path.join(ETL_ROOT, "bronze", "yfinance"))
        import ingest_yfinance_aux
        ingest_yfinance_aux.ingest_earnings_calendar(tickers)
    except Exception as e:
        print(f"❌ bronze earnings scrape FAILED: {e}")
        failures.append("bronze_earnings_scrape")

    # 2. silver merge + SUE compute
    if run_step("silver clean_unified_earnings",
                [sys.executable, "silver/clean_unified_earnings.py"], env) != 0:
        failures.append("silver_clean_unified_earnings")

    # 3. gold build (snapshot-guarded)
    if run_step("gold build_earnings_signals",
                [sys.executable, "gold/equity/build_earnings_signals.py"], env) != 0:
        failures.append("gold_build_earnings_signals")

    # 4. verify + report
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*), max(calculated_at), max(report_date) "
                    "FROM gold.sue_scores")
        n, max_calc, max_rep = cur.fetchone()
        print(f"gold.sue_scores: {n} rows, max(calculated_at)={max_calc}, "
              f"max(report_date)={max_rep}")
    finally:
        conn.close()

    if failures:
        print(f"❌ SUE month-end refresh FAILED: {failures}")
        return 1
    print("✅ SUE month-end refresh complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
