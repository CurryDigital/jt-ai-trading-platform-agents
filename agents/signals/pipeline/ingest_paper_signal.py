#!/usr/bin/env python3
"""
WRITE_SIGNAL: generic paper-strategy signal ingester.

Replaces the three near-identical single-strategy scripts (2026-07-10):
    ingest_lowvol_dividend_quality.py   (US_STK_LOWVOL_DIV_02)
    ingest_momentum_leaders.py          (US_STK_MOM_LDR_01)
    ingest_small_cap_credit_spread.py   (US_STK_SMALLCAP_CREDIT_03)
They were 202-line copies differing by exactly two constants, so every bug
fix had to be applied three times. Strategy identity now comes from the CLI.

Usage (one strategy):
    python3 ingest_paper_signal.py \
        --strategy-id US_STK_MOM_LDR_01 \
        --strategy-name Momentum_Leaders \
        --signal-file /path/to/deployed_5_live_signals_2026-07-08.json

Usage (every strategy present in the signal file):
    python3 ingest_paper_signal.py --all --signal-file /path/to/signals.json

The signal file's "signals" object is keyed by strategy NAME; with --all the
registry row is looked up by name to resolve the strategy_id, and names
missing from gold.strategy_registry are reported and skipped (never
invented).

Reads:
  the deployed live-signal JSON ({"generated_at": ..., "signals": {name: {ticker: weight}}})

Writes:
  - gold.strategy_registry (universe_tickers, signal_file_path, last_signal_at)
  - gold.strategy_ticker_scores (live signal rows: BUY at 100% score, weight*100 as entry_score)
  - consumption.signal_logs (downstream signal feed for execution/UI)
  - gold.agent_events (audit event: signal ingested by etl-manager)

Operational notes:
  - PAPER strategies only; no broker orders are placed.
  - We do NOT write to gold.paper_run_log here because that table is a daily
    run log (run_type IN morning/eod/weekly_review) rather than a per-strategy
    signal ledger. The agent_event records the same ingestion metadata.
"""
import argparse
import json
import os
import sys
from datetime import datetime, date

import pytz

# Repo-relative import — the predecessors hardcoded the absolute Hermes
# profile path (~/.hermes/profiles/qr_etl/...), which broke anywhere else.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "etl", "shared", "scripts"))
sys.path.insert(0, SHARED)
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402

HKT = pytz.timezone("Asia/Hong_Kong")


def now_hkt() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_signal_file(path: str) -> tuple:
    with open(path, "r") as f:
        data = json.load(f)
    signals = data.get("signals") or {}
    if not signals:
        raise SystemExit(f"No 'signals' object found in {path}")
    return data.get("generated_at", "unknown"), signals


