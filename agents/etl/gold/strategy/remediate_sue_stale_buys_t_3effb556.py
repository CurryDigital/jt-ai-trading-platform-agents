#!/usr/bin/env python3
"""ONE-OFF remediation (t_3effb556): SUE November book, before the
2026-11-03 settlement cycle.

Context: ingest_paper_signal.py's per-ticker upsert never retired dropped
names, so gold.strategy_ticker_scores carried 56 BUY rows for
us_stk_sue_mom_01_v2 = union of 4 file vintages. The rotation screen ranked
that contaminated union and booked a wrong November rotation (24 pending
orders, signal_date 2026-10-30, settling at the 2026-11-02 bar open in the
2026-11-03 cycle).

This script (DRY-RUN default; --apply to commit):
  1. Snapshots the affected rows:
       gold.strategy_ticker_scores__sue_retire_bak_20261102  (36 BUY rows)
       gold.paper_pending_orders__sue_cancel_bak_20261102    (7 orders)
  2. Retires the 36 stale BUY rows (vintages 2026-10-17/-28/-29) to SELL —
     score=0, entry_score=0, exit_score=prior score, computed_at restamped
     to the canonical file's generated_at — same semantics as the permanent
     replace-per-cycle fix in ingest_paper_signal.py. The 2026-10-30
     vintage's 20 rows (the canonical November set) are NOT touched.
  3. Cancels the 7 wrong pending orders:
       OPEN  CB COST PM RF   (not in the November file)
       CLOSE NTAP PSX VLO    (IN the file — these legs must stay held)
  4. Hard-asserts every expected count/set before committing; any mismatch
     rolls back and exits non-zero.

After this, re-run:
  rebuild_paper_positions.py --strategy-id us_stk_sue_mom_01_v2 --force-rebalance
"""
import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "shared", "scripts"))
sys.path.insert(0, SHARED)
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402

SID = "us_stk_sue_mom_01_v2"
SIGNAL_FILE = ("/home/ubuntu/.hermes/profiles/qr_research/workspace/"
               "us_stk_sue_mom_01_v2_live_signals.json")

STALE_VINTAGES = ("2026-10-17", "2026-10-28", "2026-10-29")
EXPECTED_STALE = {
    # 2026-10-17 (17)
    "CVX", "SJM", "TGT", "WSM", "NWSA", "ADM", "NWS", "OXY", "MPC", "CSCO",
    "RVTY", "NVDA", "AMZN", "ANET", "MPWR", "CRM", "SMCI",
    # 2026-10-28 (5)
    "DLTR", "DG", "ULTA", "BBY", "ADSK",
    # 2026-10-29 (14)
    "CB", "COST", "RF", "PM", "MDT", "ELV", "DHR", "ROP", "LW", "FDS",
    "CCL", "DOCU", "DELL", "MDB",
}
CANCEL_OPENS = {"CB", "COST", "PM", "RF"}      # not in the November file
CANCEL_CLOSES = {"NTAP", "PSX", "VLO"}         # in the file — must stay held


