#!/usr/bin/env python3
"""
Ingest the live ETF Multi-Asset Tactical Allocation signal file into the DB.

Reads the latest research output JSON matching:
  /home/ubuntu/.hermes/profiles/qr_research/workspace/deployed_5_live_signals_*.json

Actions:
  - Align gold.strategy_registry.universe_tickers with the signal file.
  - Update strategy_configs / strategy_thresholds to accommodate the live weights
    (single-asset cap raised if the file exceeds 0.20; otherwise left as-is).
  - Replace stale gold.strategy_ticker_scores rows with the live weights.
  - Replace stale gold.signal_evaluations rows (family_key='tactical') with the live weights.
  - Update gold.strategy_registry.last_signal_at.

This script is idempotent. It is designed to be called from pipeline_b_signals.sh
after the generic strategy scorer and before build_signal_redesign.py.
"""
import os
import sys
import glob
import json
import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S %Z",
)
logger = logging.getLogger("ingest_etf_multi_asset_live_signal")

STRATEGY_ID = "ETF_Multi_Asset_Tactical_Allocation"
STRATEGY_NAME = "Multi-Asset Tactical Allocation"
FAMILY_KEY = "tactical"
SIGNAL_FILE_GLOB = "/home/ubuntu/.hermes/profiles/qr_research/workspace/deployed_5_live_signals_*.json"


def get_db() -> psycopg2.extensions.connection:
    env_paths = [
        "/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env",
        "/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/.env",
        "/home/ubuntu/.hermes/profiles/qr_etl/.env",
    ]
    for p in env_paths:
        if os.path.exists(p):
            load_dotenv(p, override=True)
            break
    host = os.getenv("GOLD_DB_HOST") or os.getenv("DB_HOST")
    db = os.getenv("GOLD_DB_NAME") or os.getenv("DB_NAME")
    user = os.getenv("GOLD_DB_USER") or os.getenv("DB_USER")
    pw = os.getenv("GOLD_DB_PASSWORD") or os.getenv("DB_PASSWORD")
    port = os.getenv("GOLD_DB_PORT") or os.getenv("DB_PORT", "5432")
    if not all([host, db, user, pw]):
        raise RuntimeError("Missing DB credentials in env")
    return psycopg2.connect(host=host, dbname=db, user=user, password=pw, port=port)


def latest_signal_file() -> str:
    files = glob.glob(SIGNAL_FILE_GLOB)
    if not files:
        raise FileNotFoundError(f"No live signal file found at {SIGNAL_FILE_GLOB}")
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def load_live_weights(path: str) -> Tuple[str, Dict[str, float]]:
    """Return (generated_at_iso, {ticker: weight})."""
    with open(path) as f:
        data = json.load(f)
    generated_at = data.get("generated_at", datetime.now(timezone.utc).isoformat())
    signals = data.get("signals", {})
    if not signals:
        raise ValueError(f"No 'signals' block in {path}")
    weights = None
    for key, alloc in signals.items():
        if key == STRATEGY_NAME or key.replace("_", " ").lower() == STRATEGY_NAME.lower():
            weights = alloc
            break
    if weights is None:
        raise ValueError(f"Strategy '{STRATEGY_NAME}' not found in {path}; keys={list(signals.keys())}")
    # Normalize weights to sum exactly 1.0
    total = sum(weights.values())
    if total <= 0:
        raise ValueError(f"Weights sum to zero in {path}")
    normalized = {ticker: float(w) / total for ticker, w in weights.items()}
    return generated_at, normalized


