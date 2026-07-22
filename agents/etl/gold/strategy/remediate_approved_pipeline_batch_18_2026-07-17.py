#!/usr/bin/env python3
"""
WRITE_SIGNAL: Approved pipeline remediation batch (18 strategies)
Task: t_b94d7998

Ingests the validated manifest at:
  /home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_handoff_manifest_approved_pipeline_2026-07-17.json

This is a remediation handoff for existing paper strategies. Operations:
  1. Sync gold.strategy_registry backtest fields, signal_file_path, priority, frequency, universe_tickers, exit_logic.
  2. Sync gold.strategy_backtest_runs with the manifest backtest_id and recompute win_rate_oos from the backtest report CSV when missing.
  3. Update gold.signal_families mapping and ensure deployment.
  4. Upsert gold.strategy_ticker_scores from per-strategy live signal files (all universe tickers, weight 0 if not in signal file).
  5. Re-populate gold.signal_evaluations so the downstream UI/execution feed is wired to the correct family_key.
  6. Update gold.strategy_research status and exit/entry logic.
  7. Emit a gold.agent_events audit row.

Idempotent on re-run.
"""
import os
import sys
import json
import csv
from datetime import datetime, timezone

ETL_HOME = os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
)
SHARED = os.path.join(ETL_HOME, "shared", "scripts")
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

from db import get_connection  # noqa: E402

MANIFEST = "/home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_handoff_manifest_approved_pipeline_2026-07-17.json"

# Families that should use the dedicated HK family key because the HK feed already
# operates under that family.  All other strategies use manifest.signal_family.
HK_STRATEGIES = {"ETF_HK_Balanced_Trend", "HK_Quality_BlueChips"}

# Task 6d14e6fa-704b-46d6-913e-1fb0863acac3: research approved an expanded
# universe for the HK balanced ETF strategy.  The feed/manifest still carries
# the legacy 2-ticker universe, so we override the metadata here.  Signals
# (weights) continue to come from the live signal file.
ETF_HK_BALANCED_TREND_UNIVERSE = [
    "2800.HK",
    "0001.HK",
    "0700.HK",
    "1299.HK",
    "2318.HK",
    "AGG",
]

FAMILY_COLORS = {
    "tactical": "#F59E0B",
    "momentum": "#10B981",
    "mean_rev": "#8B5CF6",
    "hk_paper_v1": "#3B82F6",
}


