#!/usr/bin/env python3
"""
build_watchlist.py — refresh consumption.watchlist (kanban t_03bdbbfa).

Serves GET /api/watchlist -> {tickers: [...]} for the News portfolio layer
(My-book filter, held chips, exposure strip).

Sources:
  - 'positions' : DISTINCT tickers of ACTIVE rows in
                  consumption.portfolio_positions_current (refreshed wholesale:
                  rows no longer held are removed, source='positions' only).
  - 'core'      : curated macro instruments below (upserted, never removed
                  automatically).
  - 'manual'    : rows inserted by hand; this script NEVER touches them.

Run:  python3 consumption/market/build_watchlist.py
Cron: invoked from news_clusters_refresh.sh (2h cadence).
"""

from __future__ import annotations

import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS consumption.watchlist (
    ticker     VARCHAR(16)  NOT NULL PRIMARY KEY,
    source     VARCHAR(16)  NOT NULL,           -- positions | core | manual
    note       TEXT,
    added_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW()
);
"""

TICKER_RE = re.compile(r'^[A-Z0-9][A-Z0-9.=-]{0,11}$')

# Curated macro instruments the desk always watches (all exist in
# gold.daily_ohlcv; validated below before insert).
CORE = [
    'SPY', 'QQQ', 'DIA', 'IWM', 'TLT', 'HYG', 'LQD', 'EEM',
    'GC=F', 'SI=F', 'CL=F', 'NG=F',
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD',
    'EURUSD=X', 'GBPUSD=X', 'JPY=X',
    '2800.HK',
]


def main() -> int:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(DDL)

        # validation universe: anything we actually have prices for
        cur.execute('SELECT DISTINCT ticker FROM gold.daily_ohlcv')
        priced = {r[0] for r in cur.fetchall()}

        cur.execute("""SELECT DISTINCT ticker
                       FROM consumption.portfolio_positions_current
                       WHERE status = 'ACTIVE'""")
        held = sorted(r[0] for r in cur.fetchall()
                      if r[0] and TICKER_RE.match(r[0]))
        core = [t for t in CORE if t in priced]

        # wholesale-refresh 'positions' rows only
        cur.execute("DELETE FROM consumption.watchlist WHERE source = 'positions'")
        cur.executemany(
            """INSERT INTO consumption.watchlist (ticker, source, note)
               VALUES (%s, 'positions', 'active strategy holding')
               ON CONFLICT (ticker) DO UPDATE
                 SET source = 'positions', updated_at = NOW()""",
            [(t,) for t in held])
        cur.executemany(
            """INSERT INTO consumption.watchlist (ticker, source, note)
               VALUES (%s, 'core', 'curated macro instrument')
               ON CONFLICT (ticker) DO UPDATE
                 SET updated_at = NOW()""",
            [(t,) for t in core])
        cur.execute("SELECT source, count(*) FROM consumption.watchlist GROUP BY 1 ORDER BY 1")
        summary = dict(cur.fetchall())
    conn.commit()
    conn.close()
    print(f'✅ watchlist refreshed: {summary} '
          f'(held={len(held)}, core={len(core)})', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
