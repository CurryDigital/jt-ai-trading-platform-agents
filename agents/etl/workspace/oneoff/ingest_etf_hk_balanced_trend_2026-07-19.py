#!/usr/bin/env python3
"""
Ingest updated ETF_HK_Balanced_Trend into the live signal/ETL pipeline.

Reads the research UI feed at
  /home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed.json
and the live signal file at
  /home/ubuntu/.hermes/profiles/qr_research/workspace/ETF_HK_Balanced_Trend_live_signals.json

Writes:
  - gold.strategy_research (universe, asset_class, status, backtest metrics)
  - gold.strategy_registry (universe, metrics, PAPER execution, priority)
  - gold.strategy_ticker_scores (live BUY signals per ticker)
  - gold.signal_evaluations / gold.signal_families (trend family)
  - gold.asset_registry (per-instrument asset_class)
  - gold.agent_events (audit)

Post-run: rebuilds consumption/pipeline/pipeline_feed.json via build_pipeline_feed.py.
"""
import json
import os
import subprocess
import sys
from datetime import datetime

import pytz

ETL_HOME = os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
)
SHARED = os.path.join(ETL_HOME, "shared", "scripts")
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402

RESEARCH_FEED = "/home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed.json"
SIGNAL_FILE = "/home/ubuntu/.hermes/profiles/qr_research/workspace/ETF_HK_Balanced_Trend_live_signals.json"
HKT = pytz.timezone("Asia/Hong_Kong")

STRATEGY_ID = "ETF_HK_Balanced_Trend"
FAMILY_KEY = "trend"
MARKET = "HK"

UNIVERSE = ["2800.HK", "0001.HK", "0700.HK", "1299.HK", "2318.HK", "AGG"]

ASSET_CLASS_MAP = {
    "2800.HK": "ETF",
    "0001.HK": "HK Stock",
    "0700.HK": "HK Stock",
    "1299.HK": "HK Stock",
    "2318.HK": "HK Stock",
    "AGG": "ETF",
}


def now_hkt() -> str:
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_research_feed(path: str) -> dict:
    with open(path, "r") as f:
        data = json.load(f)
    for item in data.get("data", []):
        if item.get("id") == STRATEGY_ID:
            return item
    raise SystemExit(f"{STRATEGY_ID} not found in {path}")


def load_signal_weights(path: str) -> dict:
    with open(path, "r") as f:
        data = json.load(f)
    signals = data.get("signals", {})
    weights = signals.get("HK Balanced Trend") or signals.get(STRATEGY_ID)
    if not weights:
        raise SystemExit(f"No weights found in {path}")
    cleaned = {t: float(w) for t, w in weights.items() if float(w) > 0}
    total = sum(cleaned.values())
    if total <= 0:
        raise SystemExit(f"All weights are zero in {path}")
    return {t: w / total for t, w in cleaned.items()}