def resolve_strategy_id(conn, strategy_name: str):
    """Look up strategy_id by registry name. Returns None if absent."""
    cur = conn.cursor()
    cur.execute(
        "SELECT strategy_id FROM gold.strategy_registry WHERE name = %s",
        (strategy_name,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def ensure_strategy_registry(conn, strategy_id, strategy_name, asset_class,
                             signal_file_path, tickers):
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET asset_class      = %s,
            execution_mode   = 'PAPER',
            status           = 'paper',
            universe_tickers = %s,
            signal_file_path = %s,
            updated_at       = NOW(),
            last_signal_at   = NOW()
        WHERE strategy_id = %s;
        """,
        (asset_class, tickers, signal_file_path, strategy_id),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO gold.strategy_registry
              (strategy_id, name, asset_class, execution_mode, status,
               universe_tickers, signal_file_path, updated_at, last_signal_at)
            VALUES (%s, %s, %s, 'PAPER', 'paper', %s, %s, NOW(), NOW());
            """,
            (strategy_id, strategy_name, asset_class, tickers, signal_file_path),
        )
    conn.commit()
    print(f"{now_hkt()} ✅ gold.strategy_registry updated for {strategy_id}")


def upsert_ticker_scores(conn, strategy_id, signal_file, generated_at, weights):
    cur = conn.cursor()
    # Stamp provenance (migration 009) when the column exists, so these
    # file-ingested rows are distinguishable from computed ones. Guarded so
    # the same code runs on a pre-009 DB (column absent → omit it, DEFAULT
    # 'computed' would apply, which is why the column check matters here).
    try:
        from quality import column_exists, SIGNAL_INGESTED
        has_src = column_exists(cur, 'gold', 'strategy_ticker_scores', 'signal_source')
    except Exception:
        has_src = False

    def crit(weight):
        return json.dumps({
            "weight": weight,
            "source_signal_file": signal_file,
            "generated_at": generated_at,
            "ingested_at": datetime.now(HKT).isoformat(),
        })

    if has_src:
        rows = [
            (strategy_id, ticker, 100.0, "BUY", weight * 100, 0.0, crit(weight),
             "PAPER", datetime.now(), datetime.now(), SIGNAL_INGESTED)
            for ticker, weight in weights.items()
        ]
        sql = """
        INSERT INTO gold.strategy_ticker_scores
          (strategy_id, ticker, score, signal_action, entry_score, exit_score,
           criteria_met, position_status, deployed_at, updated_at, signal_source)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        ON CONFLICT (strategy_id, ticker) DO UPDATE SET
          score           = EXCLUDED.score,
          signal_action   = EXCLUDED.signal_action,
          entry_score     = EXCLUDED.entry_score,
          exit_score      = EXCLUDED.exit_score,
          criteria_met    = EXCLUDED.criteria_met,
          position_status = EXCLUDED.position_status,
          updated_at      = EXCLUDED.updated_at,
          signal_source   = EXCLUDED.signal_source;
        """
    else:
        rows = [
            (strategy_id, ticker, 100.0, "BUY", weight * 100, 0.0, crit(weight),
             "PAPER", datetime.now(), datetime.now())
            for ticker, weight in weights.items()
        ]
        sql = """
        INSERT INTO gold.strategy_ticker_scores
          (strategy_id, ticker, score, signal_action, entry_score, exit_score,
           criteria_met, position_status, deployed_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        ON CONFLICT (strategy_id, ticker) DO UPDATE SET
          score           = EXCLUDED.score,
          signal_action   = EXCLUDED.signal_action,
          entry_score     = EXCLUDED.entry_score,
          exit_score      = EXCLUDED.exit_score,
          criteria_met    = EXCLUDED.criteria_met,
          position_status = EXCLUDED.position_status,
          updated_at      = EXCLUDED.updated_at;
        """
    cur.executemany(sql, rows)
    conn.commit()
    print(f"{now_hkt()} ✅ gold.strategy_ticker_scores upserted: {len(rows)} rows")


def insert_signal_logs(conn, strategy_id, signal_file, weights):
    cur = conn.cursor()
    # Idempotent: clear any previous signal-log rows for this strategy/date
    # before re-inserting from the authoritative deployed signal file.
    cur.execute(
        "DELETE FROM consumption.signal_logs WHERE strategy_id = %s AND signal_date = %s;",
        (strategy_id, date.today()),
    )
    rows = [
        (
            strategy_id, date.today(), 1, ticker, "BUY",
            f"weight={weight}; source={signal_file}",
            weight * 100,
        )
        for ticker, weight in weights.items()
    ]
    cur.executemany(
        """
        INSERT INTO consumption.signal_logs
          (strategy_id, signal_date, signal, ticker, signal_type,
           signal_criteria, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
        """,
        rows,
    )
    conn.commit()
    print(f"{now_hkt()} ✅ consumption.signal_logs inserted: {len(rows)} rows")


def record_agent_event(conn, strategy_id, strategy_name, signal_file,
                       generated_at, weights):
    cur = conn.cursor()
    payload = {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "execution_mode": "PAPER",
        "signal_file": signal_file,
        "generated_at": generated_at,
        "tickers": list(weights.keys()),
        "weights": weights,
        "ingested_at_hkt": datetime.now(HKT).isoformat(),
    }
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status,
           created_at, payload)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, NOW(), %s::jsonb);
        """,
        ("signal_ingested", strategy_id, "etl", "etl-manager",
         json.dumps(payload), "ok", json.dumps(payload)),
    )
    conn.commit()
    print(f"{now_hkt()} ✅ gold.agent_events recorded: {cur.rowcount} row(s)")


def ingest_one(conn, strategy_id, strategy_name, asset_class,
               signal_file, generated_at, weights) -> None:
    tickers = list(weights.keys())
    print(f"{now_hkt()} Ingesting {strategy_name} ({strategy_id}): {weights}")
    ensure_strategy_registry(conn, strategy_id, strategy_name, asset_class,
                             signal_file, tickers)
    upsert_ticker_scores(conn, strategy_id, signal_file, generated_at, weights)
    insert_signal_logs(conn, strategy_id, signal_file, weights)
    record_agent_event(conn, strategy_id, strategy_name, signal_file,
                       generated_at, weights)


def _ingest_all_from_file(conn, signal_file, asset_class):
    """Ingest every strategy in one signal file. Returns (n_ok, skipped)."""
    generated_at, signals = load_signal_file(signal_file)
    print(f"{now_hkt()} Loaded signal file: {signal_file} (generated {generated_at})")
    n_ok, skipped = 0, []
    for name, weights in signals.items():
        if not weights:
            skipped.append((name, "empty weights"))
            continue
        sid = resolve_strategy_id(conn, name)
        if sid is None:
            skipped.append((name, "not in gold.strategy_registry"))
            continue
        ingest_one(conn, sid, name, asset_class, signal_file, generated_at, weights)
        n_ok += 1
    return n_ok, skipped


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--signal-file", help="Path to one deployed live-signal JSON")
    src.add_argument("--signal-dir",
                     help="Directory of signal files — ingest ALL matching --signal-glob. "
                          "This is the consistent recurring path: one call replaces "
                          "the per-strategy/per-batch ingest scripts.")
    p.add_argument("--signal-glob", default="*live_signals*.json",
                   help="Filename pattern for --signal-dir (default: '*live_signals*.json'). "
                        "Keeps backtest/manifest JSONs out of the ingest.")
    p.add_argument("--strategy-id",
                   help="gold.strategy_registry.strategy_id (single-strategy mode)")
    p.add_argument("--strategy-name",
                   help="Key under the file's 'signals' object (single-strategy mode)")
    p.add_argument("--asset-class", default="US Stock",
                   help="Registry asset_class value (default: 'US Stock')")
    p.add_argument("--all", action="store_true",
                   help="Ingest every strategy in the file; ids resolved from "
                        "gold.strategy_registry by name, unknown names skipped")
    args = p.parse_args()

    conn = get_connection()
    total_ok, skipped = 0, []
    try:
        if args.signal_dir:
            import glob
            # The qr_research workspace holds backtest/manifest JSONs too, so
            # match a signal-file naming pattern rather than every *.json.
            files = sorted(glob.glob(os.path.join(args.signal_dir, args.signal_glob)))
            if not files:
                print(f"{now_hkt()} ⚠️  no files matching {args.signal_glob!r} in {args.signal_dir}")
                return 1
            print(f"{now_hkt()} Scanning {len(files)} signal file(s) in {args.signal_dir}")
            for f in files:
                # BaseException catch: load_signal_file raises SystemExit on a
                # non-signal file, which a bare `except Exception` would miss
                # and let kill the whole scan.
                try:
                    n_ok, sk = _ingest_all_from_file(conn, f, args.asset_class)
                    total_ok += n_ok
                    skipped.extend(sk)
                except BaseException as e:
                    skipped.append((os.path.basename(f), f"file error: {e}"))
        elif args.all:
            total_ok, skipped = _ingest_all_from_file(conn, args.signal_file, args.asset_class)
        else:
            if not (args.strategy_id and args.strategy_name):
                p.error("single-file mode needs --all, or both --strategy-id and --strategy-name")
            generated_at, signals = load_signal_file(args.signal_file)
            weights = signals.get(args.strategy_name) or {}
            if not weights:
                raise SystemExit(f"No {args.strategy_name!r} signals in {args.signal_file}")
            ingest_one(conn, args.strategy_id, args.strategy_name,
                       args.asset_class, args.signal_file, generated_at, weights)
            total_ok = 1
    finally:
        conn.close()

    print(f"{now_hkt()} Ingested {total_ok} strategies.")
    if skipped:
        print(f"{now_hkt()} ⚠️  skipped {len(skipped)}:")
        for name, why in skipped:
            print(f"    {name}: {why}")
    print(f"{now_hkt()} Signal pipeline ingestion complete.")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
