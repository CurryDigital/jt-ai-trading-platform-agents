#!/usr/bin/env python3
"""One-off board backfill for silver.unified_ipo_calendar (kanban t_33748a1d).

Root cause: the AAStocks calendar ingest (refresh_ipo_calendar_daily.py)
never writes board, so every listing first seen after the NLR backfill era
(>= 2025-07-04) carried board=NULL, silently excluding Main-board events
from the C1 audited engine and forcing the paper feeder onto a ticker-prefix
fallback.

Every NULL-board row was verified Main board against HKEX sources BEFORE
this update (2026-10-26):
  - 12 via silver.hk_ipo_filings.listed_stock_code (HKEXnews applisted feed)
  - 3 via live HKEXnews applisted_sehk_e.json (02076 KANZHUN, 00625 SHEIN,
    09615 MECH-MIND)
  - 3 via HKEXnews A1/PHIP filings rows with board='MAIN' (06157 SWL Tour =
    Jiangsu Slender West Lake, 03275 Microintelligence, 02384 DSBJ = Suzhou
    Dongshan Precision) + HKEX code-range convention (non-8xxx = Main)

Runs the same fill_calendar_board()/board_qa_gate() now embedded in
refresh_ipo_filings_daily.py, then prints before/after verification.
Idempotent (fill-NULL only).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'shared', 'scripts'))

from db import get_connection  # noqa: E402
from refresh_ipo_filings_daily import (  # noqa: E402
    fill_calendar_board, board_qa_gate)

EVIDENCE_SQL = """
SELECT count(*) FROM silver.unified_ipo_calendar
WHERE board IS NULL AND listing_date >= '2025-07-04'
"""

DETAIL_SQL = """
SELECT ticker, stock_name, listing_date, board, data_source
FROM silver.unified_ipo_calendar
WHERE listing_date >= '2025-07-04'
ORDER BY listing_date
"""


def main():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(EVIDENCE_SQL)
    before = cur.fetchone()[0]
    print(f"evidence query BEFORE: {before} NULL-board rows since 2025-07-04")

    n_filings, n_range = fill_calendar_board(cur)
    print(f"fill: {n_filings} from filings (authoritative), "
          f"{n_range} from code range (fallback)")

    gate_failures = board_qa_gate(cur)
    cur.execute(EVIDENCE_SQL)
    after = cur.fetchone()[0]

    if gate_failures or after != 0:
        conn.rollback()
        print(f"FATAL: gate would fail ({len(gate_failures)} listed NULL "
              f"rows); evidence after={after}. ROLLED BACK.")
        for t, d in gate_failures:
            print(f"  NULL board: {t} listed {d}")
        sys.exit(1)

    conn.commit()
    print(f"evidence query AFTER: {after} NULL-board rows since 2025-07-04")
    print("\npost-backfill rows since 2025-07-04:")
    cur.execute(DETAIL_SQL)
    for r in cur.fetchall():
        print("  " + " | ".join(str(x) for x in r))

    cur.execute("""SELECT board, count(*) FROM silver.unified_ipo_calendar
                   GROUP BY board ORDER BY 2 DESC""")
    print("\nboard distribution (all rows):")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