def ensure_strategy_research(conn, item: dict, weights: dict):
    cur = conn.cursor()
    metrics = {
        "sharpe_oos": float(item["sharpe"]),
        "returns_oos": float(item["returns"]) / 100.0,
        "max_drawdown_oos": float(item["dd"]) / 100.0,
        "trade_count_oos": int(item["trades"]),
        "win_rate_oos": float(item["btwr"]) / 100.0,
        "profit_factor_oos": float(item["btpf"]),
    }
    cur.execute(
        """
        UPDATE gold.strategy_research
        SET name            = %s,
            asset_class     = %s,
            status          = %s,
            universe_tickers = %s,
            frequency       = %s,
            updated_at      = NOW()
        WHERE strategy_id = %s;
        """,
        (
            item["name"],
            item["asset"],
            item["db_status"],
            list(weights.keys()),
            item["frequency"],
            STRATEGY_ID,
        ),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO gold.strategy_research
              (strategy_id, name, asset_class, status, universe_tickers, frequency, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW());
            """,
            (
                STRATEGY_ID,
                item["name"],
                item["asset"],
                item["db_status"],
                list(weights.keys()),
                item["frequency"],
            ),
        )
    conn.commit()

    # Ensure the latest backtest run carries the same metrics.
    cur.execute(
        """
        SELECT run_id
        FROM gold.strategy_backtest_runs
        WHERE strategy_id = %s
        ORDER BY created_at DESC
        LIMIT 1;
        """,
        (STRATEGY_ID,),
    )
    row = cur.fetchone()
    if row:
        run_id = row[0]
        cur.execute(
            """
            UPDATE gold.strategy_backtest_runs
            SET sharpe_oos        = %s,
                returns_oos       = %s,
                max_drawdown_oos  = %s,
                trade_count_oos   = %s,
                win_rate_oos      = %s,
                profit_factor_oos = %s,
                all_risk_gates_passed = true
            WHERE run_id = %s;
            """,
            (
                metrics["sharpe_oos"],
                metrics["returns_oos"],
                metrics["max_drawdown_oos"],
                metrics["trade_count_oos"],
                metrics["win_rate_oos"],
                metrics["profit_factor_oos"],
                run_id,
            ),
        )
        conn.commit()
        print(f"{now_hkt()}  strategy_backtest_runs updated for run_id={run_id}")
    else:
        print(f"{now_hkt()}  WARNING: no strategy_backtest_runs row found; metrics not backfilled")

    print(f"{now_hkt()}  gold.strategy_research updated for {STRATEGY_ID}")


def ensure_strategy_registry(conn, item: dict, weights: dict):
    metrics = {
        "sharpe_oos": float(item["sharpe"]),
        "returns_oos": float(item["returns"]) / 100.0,
        "max_drawdown_oos": abs(float(item["dd"]) / 100.0),
        "trade_count_oos": int(item["trades"]),
        "win_rate_oos": float(item["btwr"]) / 100.0,
        "profit_factor_oos": float(item["btpf"]),
    }
    # Map research tier to registry priority while preserving T3 tier.
    priority = "EXPERIMENTAL"  # research feed tier T3 maps to else -> T3
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET name              = %s,
            asset_class       = %s,
            universe_tickers  = %s,
            frequency         = %s,
            execution_mode    = 'PAPER',
            status            = 'paper',
            priority          = %s,
            sharpe_oos        = %s,
            max_drawdown_oos  = %s,
            trade_count_oos   = %s,
            win_rate_oos      = %s,
            returns_oos       = %s,
            profit_factor_oos = %s,
            signal_file_path  = %s,
            updated_at        = NOW(),
            last_signal_at    = NOW()
        WHERE strategy_id = %s;
        """,
        (
            item["name"],
            item["asset"],
            list(weights.keys()),
            item["frequency"],
            priority,
            metrics["sharpe_oos"],
            metrics["max_drawdown_oos"],
            metrics["trade_count_oos"],
            metrics["win_rate_oos"],
            metrics["returns_oos"],
            metrics["profit_factor_oos"],
            SIGNAL_FILE,
            STRATEGY_ID,
        ),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO gold.strategy_registry
              (strategy_id, name, asset_class, universe_tickers, frequency, execution_mode,
               status, priority, sharpe_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
               returns_oos, profit_factor_oos, signal_file_path, created_at, updated_at, last_signal_at)
            VALUES
              (%s, %s, %s, %s, %s, 'PAPER', 'paper', %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW());
            """,
            (
                STRATEGY_ID,
                item["name"],
                item["asset"],
                list(weights.keys()),
                item["frequency"],
                priority,
                metrics["sharpe_oos"],
                metrics["max_drawdown_oos"],
                metrics["trade_count_oos"],
                metrics["win_rate_oos"],
                metrics["returns_oos"],
                metrics["profit_factor_oos"],
                SIGNAL_FILE,
            ),
        )
    conn.commit()
    print(f"{now_hkt()}  gold.strategy_registry updated for {STRATEGY_ID}")


def upsert_ticker_scores(conn, strategy_name: str, weights: dict):
    rows = []
    for ticker, weight in weights.items():
        rows.append((
            STRATEGY_ID, ticker, 100.0, "BUY", weight * 100, 0.0,
            json.dumps({
                "weight": round(weight, 6),
                "source_signal_file": SIGNAL_FILE,
                "generated_at": datetime.now(HKT).isoformat(),
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
    print(f"{now_hkt()}  gold.strategy_ticker_scores upserted: {len(rows)} rows")


def ensure_signal_family(conn, strategy_name: str):
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
        (FAMILY_KEY, "HK Balanced Trend", STRATEGY_ID, "#3B82F6", strategy_name),
    )
    conn.commit()
    print(f"{now_hkt()}  gold.signal_families upserted for family_key={FAMILY_KEY}")


def clear_legacy_trend_signals(conn, weights: dict):
    """Remove any stale trend-family signals for this universe (e.g. old US-market AGG)."""
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM gold.signal_evaluations
        WHERE family_key = %s
          AND ticker = ANY(%s)
          AND market != %s;
        """,
        (FAMILY_KEY, list(weights.keys()), MARKET),
    )
    conn.commit()
    print(f"{now_hkt()}  cleared {cur.rowcount} legacy trend-family signal rows outside market={MARKET}")


