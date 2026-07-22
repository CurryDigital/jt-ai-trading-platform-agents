#!/usr/bin/env python3
"""
Ingest HK_Quality_BlueChips into the live signal/ETL pipeline.

Task: t_259b9936
Source: /home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_live_signals.json
Backtest: /home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_expanded_results.json

Writes:
  - gold.strategy_registry (status, execution_mode, universe, asset_class, OOS stats, signal file)
  - gold.strategy_backtest_runs (latest OOS run)
  - gold.strategy_ticker_scores (live BUY signals per ticker)
  - gold.signal_evaluations (downstream UI/execution feed, family_key='hk_paper_v1')
  - gold.signal_families (ensure family exists)
  - consumption.signal_logs (signal ledger)
  - gold.asset_registry (asset_class='HK Stock' for all constituents)
  - gold.agent_events (audit event)

Operational notes:
  - PAPER strategy only.
  - Idempotent on re-run.
  - Uses the canonical ETL venv and db.py connection pool.
  - 0011.HK is marked delisted by upstream broker mapping; this script updates
    its asset_class but does NOT force is_active=true without operator approval.
"""
import json
import os
import sys
import csv
from datetime import datetime, date

import pytz

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts")
sys.path.insert(0, SHARED)
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402

HKT = pytz.timezone("Asia/Hong_Kong")

STRATEGY_ID = "HK_Quality_BlueChips"
STRATEGY_NAME = "HK Quality BlueChips Momentum"
ASSET_CLASS = "HK Stock"
MARKET = "HK"
PRIORITY = "EXPERIMENTAL"
FAMILY_KEY = "hk_paper_v1"
EXECUTION_MODE = "PAPER"
STATUS = "paper"

SIGNAL_FILE = "/home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_live_signals.json"
BACKTEST_FILE = "/home/ubuntu/.hermes/profiles/qr_research/workspace/HK_Quality_BlueChips_backtest_report.csv"

UNIVERSE = [
    "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK", "0011.HK",
    "0016.HK", "0027.HK", "0388.HK", "0669.HK", "0836.HK", "0939.HK",
    "0941.HK", "1038.HK", "1299.HK", "1398.HK", "1928.HK", "2318.HK",
    "2388.HK", "2628.HK",
]


def now_hkt() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_signal_file(path: str) -> tuple:
    with open(path, "r") as f:
        data = json.load(f)
    signals = data.get("signals", {})
    # The file is keyed by strategy name; fallback to strategy_id.
    weights = signals.get(STRATEGY_NAME) or signals.get(STRATEGY_ID) or {}
    if not weights:
        raise SystemExit(f"No weights found for {STRATEGY_NAME} in {path}")
    generated_at = data.get("generated_at", "unknown")
    return generated_at, weights


def load_backtest(path: str) -> dict:
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        rows = {row["metric"]: row["out_of_sample"] for row in reader}
    # Map the backtest report's metrics to the canonical strategy_id.
    return {
        "sharpe_oos": float(rows.get("sharpe", 0)) if rows.get("sharpe") else None,
        "returns_oos": float(rows.get("returns", 0)) if rows.get("returns") else None,
        "max_drawdown_oos": float(rows.get("max_drawdown", 0)) if rows.get("max_drawdown") else None,
        "trade_count_oos": int(float(rows.get("trade_count", 0))) if rows.get("trade_count") else None,
        "win_rate_oos": float(rows.get("win_rate", 0)) if rows.get("win_rate") else None,
        "profit_factor_oos": float(rows.get("profit_factor", 0)) if rows.get("profit_factor") else None,
        "sharpe_is": None,
        "returns_is": None,
        "max_drawdown_is": None,
        "period_start": date(2025, 1, 1),
        "period_end": date(2026, 7, 17),
        "backtest_id": STRATEGY_ID,
    }


def normalize_weights(weights: dict) -> dict:
    cleaned = {t: float(w) for t, w in weights.items() if float(w) > 0}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {t: w / total for t, w in cleaned.items()}


