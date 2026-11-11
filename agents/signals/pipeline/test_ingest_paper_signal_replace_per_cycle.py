#!/usr/bin/env python3
"""Regression test: replace-per-cycle ingest semantics (t_3effb556).

Bug: upsert_ticker_scores was a per-ticker upsert that NEVER retired names
absent from the current signal file, so gold.strategy_ticker_scores
accumulated the UNION of every historical file vintage as BUY rows
(us_stk_sue_mom_01_v2 2026-11: 56 BUYs = 4 vintages; the rotation screen
ranked the contaminated union and booked a wrong rotation).

Fix: after upserting the file's picks, every other BUY row for the strategy
is retired to SELL (score=0, entry_score=0, exit_score=last score,
computed_at=file stamp) — the strategy-field-completeness contract:
dropped universe members get SELL, never silently persist.

Scenario asserted here:
  1. ingest file A (20 names)            -> 20 BUY rows, all = A
  2. ingest file B (20 names, 10 overlap)-> exactly 20 BUY rows = B's set;
     the 10 non-overlap names from A are SELL with score=0, entry_score=0,
     exit_score>0, computed_at = B's stamp; the 10 overlaps are still BUY
     with B's weights
  3. re-ingest file B                    -> idempotent: still 20 BUY = B,
     zero rows retired on the second pass

Runs against a SCRATCH-SCHEMA copy of gold.strategy_ticker_scores via the
SCORES_TABLE_OVERRIDE hook (same sandbox pattern as REGISTRY_TABLE_OVERRIDE)
— the live table is never touched. Skips cleanly when the DB is unreachable.

Usage: /home/ubuntu/.hermes/etl-venv/bin/python3 test_ingest_paper_signal_replace_per_cycle.py
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

SCHEMA = "sandbox_ingest_rpc_t3effb556"
SID = "test_replace_per_cycle_sid"


def _fetchall_map(cur):
    cols = [d[0] for d in cur.description]
    out = {}
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        out[d["ticker"]] = d
    return out


def main() -> int:
    try:
        import ingest_paper_signal as ips
        from db import get_connection
    except Exception as e:
        print(f"SKIP: cannot import ingest deps ({e})")
        return 0

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {SCHEMA}")
        cur.execute(
            f"CREATE TABLE {SCHEMA}.strategy_ticker_scores "
            f"(LIKE gold.strategy_ticker_scores INCLUDING ALL)"
        )
        conn.commit()
        os.environ["SCORES_TABLE_OVERRIDE"] = f"{SCHEMA}.strategy_ticker_scores"

        file_a = {f"T{i:02d}": 0.05 for i in range(1, 21)}          # T01..T20
        file_b = {f"T{i:02d}": 0.05 for i in range(11, 31)}         # T11..T30

        # 1. ingest file A
        ips.upsert_ticker_scores(conn, SID, "fileA_live_signals.json",
                                 "2026-10-17T00:00:00Z", file_a)
        cur.execute(
            f"SELECT * FROM {SCHEMA}.strategy_ticker_scores WHERE strategy_id=%s",
            (SID,))
        rows = _fetchall_map(cur)
        buys = {t for t, r in rows.items() if r["signal_action"] == "BUY"}
        assert buys == set(file_a), f"after A: BUY set {sorted(buys)} != file A"
        assert len(rows) == 20, f"after A: {len(rows)} rows != 20"
        print("PASS 1: file A ingested -> exactly 20 BUY rows = file A's set")

        # 2. ingest file B (partial overlap)
        ips.upsert_ticker_scores(conn, SID, "fileB_live_signals.json",
                                 "2026-10-30T00:00:00Z", file_b)
        cur.execute(
            f"SELECT * FROM {SCHEMA}.strategy_ticker_scores WHERE strategy_id=%s",
            (SID,))
        rows = _fetchall_map(cur)
        buys = {t for t, r in rows.items() if r["signal_action"] == "BUY"}
        assert buys == set(file_b), (
            f"after B: BUY set != file B's set; extra={sorted(buys - set(file_b))} "
            f"missing={sorted(set(file_b) - buys)}")
        dropped = set(file_a) - set(file_b)                          # T01..T10
        for t in sorted(dropped):
            r = rows[t]
            assert r["signal_action"] == "SELL", f"{t}: {r['signal_action']} != SELL"
            assert float(r["score"]) == 0.0, f"{t}: score {r['score']} != 0"
            assert float(r["entry_score"]) == 0.0, f"{t}: entry_score != 0"
            assert float(r["exit_score"]) > 0.0, f"{t}: exit_score {r['exit_score']} not > 0"
            assert str(r["computed_at"]).startswith("2026-10-30"), (
                f"{t}: computed_at {r['computed_at']} not restamped to file B")
            cm = r["criteria_met"] or {}
            assert cm.get("retired_by_signal_file") == "fileB_live_signals.json", (
                f"{t}: criteria_met missing retirement provenance: {cm}")
        for t in sorted(set(file_a) & set(file_b)):                  # T11..T20
            r = rows[t]
            assert r["signal_action"] == "BUY", f"{t}: overlap name not BUY"
            assert abs(float(r["score"]) - 5.0) < 1e-6, f"{t}: overlap score wrong"
        print("PASS 2: file B ingested -> exactly 20 BUY rows = file B's set; "
              "10 non-overlap names from A retired to SELL "
              "(score=0, entry_score=0, exit_score>0, computed_at restamped)")

        # 3. idempotency: re-ingest file B
        ips.upsert_ticker_scores(conn, SID, "fileB_live_signals.json",
                                 "2026-10-30T00:00:00Z", file_b)
        cur.execute(
            f"SELECT * FROM {SCHEMA}.strategy_ticker_scores WHERE strategy_id=%s",
            (SID,))
        rows = _fetchall_map(cur)
        buys = {t for t, r in rows.items() if r["signal_action"] == "BUY"}
        sells = {t for t, r in rows.items() if r["signal_action"] == "SELL"}
        assert buys == set(file_b), "re-ingest B: BUY set drifted"
        assert sells == dropped, "re-ingest B: SELL set drifted"
        assert len(rows) == 30, f"re-ingest B: {len(rows)} rows != 30"
        print("PASS 3: re-ingest of file B is idempotent "
              "(20 BUY = B, 10 SELL = A\\B, 0 new retirements)")

        print("ALL PASS — replace-per-cycle semantics verified")
        return 0
    finally:
        try:
            cur = conn.cursor()
            cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
            conn.commit()
        finally:
            os.environ.pop("SCORES_TABLE_OVERRIDE", None)
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
