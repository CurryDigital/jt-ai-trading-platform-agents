#!/usr/bin/env python3
"""Scheduled OOS-window extension re-run for paper-deployed strategies (kanban t_f5e3164b).

PROBLEM
-------
Paper-deployed event-driven strategies with time-based exits (e.g.
hk_ipo_postlisting_drift_p1_v3, hold 20td) show stale OPEN rows on the
Strategy Detail > Simulation tab whenever a position's scheduled exit falls
AFTER the latest backtest run's oos_end. Research re-runs are manual, so the
most recent entries appear to "forget to sell" (concrete instance: t_c84850c0,
run 4e941d50 left 2249.HK + 6745.HK open at 19td though time_exit_20td was
2026-09-04).

WHAT THIS JOB DOES
------------------
For every gold.strategy_registry row with status='paper' that (a) has per-trade
rows in gold.strategy_backtest_trades and (b) carries a
gold.strategy_configs config_key='oos_window_refresh_engine' jsonb payload
(registry-gated engine of record — never a blind scan of research dirs):

  1. Re-runs the research backtest engine (subprocess). Engines read the
     silver layer directly and auto-extend oos_end to the latest price date.
  2. Validates the fresh artifacts (trade count match, no window shrink,
     previous run's (ticker, entry_date) keys must be a subset of the new run).
  3. In ONE transaction: inserts a NEW gold.strategy_backtest_runs row
     (next run_number; historical runs are never mutated), moves the per-trade
     detail by deleting ALL prior runs' trade rows for the strategy and
     inserting the new run's rows (required until the UI ledger query gains a
     run filter — backend main.py SELECT is not run-filtered, so superseded
     rows duplicate every trade in the Simulation tab), and refreshes
     gold.strategy_registry OOS metrics.
  4. Verifies post-write: DB open-row count == engine open count, and total
     per-strategy trade rows == latest run's trade_count_oos (no duplicates).
  5. Logs one row per strategy to gold.oos_window_refresh_log and one
     structured line to stdout: new run_id, oos_start/oos_end, open-trade
     count before/after.

Strategies whose engine is not script-reproducible simply have no
oos_window_refresh_engine config row and are skipped by construction; a config
row pointing at a missing script is flagged 'skipped_not_reproducible'.
Nothing is ever faked: any validation failure rolls back and logs 'error'.

Cadence: weekly via Hermes cron qr_etl.oos_window_refresh (wrapper
scripts/oos_window_refresh.sh). Weekly is ample — the artifact only goes stale
when a scheduled exit passes the last run's window end.

Usage:
  python3 refresh_paper_oos_window.py [--dry-run] [--strategy-id SID]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

ETL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ETL_ROOT, "shared", "scripts"))
import db  # noqa: E402  (shared connection contract: ~/.hermes/profiles/qr_etl/env/etl.env)

REQUIRED_CFG_KEYS = ("engine", "results_json", "trades_csv")


def log(msg):
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}", flush=True)


def engine_env():
    """Map etl.env DB_* vars to the OPENCLAW_DB_* vars the research engines read."""
    env = dict(os.environ)
    env["OPENCLAW_DB_HOST"] = os.environ["DB_HOST"]
    env["OPENCLAW_DB_PORT"] = os.environ.get("DB_PORT", "5432")
    env["OPENCLAW_DB_NAME"] = os.environ["DB_NAME"]
    env["OPENCLAW_DB_USER"] = os.environ["DB_USER"]
    env["OPENCLAW_DB_PASSWORD"] = os.environ["DB_PASSWORD"]
    return env


_ENGINE_PY = None


def engine_python(cfg):
    """Research engines need pandas/numpy/psycopg2 — present in system python3,
    NOT in the Hermes venv that runs this job. Probe once, cache the winner."""
    global _ENGINE_PY
    if _ENGINE_PY:
        return _ENGINE_PY
    for cand in [cfg.get("python"), "/usr/bin/python3", sys.executable]:
        if not cand or not os.path.isfile(cand):
            continue
        r = subprocess.run([cand, "-c", "import pandas, numpy, psycopg2"],
                           capture_output=True, timeout=60)
        if r.returncode == 0:
            _ENGINE_PY = cand
            return cand
    raise RuntimeError("no python interpreter with pandas/numpy/psycopg2 found")


def load_candidates(cur, only_sid=None):
    q = """
        SELECT r.strategy_id, c.config_value
        FROM gold.strategy_registry r
        JOIN gold.strategy_configs c
          ON c.strategy_id = r.strategy_id
         AND c.config_key = 'oos_window_refresh_engine'
        WHERE r.status = 'paper'
          AND EXISTS (SELECT 1 FROM gold.strategy_backtest_trades t
                      WHERE t.strategy_id = r.strategy_id)
    """
    params = ()
    if only_sid:
        q += " AND r.strategy_id = %s"
        params = (only_sid,)
    cur.execute(q + " ORDER BY r.strategy_id", params)
    return cur.fetchall()


def snapshot_before(cur, sid):
    cur.execute("""
        SELECT run_id, run_number, oos_end, trade_count_oos
        FROM gold.strategy_backtest_runs
        WHERE strategy_id = %s
        ORDER BY run_number DESC LIMIT 1
    """, (sid,))
    row = cur.fetchone()
    prev = {"run_id": str(row[0]), "run_number": row[1],
            "oos_end": row[2], "trade_count_oos": row[3]} if row else None
    cur.execute("""
        SELECT count(*), count(*) FILTER (WHERE exit_date IS NULL)
        FROM gold.strategy_backtest_trades
        WHERE strategy_id = %s AND period = 'OOS'
    """, (sid,))
    trades_before, open_before = cur.fetchone()
    cur.execute("""
        SELECT ticker, entry_date::text FROM gold.strategy_backtest_trades
        WHERE strategy_id = %s AND period = 'OOS' AND run_id = %s
    """, (sid, prev["run_id"]) if prev else (sid, None))
    prev_keys = {(r[0], r[1]) for r in cur.fetchall()} if prev else set()
    return prev, trades_before, open_before, prev_keys


def run_engine(cfg, started_at):
    engine = cfg["engine"]
    if not os.path.isfile(engine):
        return False, f"engine script not found: {engine}"
    timeout = int(cfg.get("timeout_seconds", 900))
    proc = subprocess.run(
        [engine_python(cfg), engine],
        cwd=os.path.dirname(engine),
        env=engine_env(),
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        return False, f"engine exited rc={proc.returncode}: {tail}"
    for art in (cfg["results_json"], cfg["trades_csv"]):
        if not os.path.isfile(art):
            return False, f"engine did not write expected artifact: {art}"
        if os.path.getmtime(art) < started_at - 5:
            return False, f"artifact stale (engine exited 0 but did not refresh): {art}"
    return True, "ok"


def load_artifacts(cfg):
    """stdlib csv only — this job runs in the Hermes venv (no pandas)."""
    import csv
    res = json.load(open(cfg["results_json"]))
    with open(cfg["trades_csv"], newline="") as f:
        trades = list(csv.DictReader(f))
    return res, trades


def write_log(cur, sid, status, prev, new_run_id, new_oos_end,
              trades_before, trades_after, open_before, open_after, message):
    cur.execute("""
        INSERT INTO gold.oos_window_refresh_log
        (strategy_id, status, prev_run_id, new_run_id, prev_oos_end, new_oos_end,
         trades_before, trades_after, open_before, open_after, message)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (sid, status,
          prev["run_id"] if prev else None, new_run_id,
          prev["oos_end"] if prev else None, new_oos_end,
          trades_before, trades_after, open_before, open_after, message))