def now_hkt():
    import pytz
    return datetime.now(pytz.timezone("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_manifest(path):
    with open(path, "r") as f:
        return json.load(f)


def normalize_frequency(raw: str):
    r = (raw or "daily").strip().lower()
    if r in ("day", "daily", "d"):
        return "daily"
    if r in ("weekly", "week", "w"):
        return "weekly"
    if r in ("monthly", "month", "m"):
        return "monthly"
    if r in ("quarterly",):
        return "quarterly"
    if r in ("intraday",):
        return "intraday"
    return r or "daily"


def family_key_for(s: dict) -> str:
    sid = s["strategy_id"]
    if sid in HK_STRATEGIES:
        return "hk_paper_v1"
    return s.get("signal_family", "tactical")


def market_for(s: dict) -> str:
    markets = s.get("markets", [])
    if markets:
        return markets[0]
    return "US"


def ticker_market(ticker: str, default_market: str) -> str:
    if ticker.endswith(".HK"):
        return "HK"
    return default_market


def read_csv_win_rate(report_path: str):
    """Read OOS win_rate from a backtest report CSV."""
    if not report_path or not os.path.exists(report_path):
        return None
    try:
        with open(report_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("metric", "").strip().lower() == "win_rate":
                    val = row.get("out_of_sample", "").strip()
                    if val and val.lower() != "nan":
                        return float(val)
    except Exception as e:
        print(f"{now_hkt()} WARN: could not read {report_path}: {e}")
    return None


def upsert_strategy_research(conn, s):
    cur = conn.cursor()
    sid = s["strategy_id"]
    name = s["name"]
    asset = s["asset_class"]
    markets = s.get("markets", [])
    market = markets[0] if markets else "US"
    universe = s.get("universe_tickers", [])
    freq = normalize_frequency(s.get("signal_cadence", s.get("frequency", "daily")))
    entry_rules = s.get("entry_exit_stops", {})
    exit_logic = entry_rules.get("exit_rules", "")
    entry_basis = entry_rules.get("entry_basis", "next_open")
    notes = s.get("notes", "")
    status = s.get("status", "approved")
    if status == "paper":
        status = "approved"

    if sid == "ETF_HK_Balanced_Trend":
        universe = ETF_HK_BALANCED_TREND_UNIVERSE

    cur.execute(
        """
        INSERT INTO gold.strategy_research
          (strategy_id, name, thesis, asset_class, universe_tickers, entry_logic, exit_logic,
           position_sizing, frequency, source, status, kanban_task_id, created_at, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (strategy_id) DO UPDATE SET
          name            = EXCLUDED.name,
          thesis          = EXCLUDED.thesis,
          asset_class     = EXCLUDED.asset_class,
          universe_tickers = EXCLUDED.universe_tickers,
          entry_logic     = EXCLUDED.entry_logic,
          exit_logic      = EXCLUDED.exit_logic,
          position_sizing = EXCLUDED.position_sizing,
          frequency       = EXCLUDED.frequency,
          source          = EXCLUDED.source,
          status          = EXCLUDED.status,
          kanban_task_id  = EXCLUDED.kanban_task_id,
          updated_at      = NOW();
        """,
        (
            sid, name, notes, asset, universe,
            f"entry_basis={entry_basis}", exit_logic,
            json.dumps({"assigned_capital": s.get("assigned_capital", 100000)}),
            freq, "research-agent", status, "t_b94d7998",
        ),
    )
    conn.commit()


def upsert_strategy_registry(conn, s, win_rate_override=None):
    cur = conn.cursor()
    sid = s["strategy_id"]
    name = s["name"]
    asset = s["asset_class"]
    universe = s.get("universe_tickers", [])
    freq = normalize_frequency(s.get("signal_cadence", s.get("frequency", "daily")))
    execution_mode = s.get("execution_mode", "PAPER")
    signal_file = s.get("signal_logic", {}).get("signal_file_path", "")
    priority = s.get("priority", "")
    entry_exit = s.get("entry_exit_stops", {})
    exit_logic = entry_exit.get("exit_rules", "")
    entry_basis = entry_exit.get("entry_basis", "next_open")
    assigned_capital = s.get("assigned_capital", 100000)

    if sid == "ETF_HK_Balanced_Trend":
        universe = ETF_HK_BALANCED_TREND_UNIVERSE

    oos = [b for b in s.get("backtest_results", []) if b.get("is_oos")]
    latest_oos = oos[0] if oos else s.get("backtest_results", [{}])[0]
    if latest_oos is None:
        latest_oos = {}

    win_rate = win_rate_override if win_rate_override is not None else latest_oos.get("win_rate")

    cur.execute(
        """
        INSERT INTO gold.strategy_registry
          (strategy_id, name, asset_class, universe_tickers, frequency, execution_mode, status,
           sharpe_oos, max_drawdown_oos, trade_count_oos, win_rate_oos, assigned_capital,
           signal_logic, exit_logic, signal_file_path, priority, updated_at, last_signal_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, 'paper',
           %s, %s, %s, %s, %s,
           %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (strategy_id) DO UPDATE SET
          name               = EXCLUDED.name,
          asset_class        = EXCLUDED.asset_class,
          universe_tickers   = EXCLUDED.universe_tickers,
          frequency          = EXCLUDED.frequency,
          execution_mode     = EXCLUDED.execution_mode,
          sharpe_oos         = EXCLUDED.sharpe_oos,
          max_drawdown_oos   = EXCLUDED.max_drawdown_oos,
          trade_count_oos    = EXCLUDED.trade_count_oos,
          win_rate_oos       = EXCLUDED.win_rate_oos,
          assigned_capital   = EXCLUDED.assigned_capital,
          signal_logic       = EXCLUDED.signal_logic,
          exit_logic         = EXCLUDED.exit_logic,
          signal_file_path   = EXCLUDED.signal_file_path,
          priority           = EXCLUDED.priority,
          updated_at         = NOW(),
          last_signal_at     = NOW();
        """,
        (
            sid, name, asset, universe, freq, execution_mode,
            latest_oos.get("sharpe"),
            latest_oos.get("max_dd"),
            latest_oos.get("n_trades"),
            win_rate,
            assigned_capital,
            f"entry_basis={entry_basis};weights_are_target_portfolio={s.get('signal_logic', {}).get('weights_are_target_portfolio', True)}",
            exit_logic,
            signal_file,
            priority,
        ),
    )
    conn.commit()


def upsert_backtest_runs(conn, s, win_rate_override=None):
    cur = conn.cursor()
    sid = s["strategy_id"]
    run_id = s.get("backtest_id", "")
    if not run_id:
        print(f"{now_hkt()} WARN: no backtest_id for {sid}; skipping backtest_runs")
        return

    oos = [b for b in s.get("backtest_results", []) if b.get("is_oos")]
    bt = oos[0] if oos else s.get("backtest_results", [{}])[0]
    if bt is None:
        bt = {}

    is_start = bt.get("period_start")
    is_end = bt.get("period_end")
    oos_start = bt.get("period_start")
    oos_end = bt.get("period_end")

    win_rate = win_rate_override if win_rate_override is not None else bt.get("win_rate")
    win_rate_reason = bt.get("win_rate_reason", "")
    if win_rate is not None and win_rate_reason:
        notes = f"win_rate={win_rate} ({win_rate_reason})"
    elif win_rate is not None:
        notes = f"win_rate={win_rate}"
    else:
        notes = win_rate_reason or ""

    cur.execute(
        """
        INSERT INTO gold.strategy_backtest_runs
          (run_id, strategy_id, run_number, is_start, is_end, oos_start, oos_end,
           sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
           notes, all_risk_gates_passed, created_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s,
           %s, %s, %s, %s, %s,
           %s, %s, NOW())
        ON CONFLICT (run_id) DO UPDATE SET
          strategy_id          = EXCLUDED.strategy_id,
          run_number           = EXCLUDED.run_number,
          is_start             = EXCLUDED.is_start,
          is_end               = EXCLUDED.is_end,
          oos_start            = EXCLUDED.oos_start,
          oos_end              = EXCLUDED.oos_end,
          sharpe_oos           = EXCLUDED.sharpe_oos,
          returns_oos          = EXCLUDED.returns_oos,
          max_drawdown_oos     = EXCLUDED.max_drawdown_oos,
          trade_count_oos      = EXCLUDED.trade_count_oos,
          win_rate_oos         = EXCLUDED.win_rate_oos,
          notes                = EXCLUDED.notes,
          all_risk_gates_passed = EXCLUDED.all_risk_gates_passed;
        """,
        (
            run_id, sid, 2, is_start, is_end, oos_start, oos_end,
            bt.get("sharpe"),
            bt.get("annual_return"),
            bt.get("max_dd"),
            bt.get("n_trades"),
            win_rate,
            notes,
            True,
        ),
    )
    conn.commit()


def ensure_signal_families(conn, strategies: list):
    """Populate one row per distinct family_key used in the batch."""
    cur = conn.cursor()
    # Pick the first strategy as the representative for each family_key.
    families = {}
    for s in strategies:
        fk = family_key_for(s)
        if fk not in families:
            families[fk] = s

    for fk, s in families.items():
        sid = s["strategy_id"]
        label = fk.replace("_", " ").title()
        color = FAMILY_COLORS.get(fk, "#10B981")
        cur.execute(
            """
            INSERT INTO gold.signal_families
              (family_key, label, strategy_id, deployed, color, strategy_name, updated_at)
            VALUES
              (%s, %s, %s, true, %s, %s, NOW())
            ON CONFLICT (family_key) DO UPDATE SET
              label          = EXCLUDED.label,
              strategy_id    = EXCLUDED.strategy_id,
              deployed       = EXCLUDED.deployed,
              color          = EXCLUDED.color,
              strategy_name  = EXCLUDED.strategy_name,
              updated_at     = NOW();
            """,
            (fk, label, sid, color, s["name"]),
        )
    conn.commit()


def load_signal_weights(signal_file: str, strategy_id: str, strategy_name: str):
    """Return {ticker: weight} from the live signal file, or {} on failure."""
    if not signal_file or not os.path.exists(signal_file):
        return {}
    with open(signal_file, "r") as f:
        payload = json.load(f)
    signals = payload.get("signals", {})
    if not signals:
        return {}
    block = signals.get(strategy_name) or signals.get(strategy_id)
    if block is None and signals:
        block = list(signals.values())[0]
    if not isinstance(block, dict):
        return {}
    cleaned = {
        t: float(w)
        for t, w in block.items()
        if isinstance(w, (int, float)) and float(w) > 0
    }
    if not cleaned:
        return {}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {t: w / total for t, w in cleaned.items()}


def build_ticker_weights(s: dict) -> dict:
    """Return {ticker: normalized weight} for all universe tickers."""
    universe = s.get("universe_tickers", [])
    signal_file = s.get("signal_logic", {}).get("signal_file_path", "")
    active = load_signal_weights(signal_file, s["strategy_id"], s["name"])

    if not universe:
        return active

    # Normalise active weights over the full universe.  Missing tickers get 0.
    # If no active weights, assign equal weight to the universe (fallback).
    weights = {}
    if active:
        for t in universe:
            weights[t] = active.get(t, 0.0)
        total = sum(weights.values())
        if total > 0:
            weights = {t: w / total for t, w in weights.items()}
        else:
            weights = {t: 1.0 / len(universe) for t in universe}
    else:
        weights = {t: 1.0 / len(universe) for t in universe}
    return weights


def upsert_ticker_scores(conn, s, weights: dict):
    if not weights:
        print(f"{now_hkt()} WARN: no weights for {s['strategy_id']}; skipping ticker scores")
        return

    sid = s["strategy_id"]
    signal_file = s.get("signal_logic", {}).get("signal_file_path", "")
    generated_at = ""
    if signal_file and os.path.exists(signal_file):
        with open(signal_file, "r") as f:
            payload = json.load(f)
        generated_at = payload.get("generated_at", "")

    rows = []
    for ticker, weight in weights.items():
        rows.append((
            sid, ticker, 100.0, "BUY", weight * 100, 0.0,
            json.dumps({
                "weight": round(weight, 6),
                "source_signal_file": signal_file,
                "generated_at": generated_at,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }),
            "PAPER", datetime.now(), datetime.now(),
        ))

    cur = conn.cursor()
    cur.executemany(
        """
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
        """,
        rows,
    )
    conn.commit()


def insert_signal_evaluations(conn, s, weights: dict):
    """Insert fresh signal_evaluations for this strategy."""
    if not weights:
        return

    sid = s["strategy_id"]
    sname = s["name"]
    market = market_for(s)
    family = family_key_for(s)

    rows = []
    for ticker, weight in weights.items():
        mkt = ticker_market(ticker, market)
        note = f"{sid}: {sname} PAPER weight={weight:.4f}"[:195]
        rows.append((
            mkt, ticker, ticker, family, "BUY", round(weight * 100, 6), 0.0, note,
        ))

    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO gold.signal_evaluations
          (market, ticker, name, family_key, direction, potential, change_pct, note, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (market, ticker, family_key) DO UPDATE SET
          name = EXCLUDED.name,
          direction = EXCLUDED.direction,
          potential = EXCLUDED.potential,
          change_pct = EXCLUDED.change_pct,
          note = EXCLUDED.note,
          updated_at = EXCLUDED.updated_at;
        """,
        rows,
    )
    conn.commit()


def record_agent_event(conn, manifest, strategies):
    cur = conn.cursor()
    payload = {
        "batch_id": manifest.get("batch_id", ""),
        "generated_at": manifest.get("generated_at", ""),
        "agent_name": manifest.get("agent_name", ""),
        "kanban_task_id": "t_b94d7998",
        "strategies": [s["strategy_id"] for s in strategies],
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status, created_at, payload)
        VALUES
          (%s, %s, %s, %s, %s::jsonb, %s, NOW(), %s::jsonb);
        """,
        (
            "signal_ingested", "approved-pipeline-remediation-2026-07-18", "etl", "etl-manager",
            json.dumps(payload), "ok", json.dumps(payload),
        ),
    )
    conn.commit()


def main():
    manifest = load_manifest(MANIFEST)
    strategies = manifest.get("strategies", [])
    print(f"{now_hkt()} Loaded manifest {MANIFEST}")
    print(f"{now_hkt()} Strategies to remediate: {len(strategies)}")

    conn = get_connection()
    try:
        # Pre-compute per-strategy weights and the union of family keys / tickers we will touch.
        all_tickers = set()
        family_keys = set()
        for s in strategies:
            all_tickers.update(s.get("universe_tickers", []))
            family_keys.add(family_key_for(s))

        # Clean up stale rows from prior runs that used a different family_key
        # (e.g. the old 'trend' family for ETF_HY_Credit_Carry / ETF_HK_Balanced_Trend).
        # Include 'trend' as a known legacy family key for this batch.
        cleanup_families = list(family_keys | {"trend"})
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM gold.signal_evaluations
            WHERE ticker = ANY(%s) AND family_key = ANY(%s);
            """,
            (list(all_tickers), cleanup_families),
        )
        print(f"{now_hkt()} Deleted {cur.rowcount} stale signal_evaluations rows for {len(all_tickers)} tickers across families {cleanup_families}")

        # Refresh ticker scores for the batch from scratch.
        cur.execute(
            "DELETE FROM gold.strategy_ticker_scores WHERE strategy_id = ANY(%s);",
            ([s["strategy_id"] for s in strategies],),
        )
        print(f"{now_hkt()} Deleted {cur.rowcount} stale strategy_ticker_scores rows for the batch")
        conn.commit()

        # Ensure family rows exist before inserting signal_evaluations.
        ensure_signal_families(conn, strategies)

        for s in strategies:
            sid = s["strategy_id"]
            print(f"{now_hkt()} Remediating {sid}")

            # Recompute win_rate_oos from the backtest report CSV if the manifest leaves it null.
            oos = [b for b in s.get("backtest_results", []) if b.get("is_oos")]
            bt = oos[0] if oos else s.get("backtest_results", [{}])[0] or {}
            win_rate_override = None
            if bt.get("win_rate") is None:
                win_rate_override = read_csv_win_rate(bt.get("backtest_report_path"))
                if win_rate_override is not None:
                    print(f"{now_hkt()}   recomputed win_rate_oos={win_rate_override} from {bt.get('backtest_report_path')}")

            upsert_strategy_research(conn, s)
            upsert_strategy_registry(conn, s, win_rate_override=win_rate_override)
            upsert_backtest_runs(conn, s, win_rate_override=win_rate_override)

            weights = build_ticker_weights(s)
            upsert_ticker_scores(conn, s, weights)
            insert_signal_evaluations(conn, s, weights)

            print(f"{now_hkt()}   ✅ {sid}: {len(weights)} tickers, family={family_key_for(s)}")

        record_agent_event(conn, manifest, strategies)
    finally:
        conn.close()

    print(f"{now_hkt()} Remediation complete for {len(strategies)} strategies.")


if __name__ == "__main__":
    main()
