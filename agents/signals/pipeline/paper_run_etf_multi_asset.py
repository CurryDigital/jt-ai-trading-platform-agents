#!/usr/bin/env python3
"""
Paper trading runner for ETF_Multi_Asset_Tactical_Allocation.
- Reads strategy config from gold.strategy_configs / gold.strategy_definitions / gold.strategy_universes / gold.strategy_thresholds.
- Fetches latest prices from silver.unified_prices (uses most recent non-null close per ticker).
- Computes inverse-12-week-volatility weights.
- Applies max single-asset exposure and leverage gates.
- Floors (not rounds) share quantities to stay within assigned capital.
- Logs the run to gold.paper_run_log.
- Does NOT place real broker orders unless --place-orders is passed and IBKR gateway is reachable.
"""
import os
import sys
import argparse
import json
import logging
from datetime import datetime, date, timedelta, timezone
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
logger = logging.getLogger("paper_etf_multi_asset")

HKT = pytz.timezone("Asia/Hong_Kong")
ET = pytz.timezone("America/New_York")

STRATEGY_ID = "ETF_Multi_Asset_Tactical_Allocation"
STRATEGY_NAME = "Multi-Asset Tactical Allocation"


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
        "SELECT config_key, config_value, description FROM gold.strategy_configs WHERE strategy_id=%s",
        (STRATEGY_ID,),
    )
    config = {}
    for key, value, desc in cur.fetchall():
        config[key] = value

    # Ensure minimum defaults so a freshly-registered strategy runs without prior configs
    config.setdefault("max_leverage", {"value": 1.0})
    config.setdefault("max_single_asset_exposure", {"value": 0.20})
    config.setdefault("weighting_method", {"value": "live_signal_file_weights"})

    cur.execute(
        "SELECT strategy_id, strategy_name, execution_mode, status, parameters "
        "FROM gold.strategy_definitions WHERE strategy_id=%s",
        (STRATEGY_ID,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Strategy definition not found for {STRATEGY_ID}")
    config["_strategy_id"] = row[0]
    config["_strategy_name"] = row[1]
    config["_execution_mode"] = row[2]
    config["_status"] = row[3]
    config["_parameters"] = row[4] or {}

    cur.execute(
        "SELECT name, assigned_capital, in_market_capital, status, execution_mode "
        "FROM gold.strategy_registry WHERE name=%s",
        (STRATEGY_NAME,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Strategy registry row not found for {STRATEGY_NAME}")
    config["_registry_name"] = row[0]
    config["assigned_capital"] = float(row[1] or 0)
    config["in_market_capital"] = float(row[2] or 0)
    config["registry_status"] = row[3]
    config["registry_execution_mode"] = row[4]
    return config


def load_universe(cur: psycopg2.extensions.cursor) -> List[str]:
    """Read the approved universe from the registry (single source of truth)."""
    cur.execute(
        "SELECT universe_tickers FROM gold.strategy_registry WHERE strategy_id=%s",
        (STRATEGY_ID,),
    )
    row = cur.fetchone()
    if row and row[0]:
        return sorted(row[0])
    # Fallback to the legacy table if registry is empty
    cur.execute(
        "SELECT ticker FROM gold.strategy_universes WHERE strategy_id=%s AND is_active ORDER BY ticker",
        (STRATEGY_ID,),
    )
    return [r[0] for r in cur.fetchall()]


def load_thresholds(cur: psycopg2.extensions.cursor) -> Dict[str, Tuple[float, float, str]]:
    cur.execute(
        "SELECT metric_name, min_value, max_value, trigger_action FROM gold.strategy_thresholds WHERE strategy_id=%s",
        (STRATEGY_ID,),
    )
    return {r[0]: (float(r[1] or 0), float(r[2] or 0), r[3]) for r in cur.fetchall()}


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


def volatility_12_week(cur: psycopg2.extensions.cursor, tickers: List[str]) -> Dict[str, float]:
    """Compute annualized realized volatility from ~12 weeks of daily returns."""
    end = date.today()
    start = end - timedelta(days=120)
    cur.execute(
        "SELECT ticker, date, close FROM silver.unified_prices "
        "WHERE ticker=ANY(%s) AND date BETWEEN %s AND %s AND close IS NOT NULL "
        "ORDER BY ticker, date ASC",
        (tickers, start, end),
    )
    series = {t: [] for t in tickers}
    for ticker, d, close in cur.fetchall():
        series[ticker].append((d, float(close)))

    vols = {}
    for ticker, points in series.items():
        if len(points) < 30:
            logger.warning("Insufficient history for %s (%d days), using fallback vol=0.20", ticker, len(points))
            vols[ticker] = 0.20
            continue
        closes = [c for _, c in points]
        returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        if not returns or len(returns) < 2:
            vols[ticker] = 0.20
            continue
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        daily_vol = math.sqrt(variance)
        ann_vol = daily_vol * math.sqrt(252)
        vols[ticker] = max(ann_vol, 0.001)  # avoid divide by zero
    return vols


def load_weights_from_db(cur: psycopg2.extensions.cursor, tickers: List[str]) -> Dict[str, float]:
    """Read the live target weights from gold.strategy_ticker_scores."""
    cur.execute(
        "SELECT ticker, score FROM gold.strategy_ticker_scores WHERE strategy_id=%s AND ticker=ANY(%s)",
        (STRATEGY_ID, tickers),
    )
    weights = {ticker: float(score) / 100.0 for ticker, score in cur.fetchall() if score is not None}
    if not weights:
        logger.warning("No live weights in DB for %s; falling back to inverse-12-week-volatility", STRATEGY_ID)
    return weights


def inverse_vol_weights(vols: Dict[str, float], max_single_exposure: float) -> Dict[str, float]:
    """Compute inverse-vol weights with a single-asset cap."""
    inv_vols = {t: 1.0 / v for t, v in vols.items() if v > 0}
    total_inv = sum(inv_vols.values())
    if total_inv <= 0:
        return {}
    raw = {t: inv_vols[t] / total_inv for t in inv_vols}

    capped = dict(raw)
    while True:
        over = {t: w for t, w in capped.items() if w > max_single_exposure + 1e-12}
        if not over:
            break
        excess = sum(w - max_single_exposure for w in over.values())
        for t in over:
            capped[t] = max_single_exposure
        room = {t: max_single_exposure - w for t, w in capped.items() if w < max_single_exposure - 1e-12}
        total_room = sum(room.values())
        if total_room <= 0:
            break
        for t in room:
            capped[t] += excess * (room[t] / total_room)

    total_weight = sum(capped.values())
    if total_weight > 0:
        capped = {t: w / total_weight for t, w in capped.items()}
    return capped


def compute_target_positions(config, thresholds, universe, prices, vols, weights_from_db: Dict[str, float]) -> Dict[str, Any]:
    assigned_capital = float(config.get("assigned_capital", 0))
    max_leverage = float(config.get("max_leverage", {}).get("value", 1.0))
    max_single_exposure = float(config.get("max_single_asset_exposure", {}).get("value", 0.20))

    total_capital = assigned_capital * max_leverage

    if weights_from_db:
        weighting_method = "live_signal_file_weights"
        capped_weights = {t: weights_from_db.get(t, 0.0) for t in universe}
        # Re-normalize to sum exactly 1.0 in case of missing tickers
        total = sum(capped_weights.values())
        if total > 0:
            capped_weights = {t: w / total for t, w in capped_weights.items()}
        # Apply single-asset cap if the live file exceeded it
        if max(capped_weights.values(), default=0) > max_single_exposure + 1e-12:
            logger.warning("Live weight exceeds max_single_asset_exposure %.4f; capping", max_single_exposure)
            capped_weights = inverse_vol_weights({t: 1.0 / max(w, 0.0001) for t, w in capped_weights.items()}, max_single_exposure)
    else:
        weighting_method = "inverse_12_week_volatility_fallback"
        capped_weights = inverse_vol_weights(vols, max_single_exposure)

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
        # Floor shares (not round) to ensure we do not exceed capital
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
        "weighting_method": weighting_method,
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
    # TODO: integrate with IBKR gateway order API when available
    return 0, ["BROKER_NOT_CONNECTED: no live orders placed; IBKR gateway unreachable from this session"]


def log_run(conn, config, result):
    cur = conn.cursor()
    positions = result["positions"]
    orders_placed, _ = place_paper_orders(positions, dry_run=True)
    gate_reasons = ", ".join(result["gate_reasons"]) if result["gate_reasons"] else None
    status = "halted" if result["gate_reasons"] else "ok"
    run_type = "morning"  # allowed: morning, eod, weekly_review
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
    global args
    parser = argparse.ArgumentParser(description="Paper trading runner for ETF Multi-Asset Tactical Allocation")
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
        thresholds = load_thresholds(cur)
        universe = load_universe(cur)
        prices = latest_prices(cur, universe)
        vols = volatility_12_week(cur, universe)
        weights_from_db = load_weights_from_db(cur, universe)

        logger.info("Strategy %s | status=%s | execution_mode=%s | capital=%s",
                    STRATEGY_ID, config.get("_status"), config.get("_execution_mode"), config.get("assigned_capital"))
        logger.info("Universe size=%d | prices available=%d | vols computed=%d | db_weights=%d",
                    len(universe), len(prices), len(vols), len(weights_from_db))

        result = compute_target_positions(config, thresholds, universe, prices, vols, weights_from_db)
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
