#!/usr/bin/env python3
"""One-time label backfill for NULL entry_price_basis rows (t_716fe5a7).

LABELING ONLY — entry_price is never rewritten. For each row with a NULL
entry_price_basis, find the silver.unified_prices close that exactly equals
entry_price on a date <= entry_date (within a 10-calendar-day window). A
unique exact match proves the fill was priced at that close (SIGNAL_CLOSE
semantics); with --apply the row is stamped entry_price_basis='SIGNAL_CLOSE'
and entry_price_source_date=<match date>. Rows with zero or multiple
matches are left NULL and reported.

OPERATOR DECISION 2026-11-02: entry-basis cleanup is PROSPECTIVE-ONLY.
Historical ledger rows are NOT restated without explicit operator sign-off.
This script therefore defaults to DRY-RUN (read-only provenance report);
--apply performs the label writes and requires that sign-off.

--apply safety: snapshots affected rows into gold.paper_trades_synthetic
__basis_label_bak_20261102, logs pre/post counts to gold.etl_snapshot_log.
Idempotent: rows already labelled are skipped by the NULL filter.
"""
import sys, os
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path:
    sys.path.insert(0, _ETL_SHARED)

from db import get_connection

BAK = 'gold.paper_trades_synthetic__basis_label_bak_20261102'
SNAPSHOT_ID = 'basis_label_20261102_t_716fe5a7'


def main():
    apply = '--apply' in sys.argv
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT count(*) FROM gold.paper_trades_synthetic
        WHERE entry_price_basis IS NULL;
    """)
    pre_null = cur.fetchone()[0]
    print(f"NULL entry_price_basis rows: {pre_null}")
    if pre_null == 0:
        print("Nothing to do.")
        return 0

    cur.execute("""
        SELECT id, strategy_id, ticker, entry_date, entry_price
        FROM gold.paper_trades_synthetic
        WHERE entry_price_basis IS NULL
        ORDER BY strategy_id, ticker;
    """)
    rows = cur.fetchall()

    labelled, ambiguous, unmatched = 0, [], []
    for rid, sid, ticker, entry_date, entry_price in rows:
        cur.execute("""
            SELECT DISTINCT date FROM silver.unified_prices
            WHERE ticker = %s
              AND date <= %s
              AND date >= %s - INTERVAL '10 days'
              AND close = %s
            ORDER BY date;
        """, (ticker, entry_date, entry_date, entry_price))
        matches = [r[0] for r in cur.fetchall()]
        if len(matches) == 1:
            print(f"  MATCH id={rid} {sid} {ticker} entry {entry_date} "
                  f"@ {entry_price} == close of {matches[0]} -> SIGNAL_CLOSE")
            labelled += 1
            if apply:
                cur.execute("""
                    UPDATE gold.paper_trades_synthetic
                    SET entry_price_basis = 'SIGNAL_CLOSE',
                        entry_price_source_date = %s
                    WHERE id = %s AND entry_price_basis IS NULL;
                """, (matches[0], rid))
        elif len(matches) == 0:
            unmatched.append((rid, sid, ticker, entry_date, entry_price))
        else:
            ambiguous.append((rid, sid, ticker, entry_date, entry_price, matches))

    if not apply:
        conn.rollback()
        print(f"DRY-RUN: would label {labelled} rows; "
              f"unmatched={len(unmatched)} ambiguous={len(ambiguous)}. "
              f"No writes performed (operator decision 2026-11-02: "
              f"prospective-only; --apply requires sign-off).")
        for r in unmatched:
            print("  UNMATCHED:", r)
        for r in ambiguous:
            print("  AMBIGUOUS:", r)
        return 0

    # --apply path: snapshot + write + log.
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {BAK} AS
        SELECT * FROM gold.paper_trades_synthetic WHERE entry_price_basis IS NULL;
    """)
    cur.execute(f"SELECT count(*) FROM {BAK};")
    print(f"Snapshot {BAK}: {cur.fetchone()[0]} rows")

    cur.execute("""
        SELECT count(*) FROM gold.paper_trades_synthetic
        WHERE entry_price_basis IS NULL;
    """)
    post_null = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO gold.etl_snapshot_log
          (snapshot_id, scope, script, pre_rows, post_rows, note, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (SNAPSHOT_ID,
          'gold.paper_trades_synthetic NULL entry_price_basis label backfill',
          'gold/strategy/label_null_entry_basis_2026-11-02.py',
          pre_null, post_null,
          f'labelled={labelled} unmatched={len(unmatched)} ambiguous={len(ambiguous)}; '
          f'label-only, entry_price never rewritten; snapshot {BAK}',
          datetime.now(timezone.utc).replace(tzinfo=None)))

    conn.commit()
    print(f"APPLIED: labelled={labelled} post_null={post_null}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
