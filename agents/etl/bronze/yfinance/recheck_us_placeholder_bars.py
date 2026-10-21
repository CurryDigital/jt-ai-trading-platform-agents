#!/usr/bin/env python3
"""
Bronze: US post-close D+1 suspect/straggler recheck (kanban t_d97f3b82)
=======================================================================
Runs inside yf_us_postclose_topup.sh right after the normal bronze ingest.

Two populations are re-pulled for the recent window:
  1. SUSPECT — tickers with unresolved quarantined placeholder bars in
     bronze.yf_suspect_bars over the last 10 days (Yahoo synthetic
     zero-volume flat bars around corporate actions, e.g. AVB/EQR 2026-08).
  2. STRAGGLER — active US STOCK/ETF tickers whose latest bronze.yf_prices
     date trails the universe max date (missed the session entirely).

Every re-pulled row passes through the same guards in
ingest_yfinance_prices._upsert_prices: a still-suspect row is withheld again
(quarantine refreshed) and a corporate-action rewrite stays blocked.

Exit semantics: always 0 unless the recheck itself blew up — suspects that
remain suspects emit WARNING lines only; the top-up cron must stay green
when only suspects are withheld.
"""
import os
import sys
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
sys.path.insert(0, SCRIPT_DIR)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection

try:
    import yfinance as yf
except ImportError:
    print("WARNING: yfinance not installed — suspect recheck skipped")
    sys.exit(0)

import ingest_yfinance_prices as ing

RECHECK_WINDOW_DAYS = 10


def _recheck_universe(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT s.ticker FROM bronze.yf_suspect_bars s
        JOIN gold.asset_registry ar ON ar.ticker = s.ticker
        WHERE s.resolved_at IS NULL AND s.date >= CURRENT_DATE - %s
          AND ar.is_active = TRUE
    """, (RECHECK_WINDOW_DAYS,))
    suspects = {r[0] for r in cur.fetchall()}

    cur.execute("""
        WITH us AS (
            SELECT ticker FROM gold.asset_registry
            WHERE market = 'US' AND asset_class IN ('STOCK', 'ETF')
              AND is_active = TRUE
        ),
        last_dates AS (
            SELECT p.ticker, max(p.date) AS last_date
            FROM bronze.yf_prices p JOIN us USING (ticker)
            WHERE p.date >= CURRENT_DATE - %s
            GROUP BY p.ticker
        ),
        universe_max AS (
            SELECT max(last_date) AS d FROM last_dates
        )
        SELECT l.ticker FROM last_dates l, universe_max m
        WHERE m.d IS NOT NULL AND l.last_date < m.d
    """, (RECHECK_WINDOW_DAYS,))
    stragglers = {r[0] for r in cur.fetchall()}
    return suspects, stragglers


def main():
    conn = get_connection()
    try:
        suspects, stragglers = _recheck_universe(conn)
    finally:
        conn.close()

    only_stragglers = stragglers - suspects
    if suspects:
        print(f"  Recheck: {len(suspects)} suspect ticker(s): {','.join(sorted(suspects))}")
    if only_stragglers:
        print(f"  Recheck: {len(only_stragglers)} straggler ticker(s) behind universe max date: "
              f"{','.join(sorted(only_stragglers))}")
    tickers = sorted(suspects | stragglers)
    if not tickers:
        print("  Recheck: no suspects or stragglers — nothing to do")
        return 0

    conn = get_connection()
    cur = conn.cursor()
    start = (date.today() - timedelta(days=RECHECK_WINDOW_DAYS + 5)).isoformat()
    still_suspect = set()
    healed = set()
    for ticker in tickers:
        try:
            data = yf.download(ticker, start=start, auto_adjust=True, progress=False)
            if isinstance(data.columns, __import__('pandas').MultiIndex):
                data.columns = data.columns.get_level_values(0)
            df = data.reset_index()
            n = ing._upsert_prices(cur, ticker, df)
            conn.commit()
            if ticker in suspects:
                if any(t == ticker for t, _ in ing._suspect_keys):
                    still_suspect.add(ticker)
                else:
                    healed.add(ticker)
            print(f"  Recheck {ticker}: {n} row(s) upserted")
        except Exception as e:
            conn.rollback()
            print(f"  WARNING: recheck failed for {ticker}: {e}")
    conn.close()

    for ticker in sorted(healed):
        print(f"  Recheck {ticker}: HEALED — real bars landed, quarantine resolved")
    for ticker in sorted(still_suspect):
        # left absent/quarantined — warning only, no failure
        print(f"  WARNING: STILL SUSPECT {ticker} — Yahoo still serving "
              f"zero-volume flat placeholders; rows remain quarantined/absent "
              f"(see gold.v_us_equity_bar_quality)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
