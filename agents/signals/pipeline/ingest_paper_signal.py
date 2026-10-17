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
    signals = data.get("signals")
    if signals is None and "selected" in data:
        # 2026-07-28 schema change: qr_research now emits per-strategy files as
        # {strategy_id, selected, cash_filter, ...} with no 'signals' key.
        # Normalise into the per-strategy signals-list shape handled below.
        sel = data.get("selected") or []
        if not sel:
            if data.get("cash_filter"):
                # Flat/all-cash signal. Matches the {'CASH': 1.0} convention
                # used by the multi-strategy files (e.g. US_STK_GOLD_HDG_05).
                signals = [{"ticker": "CASH", "weight": 1.0, "action": "BUY"}]
            else:
                raise SystemExit(
                    f"Empty 'selected' and cash_filter not set in {path}")
        elif all(isinstance(s, dict) and s.get("ticker")
                 and s.get("weight") is not None for s in sel):
            signals = sel
        else:
            raise SystemExit(
                f"'selected' entries in {path} lack ticker/weight — "
                "refusing to invent weights")
    if not signals:
        raise SystemExit(f"No 'signals' object found in {path}")
    metrics_path = path.replace("_live_signals.json", "_signal_metrics.json")
    metrics = {}
    if os.path.exists(metrics_path):
        try:
            with open(metrics_path, "r") as f:
                metrics = json.load(f)
        except Exception as e:
            print(f"{now_hkt()} ⚠️  could not load metrics file {metrics_path}: {e}", file=sys.stderr)
    return data.get("generated_at", "unknown"), signals, data, metrics


def resolve_strategy_info_by_id(conn, strategy_id: str):
    """Look up (name, asset_class) by strategy_id. Returns (None, None) if absent."""
    cur = conn.cursor()
    cur.execute(
        "SELECT name, asset_class FROM gold.strategy_registry WHERE strategy_id = %s",
        (strategy_id,),
    )
    row = cur.fetchone()
    return row if row else (None, None)


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
    # If caller didn't override asset_class, preserve the registry's value.
    if asset_class is None:
        cur.execute(
            "SELECT asset_class FROM gold.strategy_registry WHERE strategy_id = %s",
            (strategy_id,),
        )
        row = cur.fetchone()
        asset_class = row[0] if row and row[0] else "US Stock"
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET asset_class      = COALESCE(%s, asset_class),
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
            (strategy_id, strategy_name, asset_class or "US Stock", tickers, signal_file_path),
        )
    conn.commit()
    print(f"{now_hkt()} ✅ gold.strategy_registry updated for {strategy_id}")