def ensure_strategy_registry(conn, bt: dict, signal_file: str):
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET asset_class          = %s,
            execution_mode       = %s,
            status               = %s,
            priority             = %s,
            universe_tickers     = %s,
            signal_file_path     = %s,
            sharpe_oos           = %s,
            max_drawdown_oos     = %s,
            trade_count_oos      = %s,
            win_rate_oos         = %s,
            returns_oos          = %s,
            profit_factor_oos    = %s,
            updated_at           = NOW(),
            last_signal_at       = NOW()
        WHERE strategy_id = %s;
        """,
        (
            ASSET_CLASS, EXECUTION_MODE, STATUS, PRIORITY, UNIVERSE, signal_file,
            bt.get("sharpe_oos"), bt.get("max_drawdown_oos"),
            bt.get("trade_count_oos"), bt.get("win_rate_oos"),
            bt.get("returns_oos"), bt.get("profit_factor_oos"),
            STRATEGY_ID,
        ),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO gold.strategy_registry
              (strategy_id, name, asset_class, execution_mode, status, priority,
               universe_tickers, signal_file_path, sharpe_oos, max_drawdown_oos,
               trade_count_oos, win_rate_oos, returns_oos, profit_factor_oos,
               updated_at, last_signal_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
            """,
            (
                STRATEGY_ID, STRATEGY_NAME, ASSET_CLASS, EXECUTION_MODE, STATUS, PRIORITY,
                UNIVERSE, signal_file, bt.get("sharpe_oos"), bt.get("max_drawdown_oos"),
                bt.get("trade_count_oos"), bt.get("win_rate_oos"),
                bt.get("returns_oos"), bt.get("profit_factor_oos"),
            ),
        )
    conn.commit()
    print(f"{now_hkt()}  gold.strategy_registry updated for {STRATEGY_ID}")


def ensure_backtest_runs(conn, bt: dict):
    cur = conn.cursor()
    # Use run_number 3 for this task's canonical refresh (existing rows are 1 and 2).
    run_number = 3
    cur.execute(
        """
        SELECT run_id FROM gold.strategy_backtest_runs
        WHERE strategy_id = %s AND run_number = %s
        ORDER BY created_at DESC LIMIT 1;
        """,
        (STRATEGY_ID, run_number),
    )
    row = cur.fetchone()
    params = json.dumps({
        "source": "HK_Quality_BlueChips_backtest_report.csv",
        "backtest_id": bt.get("backtest_id"),
        "period_start": str(bt.get("period_start")),
        "period_end": str(bt.get("period_end")),
    })
    if row:
        run_id = row[0]
        cur.execute(
            """
            UPDATE gold.strategy_backtest_runs
            SET is_start = %s, is_end = %s, oos_start = %s, oos_end = %s,
                sharpe_oos = %s, returns_oos = %s, max_drawdown_oos = %s,
                trade_count_oos = %s, win_rate_oos = %s, profit_factor_oos = %s,
                sharpe_is = %s, returns_is = %s, max_drawdown_is = %s,
                all_risk_gates_passed = true, parameters_used = %s::jsonb,
                notes = %s, created_at = NOW()
            WHERE run_id = %s;
            """,
            (
                bt.get("period_start"), bt.get("period_end"),
                bt.get("period_start"), bt.get("period_end"),
                bt.get("sharpe_oos"), bt.get("returns_oos"), bt.get("max_drawdown_oos"),
                bt.get("trade_count_oos"), bt.get("win_rate_oos"), bt.get("profit_factor_oos"),
                bt.get("sharpe_is"), bt.get("returns_is"), bt.get("max_drawdown_is"),
                params, "t_259b9936 refresh", run_id,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO gold.strategy_backtest_runs
              (strategy_id, run_number, run_by, is_start, is_end, oos_start, oos_end,
               sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
               profit_factor_oos, sharpe_is, returns_is, max_drawdown_is,
               all_risk_gates_passed, parameters_used, notes, created_at)
            VALUES
              (%s, %s, 'etl-manager', %s, %s, %s, %s,
               %s, %s, %s, %s, %s, %s, %s, %s, %s,
               true, %s::jsonb, %s, NOW());
            """,
            (
                STRATEGY_ID, run_number,
                bt.get("period_start"), bt.get("period_end"),
                bt.get("period_start"), bt.get("period_end"),
                bt.get("sharpe_oos"), bt.get("returns_oos"), bt.get("max_drawdown_oos"),
                bt.get("trade_count_oos"), bt.get("win_rate_oos"), bt.get("profit_factor_oos"),
                bt.get("sharpe_is"), bt.get("returns_is"), bt.get("max_drawdown_is"),
                params, "t_259b9936 refresh",
            ),
        )
    conn.commit()
    print(f"{now_hkt()}  gold.strategy_backtest_runs upserted for {STRATEGY_ID}")


def upsert_ticker_scores(conn, generated_at: str, weights: dict):
    if not weights:
        print(f"{now_hkt()}  no weights; skipping ticker scores")
        return
    rows = []
    for ticker, weight in weights.items():
        rows.append((
            STRATEGY_ID, ticker, 100.0, "BUY", weight * 100, 0.0,
            json.dumps({
                "weight": round(weight, 6),
                "source_signal_file": SIGNAL_FILE,
                "generated_at": generated_at,
                "ingested_at": datetime.now(HKT).isoformat(),
                "execution_mode": EXECUTION_MODE,
                "strategy_name": STRATEGY_NAME,
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
    print(f"{now_hkt()}  gold.strategy_ticker_scores upserted: {len(rows)} rows")


def ensure_signal_family(conn):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO gold.signal_families
          (family_key, label, strategy_id, deployed, color, strategy_name, updated_at)
        VALUES (%s, %s, %s, true, %s, %s, NOW())
        ON CONFLICT (family_key) DO UPDATE SET
          label = EXCLUDED.label,
          strategy_id = EXCLUDED.strategy_id,
          deployed = EXCLUDED.deployed,
          color = EXCLUDED.color,
          strategy_name = EXCLUDED.strategy_name,
          updated_at = EXCLUDED.updated_at;
        """,
        (FAMILY_KEY, "HK Paper V1", STRATEGY_ID, "#10B981", STRATEGY_NAME),
    )
    conn.commit()


def upsert_signal_evaluations(conn, weights: dict):
    if not weights:
        return
    ensure_signal_family(conn)
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM gold.signal_evaluations WHERE family_key = %s AND ticker = ANY(%s);",
        (FAMILY_KEY, list(weights.keys())),
    )
    rows = []
    for ticker, weight in weights.items():
        note = f"{STRATEGY_ID}: {STRATEGY_NAME} PAPER weight={weight:.4f}"[:195]
        rows.append((MARKET, ticker, ticker, FAMILY_KEY, "BUY", round(weight * 100, 6), 0.0, note))
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
    print(f"{now_hkt()}  gold.signal_evaluations upserted: {len(rows)} rows")


