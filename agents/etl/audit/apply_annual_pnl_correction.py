#!/usr/bin/env python3
"""t_86a4a973: apply verified research book annuals to gold.strategy_backtest_runs.

Replaces legacy UNWEIGHTED trades-sum annual_pnl_YYYY values with the verified
calendar-year book annuals computed in t_abb57f07 (annual_compounds_t_abb57f07.json,
curve-compounding mirror of the ETL builder, verified against
gold.strategy_backtest_monthly_returns within 1e-6).

Scope:
  - LATEST run per strategy (same DISTINCT ON ordering as the t_ce0deace
    snapshot), restricted to strategies published in
    consumption.strategy_monthly_returns.
  - Only strategies on the verified list (27 entries in the artifact).
    keep_legacy_values (H3_VIX_TAIL_HEDGE_V1, S14_OIL_SQUEEZE_DISC_V1,
    S9_MACD_Momentum_V2) are NEVER touched.
  - Columns annual_pnl_2024/2025/2026 (the only annual_pnl_YYYY columns on the
    table). Years present in the artifact are set to the book annual; years
    absent from the artifact (outside the latest run's OOS window) are set to
    NULL — no book annual exists for those years and any legacy value there is
    a bogus trades-sum (e.g. us_stk_sue_mom_01_v2 annual_pnl_2024 = +5.05).
  - Every column change is logged to
    gold.strategy_backtest_runs_annual_pnl_audit (phase='update',
    task_id='t_86a4a973') with column_name, old_value, new_value.

Idempotent: only actual changes are applied and logged; a second run updates
0 rows and appends 0 audit rows. NaN legacy values are treated as changed
(NaN != NaN) and overwritten/nulled.

Usage:
  python3 apply_annual_pnl_correction.py --dry-run   # print plan, no writes
  python3 apply_annual_pnl_correction.py --apply     # write

Credentials: /home/ubuntu/.env via OPENCLAW_DATABASE_URL.
"""
import argparse
import json
import os
import sys
from decimal import Decimal

TASK_ID = "t_86a4a973"
ETL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACT_PATH = os.path.join(ETL_ROOT, "audit", "annual_compounds_t_abb57f07.json")
ANNUAL_COLS = ["annual_pnl_2024", "annual_pnl_2025", "annual_pnl_2026"]
YEARS = [c.rsplit("_", 1)[1] for c in ANNUAL_COLS]

EXPECTED_KEEP_LEGACY = {"H3_VIX_TAIL_HEDGE_V1", "S14_OIL_SQUEEZE_DISC_V1", "S9_MACD_Momentum_V2"}


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


def is_nan(v):
    return isinstance(v, Decimal) and (v.is_nan() or v.is_infinite())


def values_equal(a, b):
    """SQL-ish equality for our purposes; NaN never equals anything."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if is_nan(a) or is_nan(b):
        return False
    return Decimal(str(a)) == Decimal(str(b))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with open(ARTIFACT_PATH) as f:
        art = json.load(f)
    annuals = art["annual_compounds"]
    verified = set(art["verified"])
    keep_legacy = set(art["keep_legacy_values"])

    if set(annuals) != verified:
        raise RuntimeError(f"artifact mismatch: annuals keys != verified: {set(annuals) ^ verified}")
    if keep_legacy != EXPECTED_KEEP_LEGACY:
        raise RuntimeError(f"unexpected keep_legacy_values: {sorted(keep_legacy)}")
    if verified & keep_legacy:
        raise RuntimeError("verified/keep_legacy overlap")

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(load_dsn())
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT DISTINCT strategy_id FROM consumption.strategy_monthly_returns")
    published = sorted(r["strategy_id"] for r in cur.fetchall())
    targets = sorted(verified & set(published))
    missing = sorted(verified - set(published))
    if missing:
        raise RuntimeError(f"verified strategies not published: {missing}")
    if keep_legacy - set(published):
        raise RuntimeError("keep-legacy strategy not published")

    cur.execute(
        "SELECT strategy_id, config_value FROM gold.strategy_configs "
        "WHERE config_key = 'trades_sum_is_book_annual_return'"
    )
    flags = {r["strategy_id"]: (r["config_value"] is True or str(r["config_value"]).lower() == "true")
             for r in cur.fetchall()}

    cur.execute(
        f"""
        SELECT DISTINCT ON (r.strategy_id)
               r.strategy_id, r.run_id, r.run_number, r.created_at,
               r.annual_pnl_2024, r.annual_pnl_2025, r.annual_pnl_2026,
               r.returns_oos
        FROM gold.strategy_backtest_runs r
        WHERE r.strategy_id = ANY(%s)
        ORDER BY r.strategy_id, r.created_at DESC NULLS LAST,
                 r.run_number DESC NULLS LAST, r.run_id DESC
        """,
        (targets,),
    )
    runs = {r["strategy_id"]: r for r in cur.fetchall()}
    if set(runs) != set(targets):
        raise RuntimeError(f"no latest run for: {sorted(set(targets) - set(runs))}")

    # plan
    plan = []  # (strategy_id, run_id, column, old, new)
    for sid in targets:
        row = runs[sid]
        for col, year in zip(ANNUAL_COLS, YEARS):
            old = row[col]
            if is_nan(old):
                old = None
            new = Decimal(str(annuals[sid][year])) if year in annuals[sid] else None
            if not values_equal(old, new):
                plan.append((sid, row["run_id"], col, old, new))

    n_runs_touched = len({p[0] for p in plan})
    print(f"verified strategies targeted : {len(targets)}")
    print(f"keep-legacy (untouched)      : {sorted(keep_legacy)}")
    print(f"column changes planned       : {len(plan)} across {n_runs_touched} runs")
    for sid, run_id, col, old, new in plan:
        print(f"  {sid:45s} {col:18s} {str(old):>12s} -> {str(new)}")

    if args.dry_run:
        print("DRY RUN — no writes")
        conn.rollback()
        return 0

    update_sql = f"""
        UPDATE gold.strategy_backtest_runs
        SET {', '.join(f"{c} = %s" for c in ANNUAL_COLS)}
        WHERE run_id = %s
    """
    audit_sql = """
        INSERT INTO gold.strategy_backtest_runs_annual_pnl_audit
            (phase, task_id, strategy_id, run_id, column_name, old_value, new_value,
             trades_sum_is_book_annual_return)
        VALUES ('update', %s, %s, %s, %s, %s, %s, %s)
    """
    updated_runs = 0
    for sid in targets:
        row = runs[sid]
        new_vals = tuple(
            Decimal(str(annuals[sid][y])) if y in annuals[sid] else None for y in YEARS
        )
        cur.execute(update_sql, (*new_vals, row["run_id"]))
        if cur.rowcount != 1:
            raise RuntimeError(f"update touched {cur.rowcount} rows for {sid} run {row['run_id']}")
        updated_runs += 1
    for sid, run_id, col, old, new in plan:
        cur.execute(audit_sql, (TASK_ID, sid, run_id, col, old, new, flags.get(sid, True)))

    conn.commit()
    print(f"APPLIED: runs updated = {updated_runs}, audit rows inserted = {len(plan)}")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
