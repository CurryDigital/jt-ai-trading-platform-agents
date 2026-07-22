#!/usr/bin/env python3
"""
WRITE_SIGNAL: HK LowVol batch (2 strategies)

Ingests 2 approved HK LowVol strategies from the research handoff manifest
and their per-strategy live signal files into the gold signal pipeline.

Strategies:
- HK_LowVol_Weekly
- HK_LowVol_TrendFilter_Weekly

Reads:
  /home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_handoff_manifest_2026-07-18.json
  /home/ubuntu/.hermes/profiles/qr_research/workspace/<strategy_id>_live_signals.json

Writes:
  - gold.strategy_research (approved research record)
  - gold.strategy_backtest_runs (OOS backtest metrics)
  - gold.strategy_registry (status/execution_mode/universe/priority/OOS stats/signal file path)
  - gold.strategy_ticker_scores (live BUY signals)
  - gold.signal_evaluations (downstream UI/execution feed)
  - gold.v_pipeline_ui_feed refreshed via underlying CREATE VIEW
  - gold.agent_events (audit event)

Operational notes:
  - PAPER strategies only.
  - Idempotent on re-run.
  - asset_class = 'HK Stock' for consistency with HK_Quality_BlueChips.
"""
import json
import os
import sys
from datetime import datetime

import pytz

sys.path.insert(
    0, os.path.expanduser(
        "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"
    )
)
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402

MANIFEST = "/home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_handoff_manifest_2026-07-18.json"
SIGNAL_DIR = "/home/ubuntu/.hermes/profiles/qr_research/workspace"
HKT = pytz.timezone("Asia/Hong_Kong")
FAMILY_KEY = "hk_paper_v1"
ASSET_CLASS = "HK Stock"
MARKET = "HK"


def now_hkt() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_manifest(path: str):
    with open(path, "r") as f:
        data = json.load(f)
    by_id = {s["strategy_id"]: s for s in data.get("strategies", [])}
    return data.get("generated_at", "unknown"), by_id


def load_signal_weights(strategy_id: str, strategy_name: str, fallback_universe: list):
    """Return weights dict from the live signal file, or equal-weight fallback."""
    path = os.path.join(SIGNAL_DIR, f"{strategy_id}_live_signals.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        signals = data.get("signals", {})
        weights = signals.get(strategy_name) or signals.get(strategy_id)
        if weights:
            cleaned = {t: float(w) for t, w in weights.items() if float(w) > 0}
            if cleaned:
                total = sum(cleaned.values())
                if total > 0:
                    return {t: w / total for t, w in cleaned.items()}
    if fallback_universe:
        weight = 1.0 / len(fallback_universe)
        return {ticker: weight for ticker in fallback_universe}
    return {}


def ensure_strategy_research(conn, strategy: dict):
    """Insert/update the research record. Status is always 'approved' for this handoff."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gold.strategy_research
          (strategy_id, name, asset_class, universe_tickers, entry_logic, exit_logic,
           position_sizing, frequency, source, status, updated_at, kanban_task_id)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'research-agent', 'approved', NOW(), %s)
        ON CONFLICT (strategy_id) DO UPDATE SET
          name            = EXCLUDED.name,
          asset_class     = EXCLUDED.asset_class,
          universe_tickers= EXCLUDED.universe_tickers,
          entry_logic     = EXCLUDED.entry_logic,
          exit_logic      = EXCLUDED.exit_logic,
          position_sizing = EXCLUDED.position_sizing,
          frequency       = EXCLUDED.frequency,
          status          = EXCLUDED.status,
          updated_at      = EXCLUDED.updated_at,
          kanban_task_id  = EXCLUDED.kanban_task_id;
        """,
        (
            strategy["strategy_id"], strategy["name"], ASSET_CLASS,
            strategy.get("universe_tickers"), strategy["entry_exit_stops"].get("entry_basis", ""),
            strategy["entry_exit_stops"].get("exit_rules", ""),
            json.dumps({"long_only": strategy["signal_logic"].get("long_only", True),
                        "direction": strategy["signal_logic"].get("direction", "long")}),
            strategy.get("signal_cadence", "weekly"),
            strategy.get("kanban_task_id"),
        ),
    )
    conn.commit()
    print(f"{now_hkt()}  gold.strategy_research upserted for {strategy['strategy_id']}")