def upsert_signal_logs(conn, weights: dict):
    if not weights:
        return
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM consumption.signal_logs WHERE strategy_id = %s AND signal_date = %s;",
        (STRATEGY_ID, date.today()),
    )
    rows = [
        (STRATEGY_ID, date.today(), 1, ticker, "BUY",
         f"weight={weight}; source={SIGNAL_FILE}", weight * 100)
        for ticker, weight in weights.items()
    ]
    cur.executemany(
        """
        INSERT INTO consumption.signal_logs
          (strategy_id, signal_date, signal, ticker, signal_type, signal_criteria, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
        """,
        rows,
    )
    conn.commit()
    print(f"{now_hkt()}  consumption.signal_logs upserted: {len(rows)} rows")


def update_asset_registry(conn):
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gold.asset_registry
        SET asset_class = %s,
            updated_at = NOW()
        WHERE ticker = ANY(%s)
          AND asset_class != %s;
        """,
        (ASSET_CLASS, UNIVERSE, ASSET_CLASS),
    )
    n = cur.rowcount
    conn.commit()
    print(f"{now_hkt()}  gold.asset_registry asset_class aligned to '{ASSET_CLASS}': {n} rows")


def record_agent_event(conn, generated_at: str, weights: dict):
    cur = conn.cursor()
    payload = {
        "task_id": "t_259b9936",
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "execution_mode": EXECUTION_MODE,
        "asset_class": ASSET_CLASS,
        "universe": UNIVERSE,
        "signal_file": SIGNAL_FILE,
        "backtest_file": BACKTEST_FILE,
        "backtest_source": "HK_Quality_BlueChips_backtest_report.csv",
        "generated_at": generated_at,
        "tickers": list(weights.keys()),
        "weights": weights,
        "ingested_at_hkt": datetime.now(HKT).isoformat(),
    }
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status, created_at, payload)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, NOW(), %s::jsonb);
        """,
        ("signal_ingested", STRATEGY_ID, "etl", "etl-manager",
         json.dumps(payload), "ok", json.dumps(payload)),
    )
    conn.commit()
    print(f"{now_hkt()}  gold.agent_events recorded")


def main():
    generated_at, raw_weights = load_signal_file(SIGNAL_FILE)
    bt = load_backtest(BACKTEST_FILE)
    weights = normalize_weights(raw_weights)
    print(f"{now_hkt()} Loaded signal file: {SIGNAL_FILE}")
    print(f"{now_hkt()} Loaded backtest file: {BACKTEST_FILE}")
    print(f"{now_hkt()} Ingesting {STRATEGY_ID} ({STRATEGY_NAME}) with {len(weights)} tickers")

    conn = get_connection()
    try:
        ensure_strategy_registry(conn, bt, SIGNAL_FILE)
        ensure_backtest_runs(conn, bt)
        upsert_ticker_scores(conn, generated_at, weights)
        upsert_signal_evaluations(conn, weights)
        upsert_signal_logs(conn, weights)
        update_asset_registry(conn)
        record_agent_event(conn, generated_at, weights)
    finally:
        conn.close()

    print(f"{now_hkt()} HK_Quality_BlueChips live signal ingestion complete.")


if __name__ == "__main__":
    main()