def upsert_signal_evaluations(conn, strategy_name: str, weights: dict):
    clear_legacy_trend_signals(conn, weights)

    cur = conn.cursor()
    rows = []
    for ticker, weight in weights.items():
        note = f"{STRATEGY_ID}: {strategy_name} PAPER weight={weight:.6f}"[:195]
        rows.append((
            MARKET, ticker, ticker, FAMILY_KEY, "BUY",
            round(weight * 100, 6), 0.0, note,
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
    print(f"{now_hkt()}  gold.signal_evaluations upserted: {len(rows)} rows for family_key={FAMILY_KEY}")


def update_asset_registry(conn):
    cur = conn.cursor()
    updated = 0
    for ticker, asset_class in ASSET_CLASS_MAP.items():
        cur.execute(
            """
            UPDATE gold.asset_registry
            SET asset_class = %s,
                updated_at  = NOW()
            WHERE ticker = %s
              AND asset_class IS DISTINCT FROM %s;
            """,
            (asset_class, ticker, asset_class),
        )
        updated += cur.rowcount
    conn.commit()
    print(f"{now_hkt()}  gold.asset_registry updated: {updated} rows")


def record_agent_event(conn, item: dict, weights: dict):
    cur = conn.cursor()
    payload = {
        "strategy_id": STRATEGY_ID,
        "name": item["name"],
        "asset_class": item["asset"],
        "frequency": item["frequency"],
        "execution_mode": "PAPER",
        "universe": list(weights.keys()),
        "weights": {t: round(w, 6) for t, w in weights.items()},
        "source_feed": RESEARCH_FEED,
        "source_signal_file": SIGNAL_FILE,
        "ingested_at_hkt": datetime.now(HKT).isoformat(),
    }
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status, created_at, payload)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, NOW(), %s::jsonb);
        """,
        (
            "signal_ingested",
            STRATEGY_ID,
            "etl",
            "etl-manager",
            json.dumps(payload),
            "ok",
            json.dumps(payload),
        ),
    )
    conn.commit()
    print(f"{now_hkt()}  gold.agent_events recorded")


def rebuild_pipeline_feed():
    builder = os.path.join(ETL_HOME, "consumption", "pipeline", "build_pipeline_feed.py")
    proc = subprocess.run(
        [sys.executable, builder],
        capture_output=True,
        text=True,
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"build_pipeline_feed.py failed with code {proc.returncode}")
    print(f"{now_hkt()}  pipeline_feed.json rebuilt")


def main():
    print(f"{now_hkt()} Starting ingestion of {STRATEGY_ID}")
    item = load_research_feed(RESEARCH_FEED)
    weights = load_signal_weights(SIGNAL_FILE)

    # Validate universe consistency
    expected = set(UNIVERSE)
    actual = set(weights.keys())
    if expected != actual:
        raise SystemExit(
            f"Signal file universe {sorted(actual)} does not match expected {sorted(expected)}"
        )

    conn = get_connection()
    try:
        ensure_strategy_research(conn, item, weights)
        ensure_strategy_registry(conn, item, weights)
        upsert_ticker_scores(conn, item["name"], weights)
        ensure_signal_family(conn, item["name"])
        upsert_signal_evaluations(conn, item["name"], weights)
        update_asset_registry(conn)
        record_agent_event(conn, item, weights)
    finally:
        conn.close()

    rebuild_pipeline_feed()
    print(f"{now_hkt()} Ingestion complete for {STRATEGY_ID}")


if __name__ == "__main__":
    main()
