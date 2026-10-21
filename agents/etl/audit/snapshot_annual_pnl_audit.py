#!/usr/bin/env python3
"""t_ce0deace: snapshot legacy annual_pnl_YYYY values before correction.

Captures, for the LATEST run of each strategy published in
consumption.strategy_monthly_returns, the current values of
gold.strategy_backtest_runs.annual_pnl_2024/2025/2026 (+ returns_oos) into
gold.strategy_backtest_runs_annual_pnl_audit (phase='before_snapshot') and a
versioned CSV under agents/etl/audit/.

This is the rollback + before/after comparison record for t_6ea23eae
(origin t_d152898f): 21 of the 30 published strategies hold legacy UNWEIGHTED
trades-sum annuals that will be replaced by research book annuals.

Re-runnable: prior 'before_snapshot' rows for this task are deleted and
re-captured, so the table holds exactly one canonical pre-correction snapshot
per run.

Credentials: /home/ubuntu/.env via OPENCLAW_DATABASE_URL.
"""
import csv
import os
import sys

TASK_ID = "t_ce0deace"
ORIGIN_TASK = "t_d152898f"
CORRECTION_TASK = "t_6ea23eae"
ETL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(
    ETL_ROOT, "audit", "annual_pnl_audit_2026-09-07_t_ce0deace.csv"
)
EXPECTED_FLAGGED_FALSE = {
    "hk_ipo_day1_green_momentum_v1",
    "hk_ipo_postlisting_drift_p1",
    "hk_ipo_postlisting_drift_p1_v3",
    "hk_ipo_postlisting_drift_p2",
    "hk_stk_52wh_mom_04",
    "sg_stk_52wh_mom_13",
}


def load_dsn():
    dsn = os.environ.get("OPENCLAW_DATABASE_URL")
    if dsn:
        return dsn
    with open("/home/ubuntu/.env") as f:
        for line in f:
            line = line.strip()
            if line.startswith("OPENCLAW_DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENCLAW_DATABASE_URL not set in /home/ubuntu/.env")


def main():
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(load_dsn())
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # strategies currently published in the consumption view
    cur.execute("SELECT DISTINCT strategy_id FROM consumption.strategy_monthly_returns")
    published = sorted(r["strategy_id"] for r in cur.fetchall())

    # config flag (default true when no row)
    cur.execute(
        "SELECT strategy_id, config_value FROM gold.strategy_configs "
        "WHERE config_key = 'trades_sum_is_book_annual_return'"
    )
    flags = {r["strategy_id"]: (r["config_value"] is True or str(r["config_value"]).lower() == "true")
             for r in cur.fetchall()}

    # latest run per published strategy
    cur.execute(
        """
        SELECT DISTINCT ON (r.strategy_id)
               r.strategy_id, r.run_id, r.run_number, r.created_at,
               r.annual_pnl_2024, r.annual_pnl_2025, r.annual_pnl_2026,
               r.returns_oos
        FROM gold.strategy_backtest_runs r
        WHERE r.strategy_id = ANY(%s)
        ORDER BY r.strategy_id, r.created_at DESC NULLS LAST,
                 r.run_number DESC NULLS LAST, r.run_id DESC
        """,
        (published,),
    )
    rows = cur.fetchall()
    if len(rows) != len(published):
        missing = sorted(set(published) - {r["strategy_id"] for r in rows})
        print(f"WARNING: {len(missing)} published strategies have no backtest run: {missing}")

    # re-runnable: replace this task's prior before_snapshot rows
    cur.execute(
        "DELETE FROM gold.strategy_backtest_runs_annual_pnl_audit "
        "WHERE phase = 'before_snapshot' AND task_id = %s",
        (TASK_ID,),
    )
    deleted = cur.rowcount

    insert_sql = """
        INSERT INTO gold.strategy_backtest_runs_annual_pnl_audit
            (phase, task_id, strategy_id, run_id,
             annual_pnl_2024, annual_pnl_2025, annual_pnl_2026, returns_oos,
             trades_sum_is_book_annual_return)
        VALUES ('before_snapshot', %s, %s, %s, %s, %s, %s, %s, %s)
    """
    flagged_false = set()
    for r in rows:
        flag = flags.get(r["strategy_id"], True)
        if flag is False:
            flagged_false.add(r["strategy_id"])
        cur.execute(insert_sql, (
            TASK_ID, r["strategy_id"], r["run_id"],
            r["annual_pnl_2024"], r["annual_pnl_2025"], r["annual_pnl_2026"],
            r["returns_oos"], flag,
        ))

    # versioned CSV
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "strategy_id", "run_id", "run_number",
                    "run_created_at", "annual_pnl_2024", "annual_pnl_2025",
                    "annual_pnl_2026", "returns_oos",
                    "trades_sum_is_book_annual_return"])
        for r in sorted(rows, key=lambda x: x["strategy_id"]):
            w.writerow([TASK_ID, r["strategy_id"], r["run_id"], r["run_number"],
                        r["created_at"],
                        r["annual_pnl_2024"], r["annual_pnl_2025"],
                        r["annual_pnl_2026"], r["returns_oos"],
                        flags.get(r["strategy_id"], True)])

    conn.commit()

    print(f"published strategies : {len(published)}")
    print(f"runs snapshotted     : {len(rows)}")
    print(f"prior snapshot rows replaced: {deleted}")
    print(f"CSV written          : {CSV_PATH}")
    print(f"flag false (book annuals verified): {sorted(flagged_false)}")
    unexpected = flagged_false - EXPECTED_FLAGGED_FALSE
    missing_flag = EXPECTED_FLAGGED_FALSE - flagged_false
    if unexpected or missing_flag:
        print(f"FLAG MISMATCH: unexpected={sorted(unexpected)} missing={sorted(missing_flag)}")
    else:
        print("flag set matches expectation (4 hk_ipo + hk_stk_52wh_mom_04 + sg_stk_52wh_mom_13)")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
