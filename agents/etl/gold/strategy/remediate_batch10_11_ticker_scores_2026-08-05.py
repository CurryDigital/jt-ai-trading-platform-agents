#!/usr/bin/env python3
"""Remediation t_286aff03 (2026-08-05): batch10/11 ticker-score coverage gaps + stray CASH rows.

Post-handoff verify (verify_post_handoff_db.py) FAILED for 9/10 batch10/11 strategies:
gold.strategy_ticker_scores held only current holdings, not full registry universes.

Actions (idempotent):
1. DELETE stray 'CASH' score rows on etf_country_rot_10_v2 and etf_tech_mom_13
   (CASH is not in either registry universe).
2. INSERT one score row per registry universe ticker missing from
   gold.strategy_ticker_scores: score=0, signal_action='HOLD',
   signal_source='ingested' (matches batch10/11 ingest convention).
   Registry universe == handoff manifest universe (verified identical for all 10).

Run: source /home/ubuntu/.hermes/etl-venv/bin/activate && python remediate_batch10_11_ticker_scores_2026-08-05.py
Requires /home/ubuntu/.env (OPENCLAW_DB_*); dbname forced to 'aitrading'
(.env carries stale OPENCLAW_DB_NAME=airtrading).
"""
import os
import psycopg2


def load_env(path="/home/ubuntu/.env"):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k, v.strip().strip('"'))


STRATEGY_IDS = [
    "us_stk_sue_mom_01_v2",
    "hk_stk_52wh_mom_04",
    "etf_tsmom_basket_07",
    "etf_country_rot_10_v2",
    "cn_stk_lowvol_12",
    "sg_stk_52wh_mom_13",
    "us_stk_lowbeta_14",
    "etf_vix_scaled_11",
    "etf_tech_mom_13",
    "etf_def_sector_rot_12_w",
]

STRAY_CASH_STRATEGIES = ["etf_country_rot_10_v2", "etf_tech_mom_13"]


def main():
    load_env()
    conn = psycopg2.connect(
        host=os.environ["OPENCLAW_DB_HOST"],
        port=os.environ.get("OPENCLAW_DB_PORT", "5432"),
        dbname="aitrading",
        user=os.environ["OPENCLAW_DB_USER"],
        password=os.environ["OPENCLAW_DB_PASSWORD"],
    )
    cur = conn.cursor()

    # 1. Delete stray CASH rows
    cur.execute(
        """
        DELETE FROM gold.strategy_ticker_scores
        WHERE strategy_id = ANY(%s) AND ticker = 'CASH'
        RETURNING strategy_id
        """,
        (STRAY_CASH_STRATEGIES,),
    )
    deleted = cur.fetchall()
    print(f"DELETED stray CASH rows: {len(deleted)} -> {sorted(r[0] for r in deleted)}")

    # 2. Insert one row per universe ticker not yet scored
    cur.execute(
        "SELECT strategy_id, universe_tickers FROM gold.strategy_registry WHERE strategy_id = ANY(%s)",
        (STRATEGY_IDS,),
    )
    registry = {r[0]: (r[1] or []) for r in cur.fetchall()}

    inserted_total = 0
    for sid in STRATEGY_IDS:
        universe = registry.get(sid)
        if universe is None:
            print(f"ERROR: {sid} not in registry — skipped")
            continue
        cur.execute(
            "SELECT ticker FROM gold.strategy_ticker_scores WHERE strategy_id = %s",
            (sid,),
        )
        scored = {r[0] for r in cur.fetchall()}
        missing = sorted(set(universe) - scored)
        stray = sorted(scored - set(universe))
        if stray:
            print(f"WARNING: {sid} still has stray scores {stray} — not deleted (not CASH)")
        if not missing:
            print(f"{sid}: OK {len(scored)}/{len(universe)} — no insert needed")
            continue
        rows = [(sid, t, 0, "HOLD", "ingested") for t in missing]
        cur.executemany(
            """
            INSERT INTO gold.strategy_ticker_scores
                (strategy_id, ticker, score, signal_action, signal_source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (strategy_id, ticker) DO NOTHING
            """,
            rows,
        )
        inserted_total += len(rows)
        print(f"{sid}: inserted {len(rows)} zero-score rows (coverage {len(scored)}+{len(rows)}={len(scored)+len(rows)}/{len(universe)})")

    conn.commit()
    print(f"COMMITTED. total inserted={inserted_total}, deleted={len(deleted)}")
    conn.close()


if __name__ == "__main__":
    main()