def process_strategy(conn, sid, cfg, dry_run, started_at):
    cur = conn.cursor()
    missing = [k for k in REQUIRED_CFG_KEYS if k not in cfg]
    if missing:
        write_log(cur, sid, "skipped_not_reproducible", None, None, None,
                  None, None, None, None, f"config missing keys: {missing}")
        conn.commit()
        return "error", f"config missing keys {missing}"

    prev, trades_before, open_before, prev_keys = snapshot_before(cur, sid)

    ok, msg = run_engine(cfg, started_at)
    if not ok:
        write_log(cur, sid, "skipped_not_reproducible", prev, None, None,
                  trades_before, None, open_before, None, msg)
        conn.commit()
        return "error", msg

    res, trades = load_artifacts(cfg)
    new_oos_end = res["oos_end"]
    n_csv = len(trades)
    open_csv = sum(1 for t in trades if t["closed"].strip().lower() != "true")

    # ---- validation gates (any failure => no writes, real error logged) ----
    if res["trade_count_oos"] != n_csv:
        msg = f"trade_count_oos {res['trade_count_oos']} != trades csv rows {n_csv}"
    elif prev and str(new_oos_end) < str(prev["oos_end"]):
        msg = f"window shrank: new oos_end {new_oos_end} < prev {prev['oos_end']}"
    else:
        new_keys = {(t["ticker"], str(t["entry_date"])[:10]) for t in trades}
        missing_keys = prev_keys - new_keys
        if missing_keys:
            msg = f"new run dropped {len(missing_keys)} trades present in latest run: {sorted(missing_keys)[:5]}"
        else:
            msg = None
    if msg:
        write_log(cur, sid, "error", prev, None, None,
                  trades_before, n_csv, open_before, open_csv, msg)
        conn.commit()
        return "error", msg

    no_change = (prev and str(new_oos_end) <= str(prev["oos_end"])
                 and open_csv == open_before and n_csv == trades_before)
    if no_change:
        write_log(cur, sid, "skipped_no_change", prev, None, new_oos_end,
                  trades_before, n_csv, open_before, open_csv,
                  f"oos_end unchanged at {new_oos_end}; open {open_before}->{open_csv}; nothing to refresh")
        conn.commit()
        return "skipped_no_change", f"oos_end {new_oos_end} unchanged, open {open_before}->{open_csv}"

    if dry_run:
        return "dry_run", (f"would insert run_number {(prev['run_number'] + 1) if prev else 1}, "
                           f"oos_end {prev['oos_end'] if prev else None}->{new_oos_end}, "
                           f"trades {trades_before}->{n_csv}, open {open_before}->{open_csv}")

    exit_reason_default = cfg.get("exit_reason_default")
    try:
        cur.execute("SELECT COALESCE(MAX(run_number),0) FROM gold.strategy_backtest_runs WHERE strategy_id=%s", (sid,))
        run_number = cur.fetchone()[0] + 1
        cur.execute("""
            INSERT INTO gold.strategy_backtest_runs
            (strategy_id, run_number, run_by, is_start, is_end, oos_start, oos_end,
             sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
             turnover_oos, profit_factor_oos, annual_pnl_2024, annual_pnl_2025, annual_pnl_2026,
             max_single_asset_exposure, parameters_used, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING run_id
        """, (sid, run_number, "etl-oos-refresh",
              res["oos_start"], new_oos_end, res["oos_start"], new_oos_end,
              res["sharpe_oos"], res["returns_oos"], res["max_drawdown_oos"],
              res["trade_count_oos"], res["win_rate_oos"], res.get("turnover"),
              res.get("profit_factor_oos"),
              res.get("annual_pnl_2024"), res.get("annual_pnl_2025"), res.get("annual_pnl_2026"),
              cfg.get("max_single_asset_exposure", 0.2), json.dumps(res.get("parameters", {})),
              (f"Scheduled OOS-window extension re-run (Hermes cron qr_etl.oos_window_refresh, "
               f"kanban t_f5e3164b). oos_end {prev['oos_end'] if prev else None} -> {new_oos_end}. "
               f"Trade detail moved to this run (UI simulation ledger is not run-filtered); "
               f"{trades_before} prior-run trade rows deleted, {n_csv} inserted. "
               f"Open OOS trades {open_before} -> {open_csv}.")))
        new_run_id = str(cur.fetchone()[0])

        cur.execute("DELETE FROM gold.strategy_backtest_trades WHERE strategy_id=%s AND run_id <> %s",
                    (sid, new_run_id))
        deleted = cur.rowcount

        n = 0
        for t in trades:
            closed = t["closed"].strip().lower() == "true"
            reason = ((t.get("exit_reason") or exit_reason_default) if closed else None)
            cur.execute("""
                INSERT INTO gold.strategy_backtest_trades
                (run_id, strategy_id, ticker, period, entry_date, exit_date,
                 entry_price, exit_price, pnl_pct, holding_days, exit_reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (new_run_id, sid, t["ticker"], "OOS",
                  t["entry_date"], t["exit_date"] if closed else None,
                  float(t["entry_px"]), float(t["exit_px"]) if closed else None,
                  round(float(t["pnl"]), 6) if closed else None,
                  int(t["holding_days"]), reason))
            n += 1

        cur.execute("""
            UPDATE gold.strategy_registry
            SET sharpe_oos=%s, returns_oos=%s, max_drawdown_oos=%s, trade_count_oos=%s,
                win_rate_oos=%s, profit_factor_oos=%s, updated_at=NOW()
            WHERE strategy_id=%s
        """, (res["sharpe_oos"], res["returns_oos"], res["max_drawdown_oos"],
              res["trade_count_oos"], res["win_rate_oos"], res.get("profit_factor_oos"), sid))

        # ---- post-write verification INSIDE the transaction ----
        cur.execute("""
            SELECT count(*), count(*) FILTER (WHERE exit_date IS NULL)
            FROM gold.strategy_backtest_trades
            WHERE strategy_id=%s AND period='OOS'
        """, (sid,))
        total_after, open_after = cur.fetchone()
        if total_after != res["trade_count_oos"]:
            raise RuntimeError(f"post-write total {total_after} != trade_count_oos {res['trade_count_oos']} (duplicates?)")
        if open_after != open_csv:
            raise RuntimeError(f"post-write open {open_after} != engine open {open_csv}")

        write_log(cur, sid, "ok", prev, new_run_id, new_oos_end,
                  trades_before, n, open_before, open_after,
                  f"run_number={run_number}; deleted_prior_rows={deleted}")
        conn.commit()
        return "ok", (f"new_run={new_run_id} run_number={run_number} "
                      f"oos {res['oos_start']}->{new_oos_end} "
                      f"trades {trades_before}->{n} (deleted {deleted} prior rows) "
                      f"open {open_before}->{open_after}")
    except Exception as e:
        conn.rollback()
        cur2 = conn.cursor()
        write_log(cur2, sid, "error", prev, None, None,
                  trades_before, n_csv, open_before, open_csv, f"tx rolled back: {e}")
        conn.commit()
        return "error", f"tx rolled back: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="run engines + validation, report planned writes, touch nothing")
    ap.add_argument("--strategy-id", default=None)
    args = ap.parse_args()

    started_at = time.time()
    conn = db.get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    candidates = load_candidates(cur, args.strategy_id)
    log(f"candidates: {[c[0] for c in candidates]} (dry_run={args.dry_run})")
    if not candidates:
        log("nothing to do")
        return 0

    worst = 0
    for sid, cfg in candidates:
        try:
            status, msg = process_strategy(conn, sid, cfg, args.dry_run, started_at)
        except subprocess.TimeoutExpired:
            status, msg = "error", "engine subprocess timed out"
            cur2 = conn.cursor()
            write_log(cur2, sid, "error", None, None, None, None, None, None, None, msg)
            conn.commit()
        except Exception as e:
            status, msg = "error", f"unexpected: {e}"
            conn.rollback()
            cur2 = conn.cursor()
            write_log(cur2, sid, "error", None, None, None, None, None, None, None, msg)
            conn.commit()
        log(f"{status.upper():24s} {sid}: {msg}")
        if status == "error":
            worst = 1

    conn.close()
    log(f"done, exit={worst}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