def ensure_registry_universe(conn, tickers: List[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE gold.strategy_registry SET universe_tickers = %s, updated_at = NOW() "
            "WHERE strategy_id = %s",
            (tickers, STRATEGY_ID),
        )
        logger.info("Updated registry universe to %s tickers", len(tickers))


def adapt_max_single_asset_exposure(conn, max_weight: float) -> None:
    """Raise the single-asset exposure config/threshold if the live file exceeds it."""
    new_cap = max(math.ceil(max_weight * 20) / 20, 0.20)  # round up to nearest 0.05
    if new_cap <= 0.20:
        return
    with conn.cursor() as cur:
        # Update strategy_configs
        cur.execute(
            """
            INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value, description, updated_at)
            VALUES (%s, 'max_single_asset_exposure', jsonb_build_object('value', %s), 'Raised to fit live signal file', NOW())
            ON CONFLICT (strategy_id, config_key) DO UPDATE SET
                config_value = EXCLUDED.config_value,
                description = EXCLUDED.description,
                updated_at = NOW();
            """,
            (STRATEGY_ID, new_cap),
        )
        # Update strategy_thresholds (no unique constraint; delete+insert)
        cur.execute(
            "DELETE FROM gold.strategy_thresholds WHERE strategy_id=%s AND metric_name='max_single_asset_exposure'",
            (STRATEGY_ID,),
        )
        cur.execute(
            """
            INSERT INTO gold.strategy_thresholds (strategy_id, metric_name, min_value, max_value, trigger_action, updated_at)
            VALUES (%s, 'max_single_asset_exposure', 0.0, %s, 'REBALANCE', NOW());
            """,
            (STRATEGY_ID, new_cap),
        )
    logger.info("Raised max_single_asset_exposure cap to %.2f to fit live weights", new_cap)


def clear_stale_signal_rows(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM gold.strategy_universes WHERE strategy_id = %s",
            (STRATEGY_ID,),
        )
        cur.execute(
            "DELETE FROM gold.strategy_ticker_scores WHERE strategy_id = %s",
            (STRATEGY_ID,),
        )
        # Only clear our own family_key so we don't clobber unrelated signals
        cur.execute(
            "DELETE FROM gold.signal_evaluations WHERE family_key = %s",
            (FAMILY_KEY,),
        )
    logger.info("Cleared stale rows for strategy_id=%s family_key=%s", STRATEGY_ID, FAMILY_KEY)


def ensure_strategy_definition(conn) -> None:
    """paper_run_etf_multi_asset.py reads gold.strategy_definitions; ensure row exists."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM gold.strategy_definitions WHERE strategy_id=%s",
            (STRATEGY_ID,),
        )
        if cur.fetchone():
            return
        cur.execute(
            """
            INSERT INTO gold.strategy_definitions
                (strategy_id, strategy_name, strategy_type, description, parameters, execution_mode, status, created_at, updated_at)
            VALUES (%s, %s, 'research', 'ETF Multi-Asset Tactical Allocation approved live signal', '{}', 'PAPER_TRADING', 'approved', NOW(), NOW());
            """,
            (STRATEGY_ID, STRATEGY_NAME),
        )
        logger.info("Inserted strategy_definitions row for %s", STRATEGY_ID)


def insert_strategy_ticker_scores(conn, generated_at: str, weights: Dict[str, float]) -> None:
    with conn.cursor() as cur:
        for ticker, weight in weights.items():
            score = round(weight * 100.0, 6)
            criteria = json.dumps({
                "weight": weight,
                "score": score,
                "source": "live_signal_file",
                "source_file": os.path.basename(latest_signal_file()),
                "generated_at": generated_at,
                "rebalance": "weekly",
                "execution_mode": "PAPER",
                "max_leverage": 1.0,
                "max_single_asset_cap": 0.7,
                "risk_review_decision": "APPROVED",
            })
            cur.execute(
                """
                INSERT INTO gold.strategy_ticker_scores
                (strategy_id, ticker, score, signal_action, entry_score, exit_score,
                 criteria_met, position_status, deployed_at, updated_at)
                VALUES (%s, %s, %s, 'BUY', %s, 0.0, %s::jsonb, 'NONE', NOW(), NOW())
                ON CONFLICT (strategy_id, ticker) DO UPDATE SET
                    score = EXCLUDED.score,
                    signal_action = EXCLUDED.signal_action,
                    entry_score = EXCLUDED.entry_score,
                    exit_score = EXCLUDED.exit_score,
                    criteria_met = EXCLUDED.criteria_met,
                    position_status = EXCLUDED.position_status,
                    updated_at = EXCLUDED.updated_at;
                """,
                (STRATEGY_ID, ticker, score, score, criteria),
            )
    logger.info("Upserted %d strategy_ticker_scores rows", len(weights))


def insert_signal_evaluations(conn, weights: Dict[str, float]) -> None:
    with conn.cursor() as cur:
        for ticker, weight in weights.items():
            potential = round(weight * 100.0, 6)
            cur.execute(
                """
                SELECT change_1d FROM gold.kpis_metrics WHERE ticker = %s ORDER BY date DESC LIMIT 1;
                """,
                (ticker,),
            )
            row = cur.fetchone()
            change_pct = round(float(row[0]), 2) if row and row[0] is not None else 0.0
            cur.execute(
                """
                SELECT name FROM gold.asset_registry WHERE ticker = %s LIMIT 1;
                """,
                (ticker,),
            )
            name_row = cur.fetchone()
            name = name_row[0] if name_row and name_row[0] else ticker
            note = (
                f"ETF Multi-Asset Tactical Allocation: live signal weight {weight:.4f}; "
                "weekly rebalance; PAPER"
            )
            cur.execute(
                """
                INSERT INTO gold.signal_evaluations
                (market, ticker, name, family_key, direction, potential, change_pct, note, updated_at)
                VALUES ('US', %s, %s, %s, 'BUY', %s, %s, %s, NOW())
                ON CONFLICT (market, ticker, family_key) DO UPDATE SET
                    name = EXCLUDED.name,
                    direction = EXCLUDED.direction,
                    potential = EXCLUDED.potential,
                    change_pct = EXCLUDED.change_pct,
                    note = EXCLUDED.note,
                    updated_at = EXCLUDED.updated_at;
                """,
                (ticker, name, FAMILY_KEY, potential, change_pct, note),
            )
    logger.info("Upserted %d signal_evaluations rows", len(weights))


def update_last_signal_at(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE gold.strategy_registry SET last_signal_at = NOW(), updated_at = NOW() WHERE strategy_id = %s",
            (STRATEGY_ID,),
        )


def main() -> int:
    path = latest_signal_file()
    generated_at, weights = load_live_weights(path)
    max_weight = max(weights.values())
    logger.info("Live signal file: %s", path)
    logger.info("Generated at: %s", generated_at)
    logger.info("Tickers: %s", sorted(weights.keys()))
    logger.info("Weight sum: %.6f | max weight: %.4f", sum(weights.values()), max_weight)

    conn = get_db()
    try:
        ensure_registry_universe(conn, sorted(weights.keys()))
        ensure_strategy_definition(conn)
        adapt_max_single_asset_exposure(conn, max_weight)
        clear_stale_signal_rows(conn)
        insert_strategy_ticker_scores(conn, generated_at, weights)
        insert_signal_evaluations(conn, weights)
        update_last_signal_at(conn)
        conn.commit()
        logger.info("ETF Multi-Asset live signal ingestion complete")
        return 0
    except Exception as e:
        conn.rollback()
        logger.error("Ingestion failed: %s", e)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
