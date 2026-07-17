#!/usr/bin/env python3
"""
WRITE_SIGNAL: 10 Approved ETF Strategies (batch v2 audited)
Ingests the research pipeline_feed.json into the gold signal pipeline.

Reads:
  /home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed.json

Writes:
  - gold.strategy_registry (universe_tickers, asset_class, status, execution_mode, last_signal_at, signal_file_path)
  - gold.strategy_ticker_scores (live signal rows: score=100 for long-only, entry_score=100 for equal-weight n tickers)
  - gold.signal_evaluations (downstream signal feed for execution/UI, family_key='etf_paper_v2')
  - gold.agent_events (audit event: signal_ingested by etl-manager)

Operational notes:
  - This is a PAPER strategy batch; no broker orders are placed.
  - The feed contains only strategy metadata and universe; target weights are equal-weight among universe tickers.
  - Each strategy is idempotent on re-run.
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

DB_NAME = os.environ.get("DB_NAME", "airtrading")

FEED_FILE = "/home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed.json"
FAMILY_KEY = "etf_paper_v2"
HKT = pytz.timezone("Asia/Hong_Kong")


def now_hkt() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_feed(path: str):
    with open(path, "r") as f:
        data = json.load(f)
    strategies = data.get("strategies", [])
    if not strategies:
        raise SystemExit(f"No strategies in {path}")
    return data["generated_at"], data.get("feed_version", "unknown"), strategies


def ensure_strategy_registry(conn, strategy: dict):
    cur = conn.cursor()
    strategy_id = strategy["strategy_id"]
    name = strategy["name"]
    tickers = strategy["universe"]
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET asset_class      = 'ETF',
            execution_mode   = 'PAPER',
            status           = 'paper',
            universe_tickers = %s,
            signal_file_path = %s,
            updated_at       = NOW(),
            last_signal_at   = NOW()
        WHERE strategy_id = %s;
        """,
        (tickers, FEED_FILE, strategy_id),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO gold.strategy_registry
              (strategy_id, name, asset_class, execution_mode, status,
               universe_tickers, signal_file_path, updated_at, last_signal_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
            """,
            (strategy_id, name, "ETF", "PAPER", "paper", tickers, FEED_FILE),
        )
    conn.commit()


def upsert_ticker_scores(conn, generated_at: str, strategy: dict):
    strategy_id = strategy["strategy_id"]
    tickers = strategy["universe"]
    weight = 1.0 / len(tickers) if tickers else 0.0
    cur = conn.cursor()
    rows = []
    for ticker in tickers:
        rows.append((
            strategy_id, ticker, 100.0, "BUY", weight * 100, 0.0,
            json.dumps({
                "weight": round(weight, 6),
                "source_signal_file": FEED_FILE,
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


def insert_signal_evaluations(conn, strategy: dict):
    strategy_id = strategy["strategy_id"]
    tickers = strategy["universe"]
    weight = 1.0 / len(tickers) if tickers else 0.0
    cur = conn.cursor()
    # Ensure the family_key exists so FK constraint is satisfied
    # family_key has a 40-char limit; strategy_id column has a 10-char limit.
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
        (FAMILY_KEY, "ETF Paper V2", short_sid, "#10B981", strategy["name"]),
        )
    # Idempotent: clear previous signal_evaluations for this strategy/family_key
    cur.execute(
        "DELETE FROM gold.signal_evaluations WHERE family_key = %s AND ticker = ANY(%s);",
        (FAMILY_KEY, tickers),
    )
    rows = []
    for ticker in tickers:
        note = (
            f"{strategy_id}: equal-weight ETF paper signal weight={weight:.4f}"
        )[:195]
        rows.append((
            "US", ticker, ticker, FAMILY_KEY, "BUY", round(weight * 100, 6), 0.0, note,
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


def record_agent_event(conn, generated_at: str, strategies: list):
    cur = conn.cursor()
    payload = {
        "feed_version": "2026-07-09-etf-v2-audited",
        "generated_at": generated_at,
        "source_file": FEED_FILE,
        "strategies": [
            {
                "strategy_id": s["strategy_id"],
                "name": s["name"],
                "universe": s["universe"],
                "asset_class": s["asset_class"],
                "execution_mode": s["execution_mode"],
            }
            for s in strategies
        ],
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
        ("signal_ingested", "ETF_BATCH_10_2026-07-09", "etl", "etl-manager",
         json.dumps(payload), "ok", json.dumps(payload)),
    )
    conn.commit()


def main():
    generated_at, feed_version, strategies = load_feed(FEED_FILE)
    print(f"{now_hkt()} Loaded feed: {FEED_FILE}")
    print(f"{now_hkt()} Version: {feed_version} | Generated: {generated_at}")
    print(f"{now_hkt()} Strategies to ingest: {len(strategies)}")

    conn = get_connection()
    try:
        for s in strategies:
            sid = s["strategy_id"]
            print(f"{now_hkt()} Ingesting {sid} - {s['name']} (universe={s['universe']})")
            ensure_strategy_registry(conn, s)
            upsert_ticker_scores(conn, generated_at, s)
            insert_signal_evaluations(conn, s)
            print(f"{now_hkt()}   ✅ {sid} ingested")
        record_agent_event(conn, generated_at, strategies)
    finally:
        conn.close()

    print(f"{now_hkt()} Signal pipeline ingestion complete for {len(strategies)} ETF strategies.")


if __name__ == "__main__":
    main()