def fail(msg):
    print(f"PRECONDITION FAILED: {msg}")
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Commit the remediation (default: dry-run, rollback)")
    args = ap.parse_args()

    file_doc = json.load(open(SIGNAL_FILE))
    file_tickers = {s["ticker"] for s in file_doc["signals"] if s.get("action") == "BUY"}
    file_stamp = file_doc["generated_at"]
    if len(file_tickers) != 20:
        fail(f"canonical file has {len(file_tickers)} BUY names, expected 20")

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        # ── Preconditions ────────────────────────────────────────────────
        cur.execute(
            """SELECT ticker, computed_at::date FROM gold.strategy_ticker_scores
               WHERE strategy_id=%s AND signal_action='BUY'""", (SID,))
        buy_rows = cur.fetchall()
        by_vintage = {}
        for t, v in buy_rows:
            by_vintage.setdefault(str(v), set()).add(t)
        stale = set().union(*(by_vintage.get(v, set()) for v in STALE_VINTAGES))
        current = by_vintage.get("2026-10-30", set())
        other = set().union(*[s for v, s in by_vintage.items()
                              if v not in STALE_VINTAGES and v != "2026-10-30"]) if by_vintage else set()
        if stale != EXPECTED_STALE:
            fail(f"stale BUY set mismatch: extra={sorted(stale - EXPECTED_STALE)} "
                 f"missing={sorted(EXPECTED_STALE - stale)}")
        if current != file_tickers:
            fail(f"2026-10-30 vintage != canonical file: "
                 f"extra={sorted(current - file_tickers)} "
                 f"missing={sorted(file_tickers - current)}")
        if other:
            fail(f"unexpected BUY vintages present: "
                 f"{sorted((v, sorted(s)) for v, s in by_vintage.items() if v not in STALE_VINTAGES + ('2026-10-30',))}")
        if stale & file_tickers:
            fail(f"stale set overlaps canonical file: {sorted(stale & file_tickers)}")
        print(f"preconditions OK: {len(stale)} stale BUY rows across "
              f"{len(STALE_VINTAGES)} vintages; 2026-10-30 vintage = canonical "
              f"file's 20 names (untouched)")

        cur.execute(
            """SELECT id, ticker, order_kind FROM gold.paper_pending_orders
               WHERE strategy_id=%s AND status='pending'""", (SID,))
        pending = cur.fetchall()
        pend_opens = {t for _, t, k in pending if k == "OPEN"}
        pend_closes = {t for _, t, k in pending if k == "CLOSE"}
        if not CANCEL_OPENS <= pend_opens:
            fail(f"wrong OPENs not pending: {sorted(CANCEL_OPENS - pend_opens)}")
        if not CANCEL_CLOSES <= pend_closes:
            fail(f"wrong CLOSEs not pending: {sorted(CANCEL_CLOSES - pend_closes)}")
        if len(pending) != 24:
            fail(f"pending count {len(pending)} != expected 24")
        print(f"preconditions OK: 24 pending orders; cancelling "
              f"{sorted(CANCEL_OPENS)} OPENs + {sorted(CANCEL_CLOSES)} CLOSEs")

        # ── Snapshots ────────────────────────────────────────────────────
        cur.execute(
            """CREATE TABLE IF NOT EXISTS gold.strategy_ticker_scores__sue_retire_bak_20261102
               (LIKE gold.strategy_ticker_scores INCLUDING ALL)""")
        cur.execute(
            """DELETE FROM gold.strategy_ticker_scores__sue_retire_bak_20261102
               WHERE strategy_id=%s""", (SID,))
        cur.execute(
            """INSERT INTO gold.strategy_ticker_scores__sue_retire_bak_20261102
               SELECT * FROM gold.strategy_ticker_scores
               WHERE strategy_id=%s AND signal_action='BUY' AND ticker = ANY(%s)""",
            (SID, sorted(EXPECTED_STALE)))
        n_bak = cur.rowcount
        if n_bak != 36:
            fail(f"snapshot rowcount {n_bak} != 36")
        cur.execute(
            """CREATE TABLE IF NOT EXISTS gold.paper_pending_orders__sue_cancel_bak_20261102
               (LIKE gold.paper_pending_orders INCLUDING ALL)""")
        cur.execute(
            """INSERT INTO gold.paper_pending_orders__sue_cancel_bak_20261102
               SELECT * FROM gold.paper_pending_orders
               WHERE strategy_id=%s AND status='pending'
                 AND ((order_kind='OPEN'  AND ticker = ANY(%s))
                   OR (order_kind='CLOSE' AND ticker = ANY(%s)))""",
            (SID, sorted(CANCEL_OPENS), sorted(CANCEL_CLOSES)))
        if cur.rowcount != 7:
            fail(f"pending-order snapshot rowcount {cur.rowcount} != 7")
        print("snapshots: 36 score rows -> "
              "gold.strategy_ticker_scores__sue_retire_bak_20261102; "
              "7 orders -> gold.paper_pending_orders__sue_cancel_bak_20261102")

        # ── 1. retire stale BUYs to SELL (replace-per-cycle semantics) ────
        retire_meta = json.dumps({
            "retired_by_signal_file": SIGNAL_FILE,
            "retire_reason": ("one-off remediation t_3effb556: stale vintage "
                              "BUY row absent from the canonical November "
                              "signal file"),
            "kanban_task_id": "t_3effb556",
        })
        cur.execute(
            """UPDATE gold.strategy_ticker_scores
               SET signal_action='SELL', score=0, entry_score=0,
                   exit_score=score, computed_at=%s, updated_at=NOW(),
                   criteria_met = COALESCE(criteria_met,'{}'::jsonb) || %s::jsonb
               WHERE strategy_id=%s AND signal_action='BUY' AND ticker = ANY(%s)""",
            (file_stamp, retire_meta, SID, sorted(EXPECTED_STALE)))
        if cur.rowcount != 36:
            fail(f"retire rowcount {cur.rowcount} != 36")
        print("retired 36 stale BUY rows -> SELL "
              f"(exit_score=prior score, computed_at={file_stamp})")

        # ── 2. cancel the 7 wrong pending orders ─────────────────────────
        cur.execute(
            """UPDATE gold.paper_pending_orders SET status='cancelled'
               WHERE strategy_id=%s AND status='pending'
                 AND ((order_kind='OPEN'  AND ticker = ANY(%s))
                   OR (order_kind='CLOSE' AND ticker = ANY(%s)))""",
            (SID, sorted(CANCEL_OPENS), sorted(CANCEL_CLOSES)))
        if cur.rowcount != 7:
            fail(f"cancel rowcount {cur.rowcount} != 7")
        cur.execute(
            "DELETE FROM consumption.strategy_paper_pending_current WHERE strategy_id=%s", (SID,))
        cur.execute(
            """INSERT INTO consumption.strategy_paper_pending_current
                 (strategy_id, ticker, order_kind, signal_date, n_shares,
                  signal_weight, assigned_capital, score, expected_fill, updated_at)
               SELECT strategy_id, ticker, order_kind, signal_date, n_shares,
                      signal_weight, assigned_capital, score, 'next_open', NOW()
               FROM gold.paper_pending_orders
               WHERE strategy_id=%s AND status='pending'""", (SID,))
        print("cancelled 7 wrong pending orders; pending mirror refreshed")

        # ── Post-checks (in-transaction) ─────────────────────────────────
        cur.execute(
            """SELECT count(*), string_agg(ticker, ',' ORDER BY ticker)
               FROM gold.strategy_ticker_scores
               WHERE strategy_id=%s AND signal_action='BUY'""", (SID,))
        n_buy, buy_set = cur.fetchone()
        if n_buy != 20 or set(buy_set.split(",")) != file_tickers:
            fail(f"post-retire BUY set wrong: {n_buy} rows")
        cur.execute(
            """SELECT count(*) FROM gold.paper_pending_orders
               WHERE strategy_id=%s AND status='pending'""", (SID,))
        n_pend = cur.fetchone()[0]
        if n_pend != 17:
            fail(f"post-cancel pending count {n_pend} != 17")
        print(f"post-checks OK: 20 BUY rows = canonical file; "
              f"17 pending orders remain (13 -> re-run stages the rest)")

        if args.apply:
            conn.commit()
            print("APPLIED: committed.")
        else:
            conn.rollback()
            print("DRY RUN: rolled back (re-run with --apply to commit).")
        return 0
    except SystemExit:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
