#!/usr/bin/env python3
"""
WRITE_SIGNAL: LowVol_Dividend_Quality (US_STK_LOWVOL_DIV_02)
Ingests a deployed live-signal file into the gold signal pipeline.

Reads:
  /home/ubuntu/.hermes/profiles/qr_research/workspace/deployed_5_live_signals_2026-07-08.json

Writes:
  - gold.strategy_registry (asset_class, universe_tickers, signal_file_path, last_signal_at)
  - gold.strategy_ticker_scores (live signal rows: BUY at 100% score, 20% weight as entry_score)
  - consumption.signal_logs (downstream signal feed for execution/UI)
  - gold.agent_events (audit event: signal ingested by etl-manager)

Operational notes:
  - This is a PAPER strategy; no broker orders are placed.
  - We do NOT write to gold.paper_run_log here because that table is a daily
    run log (run_type IN morning/eod/weekly_review) rather than a per-strategy
    signal ledger. The agent_event records the same ingestion metadata.
"""
import sys
import os
import json
from datetime import datetime, date
import pytz

sys.path.insert(0, os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"
))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402

SIGNAL_FILE = "/home/ubuntu/.hermes/profiles/qr_research/workspace/deployed_5_live_signals_2026-07-08.json"
STRATEGY_ID = "US_STK_LOWVOL_DIV_02"
STRATEGY_NAME = "LowVol_Dividend_Quality"
HKT = pytz.timezone("Asia/Hong_Kong")


def now_hkt() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_signal(path: str):
    with open(path, "r") as f:
        data = json.load(f)
    weights = data["signals"].get(STRATEGY_NAME, {})
    if not weights:
        raise SystemExit(f"No {STRATEGY_NAME} signals found in {path}")
    return data["generated_at"], weights


def ensure_strategy_registry(conn, signal_file_path: str, tickers: list):
    """Update the live registry record with the latest signal file and universe."""
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET asset_class      = 'US Stock',
            execution_mode   = 'PAPER',
            status           = 'paper',
            universe_tickers = %s,
            signal_file_path = %s,
            updated_at       = NOW(),
            last_signal_at   = NOW()
        WHERE strategy_id = %s;
        """,
        (tickers, signal_file_path, STRATEGY_ID),
    )
    if cur.rowcount == 0:
        # Insert if the registry row is missing (should not happen for an approved strategy)
        cur.execute(
            """
            INSERT INTO gold.strategy_registry
              (strategy_id, name, asset_class, execution_mode, status,
               universe_tickers, signal_file_path, updated_at, last_signal_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
            """,
            (STRATEGY_ID, STRATEGY_NAME, "US Stock", "PAPER", "paper",
             tickers, signal_file_path),
        )
    conn.commit()
    print(f"{now_hkt()} ✅ gold.strategy_registry updated: {cur.rowcount} row(s)")


def upsert_ticker_scores(conn, generated_at: str, weights: dict):
    """Write live signal weights to gold.strategy_ticker_scores."""
    cur = conn.cursor()
    rows = []
    for ticker, weight in weights.items():
        rows.append((
            STRATEGY_ID, ticker, 100.0, "BUY", weight * 100, 0.0,
            json.dumps({
                "weight": weight,
                "source_signal_file": SIGNAL_FILE,
                "generated_at": generated_at,
                "ingested_at": datetime.now(HKT).isoformat(),
            }),
            "PAPER", datetime.now(), datetime.now(),
        ))

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
    print(f"{now_hkt()} ✅ gold.strategy_ticker_scores upserted: {len(rows)} rows")


def insert_signal_logs(conn, weights: dict):
    """Feed the live signals into consumption.signal_logs for downstream consumers."""
    cur = conn.cursor()
    # Idempotent: clear any previous signal-log rows for this strategy/date
    # before re-inserting from the authoritative deployed signal file.
    cur.execute(
        "DELETE FROM consumption.signal_logs WHERE strategy_id = %s AND signal_date = %s;",
        (STRATEGY_ID, date.today()),
    )
    rows = []
    for ticker, weight in weights.items():
        rows.append((
            STRATEGY_ID, date.today(), 1, ticker, "BUY",
            f"weight={weight}; source={SIGNAL_FILE}",
            weight * 100,
        ))

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


def record_agent_event(conn, generated_at: str, weights: dict):
    """Emit an audit event so the platform knows the signal was ingested."""
    cur = conn.cursor()
    payload = {
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "execution_mode": "PAPER",
        "signal_file": SIGNAL_FILE,
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
        VALUES
          (%s, %s, %s, %s, %s::jsonb, %s, NOW(), %s::jsonb);
        """,
        ("signal_ingested", STRATEGY_ID, "etl", "etl-manager",
         json.dumps(payload), "ok", json.dumps(payload)),
    )
    conn.commit()
    print(f"{now_hkt()} ✅ gold.agent_events recorded: {cur.rowcount} row(s)")


def main():
    generated_at, weights = load_signal(SIGNAL_FILE)
    tickers = list(weights.keys())

    print(f"{now_hkt()} Loaded signal file: {SIGNAL_FILE}")
    print(f"{now_hkt()} Generated at: {generated_at}")
    print(f"{now_hkt()} Tickers/weights: {weights}")

    conn = get_connection()
    try:
        ensure_strategy_registry(conn, SIGNAL_FILE, tickers)
        upsert_ticker_scores(conn, generated_at, weights)
        insert_signal_logs(conn, weights)
        record_agent_event(conn, generated_at, weights)
    finally:
        conn.close()

    print(f"{now_hkt()} Signal pipeline ingestion complete for {STRATEGY_ID}.")


if __name__ == "__main__":
    main()
