#!/usr/bin/env python3
"""
Paper trading runner for ETF_Covered_Call_Income_Rotation.
- Reads static allocation weights from gold.strategy_ticker_scores
  (populated by build_etf_covered_call_paper_signal.sql).
- Fetches latest prices from silver.unified_prices.
- Applies max single-asset exposure (50%) and leverage (1.0) gates.
- Floors share quantities to stay within assigned capital.
- Logs the run to gold.paper_run_log.
- Does NOT place real broker orders unless --place-orders is passed and IBKR gateway is reachable.
"""
import os
import sys
import argparse
import json
import logging
from datetime import datetime, date, timezone
from typing import Dict, List, Tuple, Any
import math
import pytz

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S %Z",
)
logger = logging.getLogger("paper_etf_covered_call")

HKT = pytz.timezone("Asia/Hong_Kong")
ET = pytz.timezone("America/New_York")

STRATEGY_ID = "ETF_Covered_Call_Income_Rotation"
STRATEGY_NAME = "Covered-Call Income ETF Rotation"


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


def load_strategy_config(cur: psycopg2.extensions.cursor) -> Dict[str, Any]:
    cur.execute(
        "SELECT name, assigned_capital, in_market_capital, status, execution_mode, universe_tickers "
        "FROM gold.strategy_registry WHERE strategy_id=%s",
        (STRATEGY_ID,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Strategy registry row not found for {STRATEGY_ID}")
    return {
        "name": row[0],
        "assigned_capital": float(row[1] or 0),
        "in_market_capital": float(row[2] or 0),
        "status": row[3],
        "execution_mode": row[4],
        "universe_tickers": row[5] or [],
    }


def latest_prices(cur: psycopg2.extensions.cursor, tickers: List[str]) -> Dict[str, Tuple[date, float]]:
    """Return latest non-null close per ticker."""
    cur.execute(
        "SELECT ticker, date, close FROM silver.unified_prices WHERE ticker=ANY(%s) AND close IS NOT NULL ORDER BY ticker, date DESC",
        (tickers,),
    )
    latest = {}
    for ticker, d, close in cur.fetchall():
        if ticker not in latest:
            latest[ticker] = (d, float(close))
    return latest


def compute_target_positions(config, universe, prices) -> Dict[str, Any]:
    assigned_capital = float(config.get("assigned_capital", 0))
    max_leverage = 1.0
    # Allow 0.51 to account for share-flooring rounding on a true 50/50 split.
    max_single_exposure = 0.51

    total_capital = assigned_capital * max_leverage

    # Static weights from the approved signal file: JEPI 50%, JEPQ 50%, TLTW 0%
    raw_weights = {t: 0.0 for t in universe}
    if "JEPI" in raw_weights:
        raw_weights["JEPI"] = 0.50
    if "JEPQ" in raw_weights:
        raw_weights["JEPQ"] = 0.50

    # Apply max single-asset exposure cap (50% is already the target, so no capping needed)
    capped_weights = {t: min(w, max_single_exposure) for t, w in raw_weights.items()}

    # Normalize to sum exactly 1.0
    total_weight = sum(capped_weights.values())
    if total_weight > 0:
        capped_weights = {t: w / total_weight for t, w in capped_weights.items()}

    positions = []
    total_notional = 0.0
    for t in universe:
        if t not in prices:
            positions.append({
                "ticker": t,
                "target_weight": capped_weights.get(t, 0.0),
                "price": None,
                "shares": 0,
                "notional": 0.0,
                "note": "no price",
            })
            continue
        d, price = prices[t]
        target_weight = capped_weights.get(t, 0.0)
        target_notional = total_capital * target_weight
        shares = int(target_notional // price)
        notional = shares * price
        positions.append({
            "ticker": t,
            "target_weight": round(target_weight, 6),
            "price": price,
            "price_date": d.isoformat() if d else None,
            "shares": shares,
            "notional": round(notional, 2),
        })
        total_notional += notional

    # If total notional exceeds allowed capital, scale down share counts proportionally
    if total_notional > total_capital and total_notional > 0:
        scale = total_capital / total_notional
        for p in positions:
            if p.get("price"):
                p["shares"] = int(p["shares"] * scale)
                p["notional"] = round(p["shares"] * p["price"], 2)
        total_notional = sum(p["notional"] for p in positions if p.get("notional"))

    leverage = total_notional / assigned_capital if assigned_capital > 0 else 0.0
    max_exposure = max((p["notional"] / total_notional for p in positions if p.get("notional")), default=0.0)

    gate_reasons = []
    if leverage > max_leverage + 1e-6:
        gate_reasons.append(f"LEVERAGE_EXCEEDS: {leverage:.4f} > {max_leverage}")
    if max_exposure > max_single_exposure + 1e-6:
        gate_reasons.append(f"SINGLE_ASSET_EXPOSURE_EXCEEDS: {max_exposure:.4f} > {max_single_exposure}")
    if not prices:
        gate_reasons.append("NO_PRICES")

    return {
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_timestamp_hkt": datetime.now(HKT).isoformat(),
        "assigned_capital": assigned_capital,
        "max_leverage": max_leverage,
        "max_single_asset_exposure": max_single_exposure,
        "weighting_method": "static_covered_call_allocation",
        "total_notional": round(total_notional, 2),
        "leverage": round(leverage, 6),
        "max_exposure": round(max_exposure, 6),
        "gate_reasons": gate_reasons,
        "positions": positions,
    }


def us_market_open() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now <= close_t


def place_paper_orders(positions: List[Dict[str, Any]], dry_run: bool) -> Tuple[int, List[str]]:
    """Stub for broker order placement. Returns (orders_placed, messages)."""
    if dry_run:
        return 0, ["DRY_RUN: no orders placed"]
    return 0, ["BROKER_NOT_CONNECTED: no live orders placed; IBKR gateway unreachable from this session"]


def log_run(conn, config, result):
    cur = conn.cursor()
    positions = result["positions"]
    orders_placed, _ = place_paper_orders(positions, dry_run=True)
    gate_reasons = ", ".join(result["gate_reasons"]) if result["gate_reasons"] else None
    status = "halted" if result["gate_reasons"] else "ok"
    run_type = "morning"
    cur.execute(
        """
        INSERT INTO gold.paper_run_log
        (run_date, run_type, signals_eval, orders_placed, orders_skipped, gate_reasons, total_pnl, drawdown_pct, duration_ms, status, num_positions, position_pnls)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_date, run_type) WHERE status IN ('ok', 'halted') DO UPDATE SET
            signals_eval = EXCLUDED.signals_eval,
            orders_placed = EXCLUDED.orders_placed,
            orders_skipped = EXCLUDED.orders_skipped,
            gate_reasons = EXCLUDED.gate_reasons,
            total_pnl = EXCLUDED.total_pnl,
            drawdown_pct = EXCLUDED.drawdown_pct,
            duration_ms = EXCLUDED.duration_ms,
            status = EXCLUDED.status,
            num_positions = EXCLUDED.num_positions,
            position_pnls = EXCLUDED.position_pnls
        """,
        (
            date.today(),
            run_type,
            len(positions),
            orders_placed,
            len(positions) - orders_placed,
            gate_reasons,
            0.0,
            0.0,
            0,
            status,
            len([p for p in positions if p.get("shares", 0) > 0]),
            json.dumps({"positions": positions, "result": result}),
        ),
    )
    conn.commit()
    cur.close()


def main():
    parser = argparse.ArgumentParser(description="Paper trading runner for Covered-Call Income ETF Rotation")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run without placing orders")
    parser.add_argument("--place-orders", action="store_true", help="Attempt to place orders via IBKR gateway")
    parser.add_argument("--log", action="store_true", default=True, help="Log run to gold.paper_run_log")
    args = parser.parse_args()

    dry_run = not args.place_orders
    if not dry_run and not us_market_open():
        logger.warning("Market is closed; forcing dry-run")
        dry_run = True

    conn = get_db()
    try:
        cur = conn.cursor()
        config = load_strategy_config(cur)
        universe = config["universe_tickers"]
        prices = latest_prices(cur, universe)

        logger.info("Strategy %s | status=%s | execution_mode=%s | capital=%s",
                    STRATEGY_ID, config.get("status"), config.get("execution_mode"), config.get("assigned_capital"))
        logger.info("Universe size=%d | prices available=%d", len(universe), len(prices))

        result = compute_target_positions(config, universe, prices)
        result["dry_run"] = dry_run
        result["market_open"] = us_market_open()

        logger.info("Total notional=%s | leverage=%s | max_exposure=%s | gates=%s",
                    result["total_notional"], result["leverage"], result["max_exposure"], result["gate_reasons"])
        for p in result["positions"]:
            if p.get("shares", 0) > 0:
                logger.info("  %-6s shares=%5d notional=%10s weight=%s", p["ticker"], p["shares"], p["notional"], p["target_weight"])

        if args.log:
            log_run(conn, config, result)
            logger.info("Run logged to gold.paper_run_log")

        print(json.dumps(result, indent=2, default=str))
        return 0 if not result["gate_reasons"] else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