def upsert_ticker_scores(conn, strategy_id, signal_file, generated_at, weights, metrics=None):
    metrics = metrics or {}
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

    # 2026-10-17: persist the signal file's own compute time as computed_at
    # (freshness checks read COALESCE(computed_at, updated_at)). generated_at
    # is an ISO string like "2026-08-05T00:00:00Z"; unparseable -> NULL.
    computed_at = None
    try:
        if generated_at and generated_at != "unknown":
            computed_at = datetime.fromisoformat(
                str(generated_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        computed_at = None

    def crit(weight, ticker):
        base = {
            "weight": weight,
            "source_signal_file": signal_file,
            "generated_at": generated_at,
            "ingested_at": datetime.now(HKT).isoformat(),
        }
        meta = metrics.get(ticker)
        if meta and isinstance(meta, dict):
            base.update({
                "risk_adj_momentum_12m": meta.get("risk_adj_momentum"),
                "total_return_12m": meta.get("total_return_12m"),
                "ann_vol_12m": meta.get("ann_vol_12m"),
                "selected": meta.get("selected"),
            })
        return json.dumps(base)

    def score_row(ticker, weight):
        entry_score = round(float(weight) * 100, 4)
        # Consistent with build_strategy_scores.py semantics: score = entry_score,
        # action is BUY only when the ticker has positive target weight.
        score = entry_score if entry_score > 0 else 0.0
        action = "BUY" if entry_score > 0 else "HOLD"
        return score, action, entry_score

    # t_82a67ac5: continuous 0-100 signal strength = midpoint percentile of the
    # file's target weights across its tickers. The signal files carry weights,
    # not rank metrics, so weight rank is the honest continuous proxy available
    # at ingest time. score/entry_score keep their weight*100 semantics
    # (rebalancer contract) — strength is additive.
    def weight_strengths(w):
        items = sorted(((t, float(x)) for t, x in w.items()), key=lambda kv: (-kv[1], kv[0]))
        n = len(items)
        out = {}
        i = 0
        while i < n:
            j = i
            while j + 1 < n and items[j + 1][1] == items[i][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            s = round(100.0 * (n - avg_rank + 0.5) / n, 2)
            for k in range(i, j + 1):
                out[items[k][0]] = s
            i = j + 1
        return out

    strengths = weight_strengths(weights)

    if has_src:
        rows = []
        for ticker, weight in weights.items():
            score, action, entry_score = score_row(ticker, weight)
            rows.append(
                (strategy_id, ticker, score, action, entry_score, 0.0, crit(weight, ticker),
                 "PAPER", datetime.now(), datetime.now(), SIGNAL_INGESTED,
                 strengths.get(ticker), computed_at)
            )
        sql = """
        INSERT INTO gold.strategy_ticker_scores
          (strategy_id, ticker, score, signal_action, entry_score, exit_score,
           criteria_met, position_status, deployed_at, updated_at, signal_source,
           signal_strength, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (strategy_id, ticker) DO UPDATE SET
          score           = EXCLUDED.score,
          signal_action   = EXCLUDED.signal_action,
          entry_score     = EXCLUDED.entry_score,
          exit_score      = EXCLUDED.exit_score,
          criteria_met    = EXCLUDED.criteria_met,
          position_status = EXCLUDED.position_status,
          updated_at      = EXCLUDED.updated_at,
          signal_source   = EXCLUDED.signal_source,
          signal_strength = EXCLUDED.signal_strength,
          computed_at     = EXCLUDED.computed_at;
        """
    else:
        rows = []
        for ticker, weight in weights.items():
            score, action, entry_score = score_row(ticker, weight)
            rows.append(
                (strategy_id, ticker, score, action, entry_score, 0.0, crit(weight, ticker),
                 "PAPER", datetime.now(), datetime.now(), strengths.get(ticker), computed_at)
            )
        sql = """
        INSERT INTO gold.strategy_ticker_scores
          (strategy_id, ticker, score, signal_action, entry_score, exit_score,
           criteria_met, position_status, deployed_at, updated_at, signal_strength,
           computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
        ON CONFLICT (strategy_id, ticker) DO UPDATE SET
          score           = EXCLUDED.score,
          signal_action   = EXCLUDED.signal_action,
          entry_score     = EXCLUDED.entry_score,
          exit_score      = EXCLUDED.exit_score,
          criteria_met    = EXCLUDED.criteria_met,
          position_status = EXCLUDED.position_status,
          signal_strength = EXCLUDED.signal_strength,
          computed_at     = EXCLUDED.computed_at,
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
    rows = []
    for ticker, weight in weights.items():
        confidence = round(float(weight) * 100, 4)
        signal_type = "BUY" if confidence > 0 else "HOLD"
        rows.append(
            (strategy_id, date.today(), 1, ticker, signal_type,
             f"weight={weight}; source={signal_file}", confidence)
        )
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


def is_strategy_ingest_enabled(conn, strategy_id):
    """Return True only if the registry row expects ingested signals and is active."""
    cur = conn.cursor()
    cur.execute(
        "SELECT status, signal_mechanism, disable_paper_rebuild "
        "FROM gold.strategy_registry WHERE strategy_id = %s",
        (strategy_id,),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return False, "not in gold.strategy_registry"
    status, mechanism, disabled = row
    if status != "paper":
        return False, f"registry status is {status}"
    if mechanism != "ingested":
        return False, f"signal_mechanism is {mechanism}"
    if disabled:
        return False, "disable_paper_rebuild is TRUE"
    return True, None


def ingest_one(conn, strategy_id, strategy_name, asset_class,
               signal_file, generated_at, weights, metrics=None) -> None:
    enabled, reason = is_strategy_ingest_enabled(conn, strategy_id)
    if not enabled:
        print(f"{now_hkt()} ⏸️  Skipping {strategy_id}: {reason}")
        return
    tickers = list(weights.keys())
    print(f"{now_hkt()} Ingesting {strategy_name} ({strategy_id}): {weights}")
    ensure_strategy_registry(conn, strategy_id, strategy_name, asset_class,
                             signal_file, tickers)
    upsert_ticker_scores(conn, strategy_id, signal_file, generated_at, weights, metrics)
    insert_signal_logs(conn, strategy_id, signal_file, weights)
    record_agent_event(conn, strategy_id, strategy_name, signal_file,
                       generated_at, weights)


def _ingest_all_from_file(conn, signal_file, asset_class):
    """Ingest every strategy in one signal file. Returns (n_ok, skipped)."""
    generated_at, signals, data, metrics = load_signal_file(signal_file)
    print(f"{now_hkt()} Loaded signal file: {signal_file} (generated {generated_at})")
    n_ok, skipped = 0, []
    basename = os.path.basename(signal_file)

    # Per-strategy file: signals is a list of {"ticker", "action", "weight"} objects.
    if isinstance(signals, list):
        sid = data.get("strategy_id")
        if not sid:
            skipped.append((basename, "signals is list but no top-level strategy_id"))
            return n_ok, skipped
        name, reg_asset_class = resolve_strategy_info_by_id(conn, sid)
        if name is None:
            skipped.append((basename, f"strategy_id {sid} not in gold.strategy_registry"))
            return n_ok, skipped
        weights = {}
        for entry in signals:
            if not isinstance(entry, dict):
                continue
            ticker = entry.get("ticker")
            weight = entry.get("weight")
            action = entry.get("action", "BUY")
            if ticker is None or weight is None:
                continue
            # Exclude explicit exits and zero-weight HOLD placeholders.
            if action in ("SELL", "EXIT"):
                continue
            if action == "HOLD" and weight == 0:
                continue
            weights[ticker] = float(weight)
        if not weights:
            skipped.append((basename, "empty weights"))
            return n_ok, skipped
        ingest_one(conn, sid, name, reg_asset_class or asset_class,
                   signal_file, generated_at, weights, metrics)
        n_ok += 1
        return n_ok, skipped

    # Multi-strategy file: signals is a dict keyed by strategy name.
    for name, weights in signals.items():
        if not weights:
            skipped.append((name, "empty weights"))
            continue
        sid = resolve_strategy_id(conn, name)
        if sid is None:
            skipped.append((name, "not in gold.strategy_registry"))
            continue
        ingest_one(conn, sid, name, asset_class, signal_file, generated_at, weights, metrics)
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
    p.add_argument("--signal-glob", default="*_live_signals.json",
                   help="Filename pattern for --signal-dir (default: '*_live_signals.json'). "
                        "Only matches per-strategy files ending in _live_signals.json.")
    p.add_argument("--strategy-id",
                   help="gold.strategy_registry.strategy_id (single-strategy mode)")
    p.add_argument("--strategy-name",
                   help="Key under the file's 'signals' object (single-strategy mode)")
    p.add_argument("--asset-class", default=None,
                   help="Override registry asset_class value (default: preserve registry value)")
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
                # No deployed signal files today is a NO-OP, not a failure:
                # 'ingested' strategies receive files event-driven (monthly /
                # WRITE_SIGNAL handoff), so most days the dir legitimately has
                # nothing. Hard-failing here turned the whole signal cycle RED
                # every no-signal day (2026-08-05 cron). Real file/parse errors
                # still hard-fail via the `skipped` list below.
                print(f"{now_hkt()} ℹ️  no files matching {args.signal_glob!r} in {args.signal_dir} — nothing to ingest (no-op)")
                return 0
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
            generated_at, signals, _, metrics = load_signal_file(args.signal_file)
            weights = signals.get(args.strategy_name) or {}
            if not weights:
                raise SystemExit(f"No {args.strategy_name!r} signals in {args.signal_file}")
            ingest_one(conn, args.strategy_id, args.strategy_name,
                       args.asset_class, args.signal_file, generated_at, weights, metrics)
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