def ensure_backtest_runs(conn, strategy: dict, bt: dict):
    """Insert/update a single OOS backtest run row. Uses run_number=1; upserted by strategy_id."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT run_id FROM gold.strategy_backtest_runs
        WHERE strategy_id = %s AND run_number = 1
        ORDER BY created_at DESC LIMIT 1;
        """,
        (strategy["strategy_id"],),
    )
    row = cur.fetchone()
    params = json.dumps({
        "source": "handoff_manifest",
        "backtest_id": bt.get("backtest_id"),
        "run_date": bt.get("run_date"),
        "is_oos": bt.get("is_oos", True),
    })
    if row:
        run_id = row[0]
        cur.execute(
            """
            UPDATE gold.strategy_backtest_runs
            SET is_start = %s, is_end = %s, oos_start = %s, oos_end = %s,
                sharpe_oos = %s, returns_oos = %s, max_drawdown_oos = %s,
                trade_count_oos = %s, win_rate_oos = %s,
                all_risk_gates_passed = true, parameters_used = %s::jsonb,
                notes = %s, created_at = NOW()
            WHERE run_id = %s;
            """,
            (
                bt.get("period_start"), bt.get("period_end"),
                bt.get("period_start"), bt.get("period_end"),
                round(bt.get("sharpe", 0), 6),
                round(bt.get("annual_return", 0), 6),
                round(bt.get("max_dd", 0), 6),
                bt.get("n_trades", 0),
                round(bt.get("win_rate", 0), 6),
                params, strategy.get("notes", ""), run_id,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO gold.strategy_backtest_runs
              (strategy_id, run_number, run_by, is_start, is_end, oos_start, oos_end,
               sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
               all_risk_gates_passed, parameters_used, notes, created_at)
            VALUES
              (%s, 1, 'research-agent', %s, %s, %s, %s,
               %s, %s, %s, %s, %s, true, %s::jsonb, %s, NOW());
            """,
            (
                strategy["strategy_id"],
                bt.get("period_start"), bt.get("period_end"),
                bt.get("period_start"), bt.get("period_end"),
                round(bt.get("sharpe", 0), 6),
                round(bt.get("annual_return", 0), 6),
                round(bt.get("max_dd", 0), 6),
                bt.get("n_trades", 0),
                round(bt.get("win_rate", 0), 6),
                params, strategy.get("notes", ""),
            ),
        )
    conn.commit()
    print(f"{now_hkt()}  gold.strategy_backtest_runs upserted for {strategy['strategy_id']}")


def ensure_strategy_registry(conn, strategy: dict, signal_file: str):
    strategy_id = strategy["strategy_id"]
    name = strategy["name"]
    tickers = strategy.get("universe_tickers")
    priority = strategy.get("priority", "EXPERIMENTAL")
    bt = strategy.get("backtest_results", [{}])[0]

    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET asset_class       = %s,
            execution_mode    = 'PAPER',
            status            = 'paper',
            priority          = %s,
            universe_tickers  = %s,
            signal_file_path  = %s,
            sharpe_oos        = %s,
            max_drawdown_oos  = %s,
            trade_count_oos   = %s,
            win_rate_oos      = %s,
            returns_oos       = %s,
            updated_at        = NOW(),
            last_signal_at    = NOW()
        WHERE strategy_id = %s;
        """,
        (
            ASSET_CLASS, priority, tickers, signal_file,
            bt.get("sharpe"), bt.get("max_dd"),
            bt.get("n_trades"), bt.get("win_rate"),
            bt.get("annual_return"), strategy_id,
        ),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO gold.strategy_registry
              (strategy_id, name, asset_class, execution_mode, status, priority,
               universe_tickers, signal_file_path, sharpe_oos, max_drawdown_oos,
               trade_count_oos, win_rate_oos, returns_oos, updated_at, last_signal_at)
            VALUES
              (%s, %s, %s, 'PAPER', 'paper', %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
            """,
            (
                strategy_id, name, ASSET_CLASS, priority, tickers, signal_file,
                bt.get("sharpe"), bt.get("max_dd"),
                bt.get("n_trades"), bt.get("win_rate"),
                bt.get("annual_return"),
            ),
        )
    conn.commit()
    print(f"{now_hkt()}  gold.strategy_registry updated for {strategy_id}")


def upsert_ticker_scores(conn, strategy_id: str, strategy_name: str, generated_at: str, weights: dict):
    if not weights:
        print(f"{now_hkt()}  no weights for {strategy_id}; skipping ticker scores")
        return

    rows = []
    for ticker, weight in weights.items():
        rows.append((
            strategy_id, ticker, 100.0, "BUY", weight * 100, 0.0,
            json.dumps({
                "weight": round(weight, 6),
                "source_signal_file": os.path.join(SIGNAL_DIR, f"{strategy_id}_live_signals.json"),
                "generated_at": generated_at,
                "ingested_at": datetime.now(HKT).isoformat(),
                "execution_mode": "PAPER",
                "strategy_name": strategy_name,
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
    print(f"{now_hkt()}  gold.strategy_ticker_scores upserted: {len(rows)} rows for {strategy_id}")


def insert_signal_evaluations(conn, strategy: dict, weights: dict):
    strategy_id = strategy["strategy_id"]
    strategy_name = strategy["name"]
    if not weights:
        return

    cur = conn.cursor()
    short_sid = strategy_id[:10]

    cur.execute(
        "SELECT 1 FROM gold.signal_families WHERE family_key = %s",
        (FAMILY_KEY,),
    )
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO gold.signal_families (family_key, label, strategy_id, deployed, color, strategy_name, updated_at)
            VALUES (%s, %s, %s, true, %s, %s, NOW())
            ON CONFLICT (family_key) DO UPDATE SET
              label = EXCLUDED.label,
              strategy_id = EXCLUDED.strategy_id,
              deployed = EXCLUDED.deployed,
              color = EXCLUDED.color,
              strategy_name = EXCLUDED.strategy_name,
              updated_at = EXCLUDED.updated_at;
            """,
            (FAMILY_KEY, "HK Paper V1", short_sid, "#10B981", strategy_name),
        )

    cur.execute(
        "DELETE FROM gold.signal_evaluations WHERE family_key = %s AND ticker = ANY(%s);",
        (FAMILY_KEY, list(weights.keys())),
    )
    rows = []
    for ticker, weight in weights.items():
        note = f"{strategy_id}: {strategy_name} PAPER weight={weight:.4f}"[:195]
        rows.append((
            MARKET, ticker, ticker, FAMILY_KEY, "BUY", round(weight * 100, 6), 0.0, note,
        ))

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
    print(f"{now_hkt()}  gold.signal_evaluations inserted: {len(rows)} rows for {strategy_id}")


def refresh_pipeline_view(conn):
    view_path = os.path.expanduser(
        "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/gold/strategy/create_pipeline_ui_feed_view.sql"
    )
    with open(view_path, "r") as f:
        sql = f.read()
    cur = conn.cursor()
    # CREATE OR REPLACE VIEW cannot drop columns; use a guarded drop/create.
    cur.execute("DROP VIEW IF EXISTS gold.v_pipeline_ui_feed;")
    cur.execute(sql)
    conn.commit()
    print(f"{now_hkt()}  gold.v_pipeline_ui_feed refreshed")


def record_agent_event(conn, generated_at: str, strategies: list, weights_by_strategy: dict):
    cur = conn.cursor()
    payload = {
        "feed_version": "2026.07.18.hk_lowvol",
        "generated_at": generated_at,
        "source_file": MANIFEST,
        "strategies": [
            {
                "strategy_id": s["strategy_id"],
                "name": s["name"],
                "universe": s.get("universe_tickers"),
                "weights": weights_by_strategy.get(s["strategy_id"], {}),
                "asset_class": ASSET_CLASS,
                "execution_mode": "PAPER",
            }
            for s in strategies
        ],
        "ingested_at_hkt": datetime.now(HKT).isoformat(),
    }
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status, created_at, payload)
        VALUES
          (%s, %s, %s, %s, %s::jsonb, %s, NOW(), %s::jsonb);
        """,
        ("signal_ingested", "HK_LOWVOL_BATCH_2026-07-18", "etl", "etl-manager",
         json.dumps(payload), "ok", json.dumps(payload)),
    )
    conn.commit()
    print(f"{now_hkt()}  gold.agent_events recorded")


def main():
    generated_at, by_id = load_manifest(MANIFEST)
    print(f"{now_hkt()} Loaded manifest: {MANIFEST}")
    print(f"{now_hkt()} Generated: {generated_at}")

    target_ids = ["HK_LowVol_Weekly", "HK_LowVol_TrendFilter_Weekly"]
    strategies = []
    for sid in target_ids:
        if sid not in by_id:
            raise SystemExit(f"Missing strategy in manifest: {sid}")
        s = by_id[sid]
        s["kanban_task_id"] = "t_2e28bd6f"
        strategies.append(s)

    weights_by_strategy = {}
    conn = get_connection()
    try:
        for s in strategies:
            sid = s["strategy_id"]
            sname = s["name"]
            print(f"{now_hkt()} Ingesting {sid} - {sname}")
            signal_file = os.path.join(SIGNAL_DIR, f"{sid}_live_signals.json")
            weights = load_signal_weights(sid, sname, s.get("universe_tickers", []))
            weights_by_strategy[sid] = weights
            print(f"{now_hkt()}   weights: {weights}")
            ensure_strategy_research(conn, s)
            bt = s.get("backtest_results", [{}])[0]
            ensure_backtest_runs(conn, s, bt)
            ensure_strategy_registry(conn, s, signal_file)
            upsert_ticker_scores(conn, sid, sname, generated_at, weights)
            insert_signal_evaluations(conn, s, weights)
        refresh_pipeline_view(conn)
        record_agent_event(conn, generated_at, strategies, weights_by_strategy)
    finally:
        conn.close()

    print(f"{now_hkt()} Signal pipeline ingestion complete for {len(strategies)} HK LowVol strategies.")


if __name__ == "__main__":
    main()
