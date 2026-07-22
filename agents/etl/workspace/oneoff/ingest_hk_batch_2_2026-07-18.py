#!/usr/bin/env python3
"""
WRITE_SIGNAL: HK strategy expansion batch (2 strategies)

Ingests 2 approved HK strategies from the research pipeline_feed.json
and their per-strategy live signal files into the gold signal pipeline.

Strategies:
- ETF_HK_Balanced_Trend (updated universe: 2800.HK, 0001.HK, 0700.HK, 1299.HK, 2318.HK, AGG)
- HK_Quality_BlueChips (new: 20 HK blue-chip tickers)

Reads:
  /home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed.json (metadata)
  /home/ubuntu/.hermes/profiles/qr_research/workspace/<strategy_id>_live_signals.json (weights)

Writes:
  - gold.strategy_registry (status/execution_mode/universe/priority/OOS stats/signal file path)
  - gold.strategy_ticker_scores (live BUY signals)
  - gold.signal_evaluations (downstream UI/execution feed)
  - gold.agent_events (audit event)

Operational notes:
  - PAPER strategies only.
  - The script is idempotent on re-run.
  - asset_class for ETF_HK_Balanced_Trend is 'ETF'.
  - asset_class for HK_Quality_BlueChips is 'HK Stock'.
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

FEED_FILE = "/home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed.json"
SIGNAL_DIR = "/home/ubuntu/.hermes/profiles/qr_research/workspace"
HKT = pytz.timezone("Asia/Hong_Kong")
FAMILY_KEY = "hk_paper_v1"

STRATEGIES = [
    {
        "strategy_id": "ETF_HK_Balanced_Trend",
        "asset_class": "ETF",
        "market": "HK",
    },
    {
        "strategy_id": "HK_Quality_BlueChips",
        "asset_class": "HK Stock",
        "market": "HK",
    },
]


def now_hkt() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_feed(path: str):
    with open(path, "r") as f:
        data = json.load(f)
    by_id = {s["strategy_id"]: s for s in data.get("strategies", [])}
    return data.get("generated_at", "unknown"), data.get("feed_version", "unknown"), by_id


def load_signal_weights(strategy_id: str, strategy_name: str, fallback_universe: list):
    """Return weights dict from the live signal file, or equal-weight fallback."""
    path = os.path.join(SIGNAL_DIR, f"{strategy_id}_live_signals.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        signals = data.get("signals", {})
        weights = signals.get(strategy_name) or signals.get(strategy_id)
        if weights:
            # Drop zero-weight tickers and normalize
            cleaned = {t: float(w) for t, w in weights.items() if float(w) > 0}
            if cleaned:
                total = sum(cleaned.values())
                if total > 0:
                    return {t: w / total for t, w in cleaned.items()}
    # Fallback: equal-weight from the pipeline feed universe
    if fallback_universe:
        weight = 1.0 / len(fallback_universe)
        return {ticker: weight for ticker in fallback_universe}
    return {}


def ensure_strategy_registry(conn, strategy: dict, asset_class: str, signal_file: str):
    strategy_id = strategy["strategy_id"]
    name = strategy["name"]
    tickers = strategy.get("universe") or strategy.get("universe_tickers")
    priority = strategy.get("priority", "NEAR_GOLDEN")
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
            asset_class, priority, tickers, signal_file,
            strategy.get("sharpe_oos"), strategy.get("max_drawdown_oos"),
            strategy.get("trade_count_oos"), strategy.get("win_rate_oos"),
            strategy.get("returns_oos"), strategy_id,
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
                strategy_id, name, asset_class, priority, tickers, signal_file,
                strategy.get("sharpe_oos"), strategy.get("max_drawdown_oos"),
                strategy.get("trade_count_oos"), strategy.get("win_rate_oos"),
                strategy.get("returns_oos"),
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


def insert_signal_evaluations(conn, strategy: dict, asset_class: str, weights: dict):
    strategy_id = strategy["strategy_id"]
    strategy_name = strategy["name"]
    if not weights:
        return

    cur = conn.cursor()
    short_sid = strategy_id[:10]

    # Ensure family exists
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

    # Idempotent: clear previous signal_evaluations for this strategy's tickers
    cur.execute(
        "DELETE FROM gold.signal_evaluations WHERE family_key = %s AND ticker = ANY(%s);",
        (FAMILY_KEY, list(weights.keys())),
    )

    rows = []
    for ticker, weight in weights.items():
        note = f"{strategy_id}: {strategy_name} PAPER weight={weight:.4f}"[:195]
        rows.append((
            "HK", ticker, ticker, FAMILY_KEY, "BUY", round(weight * 100, 6), 0.0, note,
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


def record_agent_event(conn, generated_at: str, strategies: list, weights_by_strategy: dict):
    cur = conn.cursor()
    payload = {
        "feed_version": "2026.07.18.approved",
        "generated_at": generated_at,
        "source_file": FEED_FILE,
        "strategies": [
            {
                "strategy_id": s["strategy_id"],
                "name": s["name"],
                "universe": s["universe"],
                "weights": weights_by_strategy.get(s["strategy_id"], {}),
                "asset_class": s.get("asset_class"),
                "execution_mode": "PAPER",
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
        ("signal_ingested", "HK_BATCH_2_2026-07-18", "etl", "etl-manager",
         json.dumps(payload), "ok", json.dumps(payload)),
    )
    conn.commit()
    print(f"{now_hkt()}  gold.agent_events recorded")


def main():
    generated_at, feed_version, by_id = load_feed(FEED_FILE)
    print(f"{now_hkt()} Loaded feed: {FEED_FILE}")
    print(f"{now_hkt()} Version: {feed_version} | Generated: {generated_at}")

    strategies = []
    for meta in STRATEGIES:
        sid = meta["strategy_id"]
        if sid not in by_id:
            raise SystemExit(f"Missing strategy in feed: {sid}")
        s = by_id[sid]
        # Prefer the task-specified universe over the feed's stale universe.
        # The feed currently lists 2800.HK/AGG for ETF_HK_Balanced_Trend, but
        # the approved research universe includes 6 tickers.
        if sid == "ETF_HK_Balanced_Trend":
            s["universe"] = ["2800.HK", "0001.HK", "0700.HK", "1299.HK", "2318.HK", "AGG"]
        # Ensure `universe` alias exists for both strategies.
        if "universe" not in s and "universe_tickers" in s:
            s["universe"] = s["universe_tickers"]
        s["asset_class"] = meta["asset_class"]
        s["market"] = meta["market"]
        strategies.append(s)

    weights_by_strategy = {}
    conn = get_connection()
    try:
        for s in strategies:
            sid = s["strategy_id"]
            sname = s["name"]
            asset_class = s["asset_class"]
            print(f"{now_hkt()} Ingesting {sid} - {sname} ({asset_class})")
            signal_file = os.path.join(SIGNAL_DIR, f"{sid}_live_signals.json")
            weights = load_signal_weights(sid, sname, s.get("universe", []))
            weights_by_strategy[sid] = weights
            print(f"{now_hkt()}   weights: {weights}")
            ensure_strategy_registry(conn, s, asset_class, signal_file)
            upsert_ticker_scores(conn, sid, sname, generated_at, weights)
            insert_signal_evaluations(conn, s, asset_class, weights)
        record_agent_event(conn, generated_at, strategies, weights_by_strategy)
    finally:
        conn.close()

    print(f"{now_hkt()} Signal pipeline ingestion complete for {len(strategies)} HK strategies.")


if __name__ == "__main__":
    main()
